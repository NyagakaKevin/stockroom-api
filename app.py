"""Stockroom: authenticated, shop-scoped inventory API."""
import hashlib
import os
import secrets
import sqlite3
import time
from functools import wraps

from flask import Flask, g, jsonify, request
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash, generate_password_hash

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS shops (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, owner_id INTEGER NOT NULL REFERENCES users(id));
CREATE TABLE IF NOT EXISTS memberships (
 shop_id INTEGER NOT NULL REFERENCES shops(id), user_id INTEGER NOT NULL REFERENCES users(id),
 role TEXT NOT NULL CHECK(role IN ('owner','staff')), PRIMARY KEY(shop_id,user_id));
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), expires_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS login_attempts (
 email TEXT NOT NULL, attempted_at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS login_attempts_email_time ON login_attempts(email,attempted_at);
CREATE TABLE IF NOT EXISTS items (
 id INTEGER PRIMARY KEY, shop_id INTEGER NOT NULL REFERENCES shops(id), sku TEXT NOT NULL,
 name TEXT NOT NULL, quantity INTEGER NOT NULL CHECK(quantity>=0), created_at INTEGER NOT NULL,
 UNIQUE(shop_id,sku));
CREATE TABLE IF NOT EXISTS movements (
 id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL REFERENCES items(id),
 actor_id INTEGER NOT NULL REFERENCES users(id), change INTEGER NOT NULL, reason TEXT NOT NULL,
 created_at INTEGER NOT NULL);
"""


class APIError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


def create_app(config=None):
    app = Flask(__name__)
    app.config.update(DATABASE=os.getenv('STOCKROOM_DB', 'stockroom-v2.db'),
                      MAX_CONTENT_LENGTH=16384, SESSION_TTL=3600,
                      LOGIN_LIMIT=5, LOGIN_WINDOW=900)
    if config:
        app.config.update(config)
    with sqlite3.connect(app.config['DATABASE']) as db:
        # Never silently assign legacy unscoped inventory to a user.
        columns = {row[1] for row in db.execute('PRAGMA table_info(items)')}
        if columns and 'shop_id' not in columns:
            raise RuntimeError('Legacy database detected. Back it up and use a new STOCKROOM_DB path.')
        db.executescript(SCHEMA)

    def connect():
        if 'db' not in g:
            g.db = sqlite3.connect(app.config['DATABASE'], timeout=10)
            g.db.row_factory = sqlite3.Row
            g.db.execute('PRAGMA foreign_keys=ON')
        return g.db

    @app.teardown_appcontext
    def close_db(_error):
        db = g.pop('db', None)
        if db is not None:
            db.close()

    @app.errorhandler(APIError)
    def api_error(error):
        return jsonify(error=error.message), error.status

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error=error.description), error.code

    @app.errorhandler(sqlite3.OperationalError)
    def database_error(error):
        app.logger.error('Database operation failed: %s', error)
        return jsonify(error='Database temporarily unavailable'), 503

    @app.after_request
    def headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        return response

    def payload():
        value = request.get_json(silent=True)
        if not isinstance(value, dict):
            raise APIError(400, 'Expected a JSON object')
        return value

    def text(value, field, limit):
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= limit:
            raise APIError(400, f'{field} must contain 1–{limit} characters')
        return value.strip()

    def credentials(data):
        email = text(data.get('email'), 'email', 254).lower()
        if '@' not in email or email.startswith('@') or email.endswith('@'):
            raise APIError(400, 'Valid email required')
        password = data.get('password')
        if not isinstance(password, str) or not 12 <= len(password) <= 128:
            raise APIError(400, 'Password must contain 12–128 characters')
        return email, password

    def authenticated(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            parts = request.headers.get('Authorization', '').split()
            if len(parts) != 2 or parts[0].lower() != 'bearer' or len(parts[1]) > 128:
                raise APIError(401, 'Authentication required')
            token_hash = hashlib.sha256(parts[1].encode()).hexdigest()
            session = connect().execute('SELECT * FROM sessions WHERE token_hash=? AND expires_at>?',
                                        (token_hash, int(time.time()))).fetchone()
            if session is None:
                raise APIError(401, 'Invalid or expired session')
            g.user_id, g.token_hash = session['user_id'], token_hash
            return fn(*args, **kwargs)
        return wrapped

    def membership(shop_id, owner=False):
        row = connect().execute('SELECT role FROM memberships WHERE shop_id=? AND user_id=?',
                                (shop_id, g.user_id)).fetchone()
        if row is None:
            raise APIError(404, 'Shop not found')
        if owner and row['role'] != 'owner':
            raise APIError(403, 'Owner permission required')

    def item(shop_id, item_id):
        row = connect().execute('SELECT * FROM items WHERE id=? AND shop_id=?',
                                (item_id, shop_id)).fetchone()
        if row is None:
            raise APIError(404, 'Item not found')
        return row

    @app.get('/health')
    def health():
        connect().execute('SELECT 1').fetchone()
        return jsonify(status='ok')

    @app.post('/auth/register')
    def register():
        email, password = credentials(payload())
        password_hash = generate_password_hash(password, method='scrypt')
        db = connect()
        try:
            with db:
                cur = db.execute('INSERT INTO users(email,password_hash) VALUES(?,?)', (email, password_hash))
        except sqlite3.IntegrityError:
            raise APIError(409, 'Account already exists')
        return jsonify(id=cur.lastrowid, email=email), 201

    @app.post('/auth/login')
    def login():
        email, password = credentials(payload())
        db, now = connect(), int(time.time())
        # Persist attempt limits so multiple WSGI workers share the same counter.
        with db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM login_attempts WHERE attempted_at<?', (now-app.config['LOGIN_WINDOW'],))
            count = db.execute('SELECT COUNT(*) FROM login_attempts WHERE email=?', (email,)).fetchone()[0]
            if count >= app.config['LOGIN_LIMIT']:
                raise APIError(429, 'Too many login attempts; try again later')
            db.execute('INSERT INTO login_attempts VALUES(?,?)', (email, now))
        user = db.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
        stored_hash = user['password_hash'] if user else dummy_hash
        valid = check_password_hash(stored_hash, password)
        if not user or not valid:
            raise APIError(401, 'Invalid email or password')
        token = secrets.token_urlsafe(32)
        expires = now + app.config['SESSION_TTL']
        with db:
            db.execute('DELETE FROM sessions WHERE expires_at<=?', (now,))
            db.execute('INSERT INTO sessions VALUES(?,?,?)',
                       (hashlib.sha256(token.encode()).hexdigest(), user['id'], expires))
        return jsonify(access_token=token, token_type='Bearer', expires_at=expires)

    dummy_hash = generate_password_hash(secrets.token_urlsafe(32), method='scrypt')

    @app.post('/auth/logout')
    @authenticated
    def logout():
        db = connect()
        with db:
            db.execute('DELETE FROM sessions WHERE token_hash=?', (g.token_hash,))
        return '', 204

    @app.get('/shops')
    @authenticated
    def shops():
        rows = connect().execute('SELECT s.id,s.name,m.role FROM shops s JOIN memberships m ON s.id=m.shop_id WHERE m.user_id=? ORDER BY s.id', (g.user_id,)).fetchall()
        return jsonify(shops=[dict(row) for row in rows])

    @app.post('/shops')
    @authenticated
    def create_shop():
        name, db = text(payload().get('name'), 'name', 120), connect()
        with db:
            cur = db.execute('INSERT INTO shops(name,owner_id) VALUES(?,?)', (name, g.user_id))
            db.execute("INSERT INTO memberships VALUES(?,?,'owner')", (cur.lastrowid, g.user_id))
        return jsonify(id=cur.lastrowid, name=name, role='owner'), 201

    @app.post('/shops/<int:shop_id>/members')
    @authenticated
    def add_member(shop_id):
        membership(shop_id, owner=True)
        email = text(payload().get('email'), 'email', 254).lower()
        db = connect()
        user = db.execute('SELECT id FROM users WHERE email=?', (email,)).fetchone()
        if user is None:
            raise APIError(404, 'Registered user not found')
        try:
            with db:
                db.execute("INSERT INTO memberships VALUES(?,?,'staff')", (shop_id, user['id']))
        except sqlite3.IntegrityError:
            raise APIError(409, 'Already a member')
        return jsonify(user_id=user['id'], role='staff'), 201

    @app.get('/shops/<int:shop_id>/items')
    @authenticated
    def list_items(shop_id):
        membership(shop_id)
        try:
            limit, offset = int(request.args.get('limit', 20)), int(request.args.get('offset', 0))
        except ValueError:
            raise APIError(400, 'limit and offset must be integers')
        if not 1 <= limit <= 100 or offset < 0:
            raise APIError(400, 'limit must be 1–100 and offset nonnegative')
        db = connect()
        rows = db.execute('SELECT * FROM items WHERE shop_id=? ORDER BY id LIMIT ? OFFSET ?', (shop_id, limit, offset)).fetchall()
        total = db.execute('SELECT COUNT(*) FROM items WHERE shop_id=?', (shop_id,)).fetchone()[0]
        return jsonify(items=[dict(row) for row in rows], total=total, limit=limit, offset=offset)

    @app.post('/shops/<int:shop_id>/items')
    @authenticated
    def create_item(shop_id):
        membership(shop_id)
        data, db = payload(), connect()
        sku, name = text(data.get('sku'), 'sku', 40), text(data.get('name'), 'name', 120)
        quantity = data.get('quantity', 0)
        if type(quantity) is not int or not 0 <= quantity <= 2147483647:
            raise APIError(400, 'quantity must be a nonnegative 32-bit integer')
        try:
            with db:
                cur = db.execute('INSERT INTO items(shop_id,sku,name,quantity,created_at) VALUES(?,?,?,?,?)', (shop_id, sku, name, quantity, int(time.time())))
                if quantity:
                    db.execute('INSERT INTO movements(item_id,actor_id,change,reason,created_at) VALUES(?,?,?,?,?)', (cur.lastrowid, g.user_id, quantity, 'Opening stock', int(time.time())))
        except sqlite3.IntegrityError:
            raise APIError(409, 'SKU already exists in this shop')
        return jsonify(dict(item(shop_id, cur.lastrowid))), 201

    @app.get('/shops/<int:shop_id>/items/<int:item_id>')
    @authenticated
    def get_item(shop_id, item_id):
        membership(shop_id)
        return jsonify(dict(item(shop_id, item_id)))

    @app.post('/shops/<int:shop_id>/items/<int:item_id>/adjust')
    @authenticated
    def adjust(shop_id, item_id):
        membership(shop_id)
        item(shop_id, item_id)
        data, db = payload(), connect()
        change = data.get('change')
        reason = text(data.get('reason'), 'reason', 160)
        if type(change) is not int or change == 0 or not -2147483647 <= change <= 2147483647:
            raise APIError(400, 'change must be a nonzero 32-bit integer')
        with db:
            cur = db.execute('UPDATE items SET quantity=quantity+? WHERE id=? AND shop_id=? AND quantity+? BETWEEN 0 AND 2147483647', (change, item_id, shop_id, change))
            if cur.rowcount != 1:
                raise APIError(409, 'Adjustment would put stock outside allowed range')
            db.execute('INSERT INTO movements(item_id,actor_id,change,reason,created_at) VALUES(?,?,?,?,?)', (item_id, g.user_id, change, reason, int(time.time())))
        return jsonify(dict(item(shop_id, item_id)))

    @app.get('/shops/<int:shop_id>/items/<int:item_id>/movements')
    @authenticated
    def movements(shop_id, item_id):
        membership(shop_id)
        item(shop_id, item_id)
        rows = connect().execute('SELECT * FROM movements WHERE item_id=? ORDER BY id DESC LIMIT 100', (item_id,)).fetchall()
        return jsonify(movements=[dict(row) for row in rows])

    return app


if __name__ == '__main__':
    create_app().run(host='127.0.0.1', port=int(os.getenv('PORT', '8000')), debug=False)

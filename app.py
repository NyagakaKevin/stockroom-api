"""A small inventory API built with Python and SQLite."""
import json
import os
import sqlite3
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

DB_PATH = os.getenv("STOCKROOM_DB", "stockroom.db")


def connect():
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


def init_db():
    with connect() as db:
        db.execute("CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY, sku TEXT NOT NULL UNIQUE, name TEXT NOT NULL, quantity INTEGER NOT NULL DEFAULT 0 CHECK(quantity >= 0), created_at TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS movements (id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL REFERENCES items(id), change INTEGER NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL)")


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class APIError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class Handler(BaseHTTPRequestHandler):
    def respond(self, status, value):
        data = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def payload(self):
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 1 <= size <= 16384:
                raise ValueError
            value = json.loads(self.rfile.read(size))
            if not isinstance(value, dict):
                raise ValueError
            return value
        except (ValueError, UnicodeDecodeError):
            raise APIError(400, "Expected a JSON object of at most 16384 bytes")

    def route(self):
        url = urlparse(self.path)
        parts = [part for part in url.path.split("/") if part]
        with connect() as db:
            if parts == ["health"] and self.command == "GET":
                return 200, {"status": "ok"}
            if parts == ["items"] and self.command == "GET":
                try:
                    limit = int(parse_qs(url.query).get("limit", [20])[0])
                    offset = int(parse_qs(url.query).get("offset", [0])[0])
                except ValueError:
                    raise APIError(400, "limit and offset must be integers")
                if not 1 <= limit <= 100 or offset < 0:
                    raise APIError(400, "limit must be 1–100 and offset nonnegative")
                items = db.execute("SELECT * FROM items ORDER BY id LIMIT ? OFFSET ?", (limit, offset)).fetchall()
                total = db.execute("SELECT COUNT(*) FROM items").fetchone()[0]
                return 200, {"items": [dict(item) for item in items], "total": total, "limit": limit, "offset": offset}
            if parts == ["items"] and self.command == "POST":
                data = self.payload()
                sku, name, quantity = data.get("sku"), data.get("name"), data.get("quantity", 0)
                if not isinstance(sku, str) or not 1 <= len(sku.strip()) <= 40 or not isinstance(name, str) or not 1 <= len(name.strip()) <= 120:
                    raise APIError(400, "sku and name are required strings")
                if type(quantity) is not int or quantity < 0:
                    raise APIError(400, "quantity must be a nonnegative integer")
                try:
                    with db:
                        cursor = db.execute("INSERT INTO items(sku,name,quantity,created_at) VALUES(?,?,?,?)", (sku.strip(), name.strip(), quantity, timestamp()))
                        if quantity:
                            db.execute("INSERT INTO movements(item_id,change,reason,created_at) VALUES(?,?,?,?)", (cursor.lastrowid, quantity, "Opening stock", timestamp()))
                except sqlite3.IntegrityError:
                    raise APIError(409, "SKU already exists")
                return 201, dict(db.execute("SELECT * FROM items WHERE id=?", (cursor.lastrowid,)).fetchone())
            if len(parts) >= 2 and parts[0] == "items":
                try:
                    item_id = int(parts[1])
                    if item_id < 1:
                        raise ValueError
                except ValueError:
                    raise APIError(404, "Item not found")
                item = db.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
                if item is None:
                    raise APIError(404, "Item not found")
                if len(parts) == 2 and self.command == "GET":
                    return 200, dict(item)
                if len(parts) == 3 and parts[2] == "movements" and self.command == "GET":
                    rows = db.execute("SELECT * FROM movements WHERE item_id=? ORDER BY id DESC LIMIT 100", (item_id,)).fetchall()
                    return 200, {"movements": [dict(row) for row in rows]}
                if len(parts) == 3 and parts[2] == "adjust" and self.command == "POST":
                    data = self.payload()
                    change, reason = data.get("change"), data.get("reason")
                    if type(change) is not int or change == 0 or not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 160:
                        raise APIError(400, "change must be a nonzero integer and reason is required")
                    with db:
                        cursor = db.execute("UPDATE items SET quantity=quantity+? WHERE id=? AND quantity+? >= 0", (change, item_id, change))
                        if cursor.rowcount == 0:
                            raise APIError(409, "Insufficient stock")
                        db.execute("INSERT INTO movements(item_id,change,reason,created_at) VALUES(?,?,?,?)", (item_id, change, reason.strip(), timestamp()))
                    return 200, dict(db.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone())
            raise APIError(404, "Route not found")

    def dispatch(self):
        try:
            status, result = self.route()
            self.respond(status, result)
        except APIError as error:
            self.respond(error.status, {"error": str(error)})
        except (ValueError, OverflowError):
            self.respond(400, {"error": "Invalid request"})

    do_GET = dispatch
    do_POST = dispatch


if __name__ == "__main__":
    init_db()
    port = int(os.getenv("PORT", "8000"))
    print(f"Stockroom API listening on http://localhost:{port}")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()

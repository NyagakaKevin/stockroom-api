import hashlib
import sqlite3
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app import create_app


class APITest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / 'test.db')
        self.app = create_app({'TESTING': True, 'DATABASE': self.path})
        self.client = self.app.test_client()
        self.a = self.account('owner-a@example.test')
        self.b = self.account('owner-b@example.test')
        self.shop_a = self.post('/shops', {'name': 'Shop A'}, self.a).json['id']
        self.shop_b = self.post('/shops', {'name': 'Shop B'}, self.b).json['id']
        self.item = self.post(f'/shops/{self.shop_a}/items', {'sku': 'PAD', 'name': 'Controller', 'quantity': 1}, self.a).json['id']
        self.route = f'/shops/{self.shop_a}/items/{self.item}'

    def tearDown(self):
        self.tmp.cleanup()

    def account(self, email):
        data = {'email': email, 'password': 'long-password-123'}
        self.assertEqual(self.client.post('/auth/register', json=data).status_code, 201)
        response = self.client.post('/auth/login', json=data)
        self.assertEqual(response.status_code, 200)
        return response.json['access_token']

    def post(self, path, data, token):
        return self.client.post(path, json=data, headers={'Authorization': f'Bearer {token}'})

    def get(self, path, token):
        return self.client.get(path, headers={'Authorization': f'Bearer {token}'})

    def test_authentication_required_and_invalid_tokens(self):
        self.assertEqual(self.client.get('/shops').status_code, 401)
        self.assertEqual(self.get('/shops', 'forged').status_code, 401)
        self.assertEqual(self.client.get('/health').status_code, 200)
        self.assertEqual(self.client.get('/items').status_code, 404)

    def test_password_and_token_are_not_stored_plaintext(self):
        with sqlite3.connect(self.path) as db:
            stored = db.execute('SELECT password_hash FROM users LIMIT 1').fetchone()[0]
            self.assertTrue(stored.startswith('scrypt:'))
            self.assertNotIn('long-password-123', stored)
            tokens = [r[0] for r in db.execute('SELECT token_hash FROM sessions')]
            self.assertNotIn(self.a, tokens)
            self.assertIn(hashlib.sha256(self.a.encode()).hexdigest(), tokens)

    def test_logout_revokes_and_expiry_rejects_session(self):
        self.assertEqual(self.post('/auth/logout', {}, self.a).status_code, 204)
        self.assertEqual(self.get('/shops', self.a).status_code, 401)
        with sqlite3.connect(self.path) as db:
            db.execute('UPDATE sessions SET expires_at=?', (int(time.time())-1,))
        self.assertEqual(self.get('/shops', self.b).status_code, 401)

    def test_invalid_login_and_shared_rate_limit(self):
        data = {'email': 'missing@example.test', 'password': 'long-password-123'}
        for _ in range(5):
            self.assertEqual(self.client.post('/auth/login', json=data).status_code, 401)
        second_app = create_app({'TESTING': True, 'DATABASE': self.path})
        self.assertEqual(second_app.test_client().post('/auth/login', json=data).status_code, 429)

    def test_cross_shop_reads_and_writes_are_denied(self):
        for path in [f'/shops/{self.shop_a}/items', self.route, self.route+'/movements']:
            self.assertEqual(self.get(path, self.b).status_code, 404)
        self.assertEqual(self.post(self.route+'/adjust', {'change': -1, 'reason': 'Steal'}, self.b).status_code, 404)
        # Membership in Shop B cannot grant access to a Shop A item through a substituted URL.
        self.assertEqual(self.get(f'/shops/{self.shop_b}/items/{self.item}', self.b).status_code, 404)
        self.assertEqual(self.get(self.route, self.a).json['quantity'], 1)
        self.assertEqual(self.get('/shops', self.b).json['shops'][0]['id'], self.shop_b)

    def test_owner_and_staff_permissions(self):
        self.assertEqual(self.post(f'/shops/{self.shop_a}/members', {'email': 'owner-b@example.test', 'role': 'owner'}, self.a).status_code, 201)
        self.assertEqual(self.get(self.route, self.b).status_code, 200)
        self.assertEqual(self.post(self.route+'/adjust', {'change': 1, 'reason': 'Received'}, self.b).status_code, 200)
        self.assertEqual(self.post(f'/shops/{self.shop_a}/members', {'email': 'new@example.test'}, self.b).status_code, 403)
        self.assertEqual(self.get('/shops', self.b).json['shops'][0]['role'], 'staff')

    def test_sku_uniqueness_is_per_shop(self):
        data = {'sku': 'PAD', 'name': 'Other'}
        self.assertEqual(self.post(f'/shops/{self.shop_a}/items', data, self.a).status_code, 409)
        self.assertEqual(self.post(f'/shops/{self.shop_b}/items', data, self.b).status_code, 201)

    def test_validation_and_pagination(self):
        root = f'/shops/{self.shop_a}/items'
        for quantity in [True, -1, 1.5, 2147483648]:
            self.assertEqual(self.post(root, {'sku': 'BAD', 'name': 'Bad', 'quantity': quantity}, self.a).status_code, 400)
        for query in ['limit=0', 'limit=101', 'offset=-1', 'limit=no']:
            self.assertEqual(self.get(root+'?'+query, self.a).status_code, 400)
        self.assertEqual(self.get(root+'?limit=1&offset=1', self.a).json['items'], [])
        response = self.client.post(root, data='[]', content_type='application/json', headers={'Authorization': f'Bearer {self.a}'})
        self.assertEqual(response.status_code, 400)
        response = self.client.post(root, data='x'*17000, content_type='application/json', headers={'Authorization': f'Bearer {self.a}'})
        self.assertEqual(response.status_code, 413)

    def test_stock_history_and_failed_adjustment(self):
        response = self.post(self.route+'/adjust', {'change': -2, 'reason': 'Oversell'}, self.a)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.get(self.route, self.a).json['quantity'], 1)
        self.assertEqual(len(self.get(self.route+'/movements', self.a).json['movements']), 1)
        self.assertEqual(self.post(self.route+'/adjust', {'change': -1, 'reason': 'Sold'}, self.a).status_code, 200)
        movement = self.get(self.route+'/movements', self.a).json['movements'][0]
        self.assertEqual(movement['change'], -1)
        self.assertIn('actor_id', movement)

    def test_rollback_when_audit_insert_fails(self):
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TRIGGER reject_movement BEFORE INSERT ON movements BEGIN SELECT RAISE(ABORT,'injected failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.post(self.route+'/adjust', {'change': 2, 'reason': 'Received'}, self.a)
        self.assertEqual(self.get(self.route, self.a).json['quantity'], 1)

    def test_two_requests_cannot_sell_the_last_item(self):
        def sell(_):
            with self.app.test_client() as client:
                return client.post(self.route+'/adjust', json={'change': -1, 'reason': 'Sold'}, headers={'Authorization': f'Bearer {self.a}'}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = sorted(pool.map(sell, range(2)))
        self.assertEqual(statuses, [200, 409])
        self.assertEqual(self.get(self.route, self.a).json['quantity'], 0)
        self.assertEqual(len(self.get(self.route+'/movements', self.a).json['movements']), 2)

    def test_restart_preserves_data_and_sessions(self):
        restarted = create_app({'TESTING': True, 'DATABASE': self.path}).test_client()
        self.assertEqual(restarted.get(self.route, headers={'Authorization': f'Bearer {self.a}'}).json['quantity'], 1)

    def test_legacy_database_is_rejected_without_modification(self):
        legacy = str(Path(self.tmp.name) / 'legacy.db')
        with sqlite3.connect(legacy) as db:
            db.execute('CREATE TABLE items(id INTEGER PRIMARY KEY, sku TEXT)')
            db.execute("INSERT INTO items VALUES(1,'OLD')")
        with self.assertRaisesRegex(RuntimeError, 'Legacy database'):
            create_app({'DATABASE': legacy})
        with sqlite3.connect(legacy) as db:
            self.assertEqual(db.execute('SELECT sku FROM items').fetchone()[0], 'OLD')


if __name__ == '__main__':
    unittest.main()

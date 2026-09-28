import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class APITest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        cls.base = f"http://127.0.0.1:{port}"
        env = {**os.environ, "PORT": str(port), "STOCKROOM_DB": os.path.join(cls.tmp.name, "test.db")}
        cls.proc = subprocess.Popen([sys.executable, "app.py"], cwd=os.path.dirname(os.path.dirname(__file__)), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(60):
            try:
                urlopen(cls.base + "/health", timeout=.2)
                break
            except OSError:
                time.sleep(.05)
        else:
            raise RuntimeError("API did not start")

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(timeout=5)
        cls.tmp.cleanup()

    def api(self, path, body=None):
        req = Request(self.base + path, data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json"})
        try:
            with urlopen(req) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)

    def test_inventory_lifecycle(self):
        status, item = self.api("/items", {"sku": "PAD-001", "name": "Controller", "quantity": 5})
        self.assertEqual(status, 201)
        item_id = item["id"]
        self.assertEqual(self.api("/items", {"sku": "PAD-001", "name": "Duplicate"})[0], 409)
        self.assertEqual(self.api(f"/items/{item_id}/adjust", {"change": -2, "reason": "Sold"})[1]["quantity"], 3)
        self.assertEqual(self.api(f"/items/{item_id}/adjust", {"change": -4, "reason": "Oversell"})[0], 409)
        self.assertEqual(self.api(f"/items/{item_id}/movements")[1]["movements"][0]["change"], -2)
        self.assertEqual(self.api(f"/items/{item_id}")[1]["quantity"], 3)
        self.assertEqual(self.api("/items?limit=1&offset=0")[1]["total"], 1)
        self.assertEqual(self.api("/items?limit=0")[0], 400)
        self.assertEqual(self.api("/items", {"sku": "X", "name": "Bad", "quantity": True})[0], 400)

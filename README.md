# Stockroom API

A Python backend for tracking shop inventory. Built by Kevin Nyagaka to demonstrate HTTP APIs, SQLite transactions, validation, pagination, and a stock movement audit trail. No third party packages are required.

## Run

Requires Python 3.10+.

```bash
python3 app.py
```

The server runs at `http://localhost:8000`. Set `PORT` to change the port or `STOCKROOM_DB` to set the SQLite file path. The database is created automatically.

## Try it

```bash
curl -X POST http://localhost:8000/items -H 'Content-Type: application/json' -d '{"sku":"PAD-001","name":"Game controller","quantity":5}'
curl 'http://localhost:8000/items?limit=20&offset=0'
curl -X POST http://localhost:8000/items/1/adjust -H 'Content-Type: application/json' -d '{"change":-2,"reason":"Sold two"}'
curl http://localhost:8000/items/1/movements
```

## API

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/health` | Health status |
| GET | `/items?limit=20&offset=0` | Paginated items and total count |
| POST | `/items` | Create item with `sku`, `name`, and optional `quantity` |
| GET | `/items/{id}` | Fetch one item |
| POST | `/items/{id}/adjust` | Adjust stock with `change` and `reason` |
| GET | `/items/{id}/movements` | Latest 100 movements |

All responses are JSON. Invalid input returns HTTP 400; unknown records return 404; duplicate SKU or insufficient stock returns 409. See [API documentation](docs/API.md) for request and response examples.

## Verify

```bash
python3 -m unittest discover -s tests -v
```

## Design

Each adjustment and its movement record share a SQLite transaction. A conditional update prevents concurrent requests from making stock negative. This demo has no user authentication and should not be used for real inventory until access control is added.

# API documentation

Base URL: `http://localhost:8000`. Send JSON request bodies with `Content-Type: application/json`.

| Request | Body | Success response |
| --- | --- | --- |
| `GET /health` | None | `200 {"status":"ok"}` |
| `POST /items` | `{"sku":"PAD-001","name":"Game controller","quantity":5}` | `201` item record |
| `GET /items?limit=20&offset=0` | None | `200 {"items":[...],"total":1,"limit":20,"offset":0}` |
| `GET /items/1` | None | `200` item record |
| `POST /items/1/adjust` | `{"change":-2,"reason":"Sold two"}` | `200` updated item record |
| `GET /items/1/movements` | None | `200 {"movements":[...]}` newest first |

An item record looks like `{"id":1,"sku":"PAD-001","name":"Game controller","quantity":5,"created_at":"2026-09-28T07:00:00+00:00"}`. A movement looks like `{"id":1,"item_id":1,"change":5,"reason":"Opening stock","created_at":"2026-09-28T07:00:00+00:00"}`. Creating an item with positive quantity records an opening movement.

`limit` accepts 1–100 and defaults to 20. `offset` is nonnegative and defaults to 0. `sku` is unique and 1–40 characters; `name` is 1–120 characters; `quantity` is a nonnegative integer. Adjustments need a nonzero integer change and a reason of 1–160 characters. Excessive deductions return `409 {"error":"Insufficient stock"}`. Other errors use the shape `{"error":"Message"}`.

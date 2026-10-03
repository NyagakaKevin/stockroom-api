# API contract

All request bodies are JSON objects. Protected routes require `Authorization: Bearer <access_token>`. Tokens expire after one hour and logout revokes the current token. Use HTTPS outside localhost; keep passwords and tokens out of logs, URLs and source control.

| Method | Path | Body / purpose |
| --- | --- | --- |
| GET | `/health` | Public database readiness check |
| POST | `/auth/register` | `email`, `password` (12–128 characters); returns user, 201 |
| POST | `/auth/login` | `email`, `password`; returns `access_token`, `token_type`, Unix `expires_at` |
| POST | `/auth/logout` | Revoke current session, 204 |
| GET | `/shops` | Current user's memberships |
| POST | `/shops` | `name`; creates shop and owner membership, 201 |
| POST | `/shops/{shop}/members` | Owner only: registered user's `email`; grants staff, 201 |
| GET | `/shops/{shop}/items?limit=20&offset=0` | Items, total, limit and offset; limit 1–100 |
| POST | `/shops/{shop}/items` | `sku`, `name`, optional `quantity` (default 0), 201 |
| GET | `/shops/{shop}/items/{item}` | Shop-scoped item |
| POST | `/shops/{shop}/items/{item}/adjust` | Nonzero integer `change`, `reason` |
| GET | `/shops/{shop}/items/{item}/movements` | Latest 100 changes with actor ID |

Example workflow: register, log in, create a shop, create `{ "sku": "PEN-01", "name": "Blue pen", "quantity": 10 }`, then adjust `{ "change": -2, "reason": "Sale" }`. Use IDs returned by creation responses.

Owners and staff can read and change inventory. Only owners can add members. A supplied role never grants ownership. SKUs are unique within a shop. Quantities are integers from 0 to 2147483647; booleans and floats are rejected. Changes cannot oversell or overflow. Request bodies are limited to 16 KiB.

Expected errors use `{ "error": "message" }`: 400 invalid input, 401 missing/expired authentication, 403 insufficient owner permission, 404 absent or inaccessible shop/item, 409 duplicate or invalid stock adjustment, 413 oversized body, 429 login limit, 503 database unavailable. Unexpected server failures return 500. Login permits five attempts per email in 15 minutes, including successful attempts; counters persist across workers. Old global `/items` routes return 404.

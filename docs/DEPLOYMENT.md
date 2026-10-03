# Deployment runbook

## Single-host Docker

```sh
docker compose up --build -d
curl --fail http://127.0.0.1:8000/health
```

Expected response: `{"status":"ok"}`. The named volume persists `/data/stockroom.db` across container replacement. Never run `docker compose down -v` against data you want to keep. Put an HTTPS reverse proxy in front of localhost port 8000 and configure upstream request/body limits. Never expose Flask's development server.

## Hosted service

Use a single Docker service from this repository and attach persistent storage at `/data`, writable by UID 10001. Set `STOCKROOM_DB=/data/stockroom.db`; the host supplies `PORT`. Configure `/health` as the health endpoint and enable HTTPS. Keep one service instance with this SQLite architecture. Ephemeral storage is unsuitable: deployments would lose accounts, sessions and stock. Confirm storage availability, pricing and backup support with the hosting provider before provisioning. No hosted deployment is currently claimed.

Without Docker, install requirements and run:

```sh
STOCKROOM_DB=/absolute/persistent/path/stockroom.db gunicorn 'app:create_app()' --bind 0.0.0.0:8000 --workers 2 --threads 2 --timeout 30
```

## Deployment acceptance

1. Run the automated tests and check `/health` over HTTPS.
2. Register two demo accounts and create a shop with each.
3. Create stock as account A; confirm account B cannot read or adjust A's shop, including by substituting item IDs.
4. Add B as staff to A's shop; confirm inventory access succeeds and member administration returns 403.
5. Sell stock and attempt to oversell; verify 409 and unchanged quantity/history.
6. Restart/redeploy the service, log in again, and verify accounts and inventory persist.
7. Log out and verify that the old token returns 401.

Record the service URL, deployed commit SHA, date and these results before sharing it as a live backend. The test suite validates API/database behavior; it does not validate a provider's TLS, storage or deployment settings.

## Backup and restore

Use SQLite's online backup API rather than copying a database during writes:

```python
import sqlite3
with sqlite3.connect('/data/stockroom.db') as source:
    with sqlite3.connect('/backup/stockroom-backup.db') as destination:
        source.backup(destination)
```

Run from an environment with access to the persistent disk; store backups separately with restricted permissions and retention. Test restoration into a separate service before relying on backups. Stop the application before replacing its database during a restore. Backups contain password hashes and sessions and must be treated as sensitive.

## Operations and limitations

Monitor 5xx responses, disk space, latency and backup success. Never log Authorization headers or request bodies. SQLite lock contention returns 503; investigate sustained contention before increasing worker counts. The login limiter is per email, so an attacker can temporarily exhaust another account's attempts; add upstream abuse controls for registration and all routes. Add password recovery, verified email, member removal and a reviewed migration process before using this for real customer operations.

Official deployment reference: https://flask.palletsprojects.com/en/stable/deploying/gunicorn/

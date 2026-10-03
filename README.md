# Stockroom API

An authenticated inventory backend built with Python, Flask and SQLite. Each shop has an owner and staff membership; inventory requests check membership and scope item queries to that shop. Stock adjustments and their actor-attributed movement records commit together.

## Run locally

Requires Python 3.12 or newer.

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python app.py
```

The development API listens on http://127.0.0.1:8000. Run `python -m unittest discover -s tests -v` for the automated suite.

## What the tests demonstrate

Authentication, password and token hashing, expiry and logout, shared login attempt limits, denied cross-shop reads and writes, owner/staff permissions, validation, shop-specific SKUs, rollback on audit failure, concurrent attempts to sell the last unit, and persistence across application restarts. Tests use isolated temporary databases and exercise real SQLite transactions.

## Deployment and design

- [API contract](docs/API.md)
- [Deployment, verification and backup](docs/DEPLOYMENT.md)
- [Decisions and interview walkthrough](docs/DECISIONS.md)

The Docker image runs Gunicorn as a non-root user; Compose provides persistent database storage. This repository does **not** yet establish a verified public backend deployment. The existing [browser preview](https://kevin-nyagaka-portfolio.nyagaka.chatgpt.site/stockroom.html) is a separate demonstration and does not exercise this API.

This is a breaking change from the original unauthenticated `/items` API. Start with a fresh database; the application refuses the old unscoped schema. Back up old data before any manually reviewed migration.

## Current limits

Designed for a small, single-instance portfolio service. SQLite serializes writes; horizontal scaling needs a shared database and a revised limiter. There is no email verification, password recovery, membership removal, frontend integration or account deletion yet. Add upstream request limits before public exposure; the application limiter only covers login attempts per email. Do not put customer data into the demo until those operational requirements are addressed.

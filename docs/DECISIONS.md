# Decisions to explain in an interview

## Authentication versus authorization

Authentication identifies the user from a random bearer token. Authorization separately checks that user's membership on every shop route. Item queries use both shop ID and item ID, so knowing another item's ID is insufficient. Inaccessible shops return 404 to avoid advertising their existence. Owners manage staff; staff handle inventory. Roles come from the database, never a request field.

Passwords use Werkzeug's scrypt hashing. Session tokens have 256 bits of randomness; only SHA-256 token hashes are stored. An opaque session is simpler than a JWT here and supports immediate logout without a separate revocation list. The cost is a database lookup on each protected request. Sessions survive application restarts and expire after one hour. HTTPS is still essential because possession of a token grants access.

## Inventory integrity

A sale executes a conditional SQL UPDATE that allows only a quantity in the valid range. This avoids a read-then-write race: when two clients try to sell the last unit, exactly one succeeds. The stock update and actor-attributed movement insert share a transaction. If the movement insert fails, the quantity update rolls back. A movement history is useful evidence but is not a tamper-proof audit system; database administrators can change it.

## SQLite and Flask

Flask provides routing, JSON handling, request-scoped connections and a standard WSGI entry point. SQLite keeps this small deployment understandable and inexpensive. Each request gets its own connection, foreign keys are enabled, and the database waits up to ten seconds for locks. Multiple Gunicorn workers share the persistent file and login counters. SQLite serializes writers; a larger service should move to PostgreSQL and revisit deployment/migrations rather than horizontally duplicating local files.

## Migration and deployment

The previous database had no owner or shop boundary. Automatically assigning that inventory would invent an authorization decision. Startup rejects the legacy schema, preserving it for backup and a manually reviewed import. This version intentionally breaks the global API contract.

Gunicorn serves production requests; the container runs as a non-root user. Persistent storage matters more than a successful build: without it, deployment replacement destroys inventory. Health checks cover database access, while deployment acceptance separately checks HTTPS and restart persistence. The old browser preview does not prove that the backend runs publicly.

## Evidence and honest limits

Run `python -m unittest discover -s tests -v`. Explain the cross-shop tests, concurrent last-unit sale, injected audit-write failure and restart persistence test rather than just quoting a count. These verify meaningful failure behavior. They do not prove production scale, external security review or provider configuration.

The current scope excludes email verification, password recovery, staff removal, frontend integration and global abuse controls. The per-email login limiter is shared across workers but can be abused to lock an account temporarily. Explain these limitations and the next steps openly; do not claim production readiness or senior-level experience solely from this project.

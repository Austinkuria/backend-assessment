# Reliable Posts API

A Django REST Framework backend for a university social network where students create, read, edit and delete posts. Beyond basic CRUD, the API is built to behave consistently when clients **retry**, **double-submit**, or **race** each other, which is what happens with flaky mobile connections.

- **Stack:** Python 3.12+, Django 6.1, Django REST Framework 3.18, SQLite by default (PostgreSQL optional)
- **Auth:** DRF token authentication (session auth also works for the browsable API)

---

## Quick start

```bash
git clone <repo-url> && cd backend-assessment
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

The API runs at http://127.0.0.1:8000/api/. Open it in a browser and use **Log in** (top right) to try it through DRF's browsable API.

### Run the tests

```bash
python manage.py test
```

### Optional configuration (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `DJANGO_SECRET_KEY` | dev key | Secret key (set this in production) |
| `DJANGO_DEBUG` | `true` | Debug mode |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated hosts |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT` | unset | If `POSTGRES_DB` is set, PostgreSQL is used instead of SQLite (`pip install "psycopg[binary]"`) |
| `POSTS_IDEMPOTENCY_KEY_REQUIRED` | `true` | Require `Idempotency-Key` on post creation |
| `POSTS_IDEMPOTENCY_KEY_TTL_SECONDS` | `86400` | How long idempotency keys are remembered |

---

## API documentation

Base URL: `/api/`. All request and response bodies are JSON. Every `/api/posts/` endpoint needs an authenticated user, so send `Authorization: Token <token>`.

### Authentication

#### `POST /api/auth/register/`
```json
{ "username": "austin", "email": "austin@uni.ac.ke", "password": "s3cure-Passw0rd!" }
```
**201** returns the user plus an API token:
```json
{ "id": 1, "username": "austin", "email": "austin@uni.ac.ke", "token": "9944b09199c62bcf9418ad846dd0e4bbdfc6ee4b" }
```
**400** for an invalid or duplicate username or a weak password (Django's password validators run).

#### `POST /api/auth/token/`
```json
{ "username": "austin", "password": "s3cure-Passw0rd!" }
```
**200** returns `{ "token": "..." }`. **400** for bad credentials.

### Post representation

```json
{
  "id": 42,
  "title": "Library hours extended",
  "content": "The main library is now open until midnight during exams.",
  "author": { "id": 1, "username": "austin" },
  "created_at": "2026-10-31T19:20:11.512Z",
  "updated_at": "2026-10-31T19:20:11.512Z",
  "version": 1
}
```

| Field | Rules |
|---|---|
| `title` | required, trimmed, not blank, max 200 chars |
| `content` | required, trimmed, not blank, max 10,000 chars |
| `id`, `author`, `created_at`, `updated_at`, `version` | read-only. The server ignores them if a client sends them. `author` is always the authenticated user. |

`version` goes up by one on every change. It is also sent as the `ETag` response header (for example `ETag: "3"`), and clients can send it back in `If-Match` (see below).

### Endpoints

| Method | Path | Who | Success |
|---|---|---|---|
| `GET` | `/api/posts/` | any authenticated user | `200` paginated list, newest first |
| `POST` | `/api/posts/` | any authenticated user | `201` created post |
| `GET` | `/api/posts/{id}/` | any authenticated user | `200` post + `ETag` |
| `PUT` | `/api/posts/{id}/` | author only | `200` updated post (title and content both required) |
| `PATCH` | `/api/posts/{id}/` | author only | `200` updated post (any subset of fields) |
| `DELETE` | `/api/posts/{id}/` | author only | `204` no body |

#### `GET /api/posts/`
Query parameters: `page` (default 1), `author=<user id>` (optional filter).
```json
{ "count": 31, "next": "http://.../api/posts/?page=2", "previous": null, "results": [ { "...post..." } ] }
```

#### `POST /api/posts/`
Headers: **`Idempotency-Key: <unique string, e.g. a UUID>`** (required, max 255 chars)
```json
{ "title": "Library hours extended", "content": "Open until midnight." }
```
- **201** with the post, plus `Location` and `ETag` headers.
- If the same key is retried, you get the **same 201 and body** again, plus the header `Idempotent-Replayed: true`. No second post is created.
- **400** for validation errors or a missing or invalid `Idempotency-Key`.
- **422** if the key was already used for a *different* payload.

#### `PUT` / `PATCH /api/posts/{id}/`
Optional header: **`If-Match: "<version>"`** (accepts `"3"`, `3`, `W/"3"`, `*`).
- **200** with the updated post and its new `ETag`.
- **412 Precondition Failed** if `If-Match` is stale. The body includes the current post so the client can reconcile:
  ```json
  { "detail": "This post has been modified since you last fetched it. ...", "current": { "...post..." } }
  ```

#### `DELETE /api/posts/{id}/`
Optional header: `If-Match: "<version>"`.
- **204** on success, and also when the author **retries** a delete that already happened.
- **412** if `If-Match` is stale.

### Status codes

| Code | When |
|---|---|
| `200` / `201` / `204` | Success |
| `400` | Invalid body, missing `Idempotency-Key`, malformed `If-Match` or `author` filter |
| `401` | Missing or invalid token |
| `403` | Authenticated, but trying to change someone else's post |
| `404` | Post does not exist or has been deleted |
| `412` | `If-Match` version is stale (someone changed the post first) |
| `422` | `Idempotency-Key` reused with a different payload |

### Example session (curl)

```bash
TOKEN=$(curl -s -X POST localhost:8000/api/auth/register/ -H "Content-Type: application/json" \
  -d '{"username":"austin","password":"s3cure-Passw0rd!"}' | python -c "import sys,json;print(json.load(sys.stdin)['token'])")

# Create (safe to repeat: the same key never creates a second post)
curl -i -X POST localhost:8000/api/posts/ -H "Authorization: Token $TOKEN" \
  -H "Content-Type: application/json" -H "Idempotency-Key: 7f9c1a2e-0b1d-4c55-9a43-3c1e5e7d2f10" \
  -d '{"title":"Hello","content":"First post"}'

# Conditional update
curl -i -X PATCH localhost:8000/api/posts/1/ -H "Authorization: Token $TOKEN" \
  -H "Content-Type: application/json" -H 'If-Match: "1"' -d '{"content":"Edited"}'

# Delete (safe to repeat)
curl -i -X DELETE localhost:8000/api/posts/1/ -H "Authorization: Token $TOKEN"
```

---

## Design decisions

### Project structure

```
config/                 settings and root URLs
accounts/               registration and token endpoints
posts/
  models.py             Post (with version and soft delete), IdempotencyRecord
  serializers.py        validation and representation
  permissions.py        IsAuthorOrReadOnly
  idempotency.py        Idempotency-Key handling (generic, reusable)
  services.py           conditional update/delete (compare-and-swap) and If-Match parsing
  views.py              thin PostViewSet that wires HTTP to the services
  management/commands/  purge_idempotency_records
  tests/                CRUD, scenario and real multi-threaded concurrency tests
```

Views only handle HTTP concerns. The reliability logic lives in `idempotency.py` and `services.py`, which keeps it isolated and testable.

### How each scenario is handled

| Scenario | Mechanism | Result |
|---|---|---|
| **1. Publish clicked several times** | `Idempotency-Key` header. The client generates one key per publish action and reuses it on every click or retry. The server creates the post and stores the key with its response **in one transaction**. A unique `(user, key)` constraint backs this up. | Exactly one post. Every click gets the same `201` and body. |
| **2. Connection drops before the response; user retries later** | Same mechanism. The stored response is replayed for 24 h (configurable). | The retry receives the original `201` (marked `Idempotent-Replayed: true`). No duplicate. |
| **3. Update appears to fail and is resubmitted** | PUT/PATCH set absolute values, so they are naturally idempotent. If the post already holds the requested values, nothing is written and `200` is returned, even when the retry carries the now-stale `If-Match` from the first attempt. | A retry returns `200` with the same post. The version is not bumped twice. |
| **4. Delete confirmation never arrives** | **Soft delete** keeps a tombstone (`deleted_at`). When the author repeats the delete, the server sees it is already done and returns `204` again. | Retrying a delete is safe and returns the same answer. Deleted posts are `404` for every read or write, and `404` for other users' deletes. |
| **5. Two requests on the same post at almost the same time** | **Optimistic concurrency control.** Each write is a single conditional `UPDATE ... WHERE id=? AND version=?` run atomically by the database. Clients that send `If-Match` cannot overwrite a change they haven't seen; they get `412` plus the current post. An update racing a delete gets `404`. Two identical deletes both get `204`. | No lost updates, no half-applied state, no duplicate side effects, whether requests hit one server or many. |

### Why these choices

- **Idempotency keys over content-based duplicate detection.** Rejecting identical title and content within N seconds is a guess. It blocks legitimate reposts and still fails when retries arrive late. A client-generated key states intent exactly. This is the approach used by Stripe and the IETF `Idempotency-Key` draft. The key is **required** by default so every client gets the guarantee; set `POSTS_IDEMPOTENCY_KEY_REQUIRED=false` to make it optional.
- **The fingerprint guards against key misuse.** Each record stores a hash of method, path and validated payload. Reusing a key for a different request returns `422` instead of silently returning the wrong post.
- **Only successful creates consume a key.** A `400` is not stored, so the user can fix the input and resubmit with the same key.
- **The database enforces the guarantees, not the Python code.** Compare-and-swap updates and a unique constraint stay correct across multiple processes or servers, where in-process locks would not. On SQLite, transactions start in `IMMEDIATE` mode so concurrent writers queue instead of failing with "database is locked". On PostgreSQL, the unique constraint resolves the race and the losing request replays the winner's response (this path is tested).
- **`If-Match` is optional.** Simple clients get atomic last-write-wins. Clients that care about conflicting edits from two devices opt into `412` protection using standard HTTP semantics (`ETag` / `If-Match`).
- **No-op updates don't change `version`.** This is what makes a retried update with a stale ETag safe.
- **Permissions.** `IsAuthenticated` everywhere, since this is a members-only university community, plus an object-level `IsAuthorOrReadOnly`. A missing post is checked before ownership, so you get `404` before `403`.
- **Housekeeping.** `python manage.py purge_idempotency_records` deletes expired keys and can run daily from cron. Expired keys are also ignored when looked up.

### Trade-offs and possible extensions

- A replayed create returns the response **as originally sent** (snapshot), even if the post was edited later. This matches common idempotency semantics.
- Soft-deleted rows stay in the table. A periodic hard-delete job could remove old tombstones.
- Possible next steps: rate limiting (DRF throttling), `If-None-Match`/`304` for cheaper polling, CORS headers exposing `ETag`, and OpenAPI docs (drf-spectacular).

---

## Tests

`python manage.py test` runs **52 tests**:

- `posts/tests/test_crud.py`: create, list (pagination, ordering, author filter), retrieve, update (PUT/PATCH), delete; validation; 401/403/404 handling; token-auth flow.
- `posts/tests/test_scenarios.py`: one test class per scenario in the brief: repeated clicks, retry after a lost response, key reuse with a different payload, per-user key scope, key expiry, a simulated PostgreSQL-style race on the unique constraint, retried updates and deletes, stale `If-Match` → `412`, update racing a delete → `404`.
- `posts/tests/test_concurrency.py`: **real multi-threaded tests**. Six threads with separate DB connections fire the same request at the same instant: one post is created from six simultaneous publishes, exactly one of six conditional edits wins (the rest get `412`), and six simultaneous deletes all return `204` while the delete is applied once.
- `accounts/tests.py`: registration, password validation, token login.


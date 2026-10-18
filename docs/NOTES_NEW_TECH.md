# Notes on the New Technologies (study guide)

Each section: **what it is → why this project needs it → where it is in the code → key commands → common gotchas.**

---
## 1. JWT authentication (djangorestframework-simplejwt)
- **What:** stateless tokens. After login the server returns a short-lived **access** token (30 min) and a longer **refresh** token (7 days). The client sends `Authorization: Bearer <access>` on each request. The server verifies the signature; no session lookup.
- **Why:** works for mobile/SPA clients and scales horizontally (no shared session store).
- **Code:** `config/settings.py` (`SIMPLE_JWT`), `apps/accounts/serializers.py` (custom claims `role`, `org_id`), `LogoutView` (blacklist).
- **Gotchas:** you can't revoke an access token before it expires (keep it short); refresh rotation + blacklist handles refresh tokens; never put secrets in claims (they are only signed, not encrypted).

## 2. RBAC: Role-Based Access Control
- **What:** permissions are granted to roles, and users get roles. Here: org_admin > manager > agent > customer.
- **Code:** `apps/core/permissions.py` (`roles_allowed` factory), plus queryset scoping and service rules.
- **Remember:** RBAC alone is not enough. You also need **object-level** checks ("is this *my* ticket?"). That is what queryset scoping does.

## 3. Multi-tenancy (row-level)
- **What:** many customers (tenants) share one app and database; each row carries `organization_id`.
- **Alternatives:** schema-per-tenant (e.g. django-tenants), database-per-tenant (strongest isolation, highest cost).
- **Code:** `TenantScopedMixin`, `Ticket.organization`, tests in `tests/test_tenancy.py`.
- **Gotcha:** the #1 bug is a forgotten filter. Mitigate with a mixin, code review rules and *tests that try to cross tenants*.

## 4. OpenAPI / Swagger (drf-spectacular)
- **What:** generates an OpenAPI 3 schema from your serializers/views; Swagger UI and ReDoc render it.
- **Code:** `config/urls.py`, `@extend_schema` in `apps/tickets/views.py`.
- **Commands:** `python manage.py spectacular --file schema.yml` (export for frontend teams / client generation).
- **Gotcha:** for custom actions, tell it the request/response serializers with `@extend_schema`, or the docs show wrong shapes.

## 5. Celery + Celery Beat + Redis
- **What:** Celery runs tasks outside the request in worker processes; Beat is a scheduler that enqueues periodic tasks; Redis is the broker (message queue).
- **Why here:** sending email must not slow the API; SLA breach detection must run every minute even when nobody calls the API.
- **Code:** `config/celery.py`, `apps/tickets/tasks.py`, `CELERY_BEAT_SCHEDULE` in settings.
- **Commands:** `celery -A config worker -l info`, `celery -A config beat -l info`.
- **Concepts:** at-least-once delivery → tasks must be **idempotent** (`_mark_breached` flips a flag with a conditional UPDATE, so running twice does nothing); `autoretry_for` + `retry_backoff` for flaky email; `CELERY_TASK_ALWAYS_EAGER` runs tasks inline (dev/tests).
- **Gotcha:** never enqueue a task *inside* a DB transaction before commit; the worker may run before the data exists. Use `transaction.on_commit`.

## 6. `transaction.on_commit`
- **What:** run a callback only after the outermost DB transaction successfully commits.
- **Why:** avoids emailing/broadcasting about changes that later roll back. See `notifications.py`.
- **Testing:** in `pytest` normal DB tests never commit, so use `django_capture_on_commit_callbacks(execute=True)` (see `test_email_is_sent_only_after_commit`).

## 7. Django Channels + ASGI + Daphne (WebSockets)
- **What:** WSGI handles request/response only. **ASGI** also supports long-lived connections. Channels adds *consumers* (like views for WebSockets) and *channel layers* (pub/sub over Redis) so any server process can push to any connected client.
- **Code:** `config/asgi.py`, `consumers.py` (join group), `notifications.broadcast` (`group_send`), `middleware.py` (JWT auth).
- **Flow:** client connects → middleware authenticates → consumer checks ticket access → joins `ticket_<id>_staff|public` → service calls `group_send` → consumer `ticket_event()` forwards JSON to the browser.
- **Gotchas:** call `get_asgi_application()` before importing models in `asgi.py`; ORM calls inside async code need `database_sync_to_async`; use Redis layer (not in-memory) with more than one process.

## 8. Optimistic locking
- **What:** read a `version`, and write with `UPDATE ... WHERE id=? AND version=?`. If 0 rows updated, someone else changed it → HTTP 409.
- **Versus pessimistic:** `select_for_update()` locks rows until commit: safer for money, worse for human-speed edits.
- **Code:** `_guarded_update` in `services.py`; `F("version") + 1` makes the increment atomic in SQL.

## 9. Service layer & state machine
- **Service layer:** business logic in plain functions (`services.py`) → reusable from views, Celery, management commands and tests.
- **State machine:** the `ALLOWED_TRANSITIONS` dict is the single source of truth for legal status changes.

## 10. DRF throttling, pagination, filtering
- **Throttling:** `AnonRateThrottle`, `UserRateThrottle`, plus a scoped `auth` rate (10/min) for login/register to slow brute force.
- **django-filter:** declarative filters (`TicketFilter`) incl. custom method filters (`breached`, `unassigned`).
- **Search/Ordering:** `SearchFilter`, `OrderingFilter`. For big data replace `icontains` with FULLTEXT/OpenSearch.

## 11. Pytest + pytest-django
- **Fixtures** build orgs/users once and reuse them; `client_for(user)` uses `force_authenticate`.
- **Markers:** `@pytest.mark.django_db`, `@pytest.mark.asyncio` (WebSocket tests need `transaction=True`).
- **What good tests prove here:** tenant isolation, permission matrix, state machine, idempotent SLA job, optimistic-lock conflict.
- **Commands:** `pytest -x -q`, `pytest -k tenancy`, `pytest --cov=apps`.

## 12. Docker & Docker Compose
- **Image:** `Dockerfile` (Python slim + build deps for mysqlclient, non-root user).
- **Compose:** 5 services: `db`, `redis`, `web`, `worker`, `beat`; `healthcheck` + `depends_on: service_healthy` makes the app wait for MySQL.
- **Gotcha:** inside Compose, hosts are service names (`DB_HOST=db`, `redis://redis:6379`), not `localhost`.

## 13. GitHub Actions CI
- Pipeline: checkout → Python 3.12 → install → `manage.py check` → migrations → `pytest --cov` with a **MySQL service container** → Docker build.
- Add later: lint (ruff), security scan (`pip-audit`, `bandit`), deploy job on tags.

## 14. AWS mapping (see `DEPLOYMENT_AWS.md`)
ALB → ECS Fargate (web, worker, beat) → RDS MySQL; ElastiCache Redis; S3 for attachments; SES for email; Secrets Manager; CloudWatch; ECR for images.

## 15. Quick vocabulary
**Idempotent** (safe to repeat) · **Eventual consistency** · **At-least-once delivery** · **N+1 query** · **Compare-and-swap** ·
**Tenant isolation** · **Audit trail** · **SLA / SLO** · **Backpressure** · **Dead-letter queue**

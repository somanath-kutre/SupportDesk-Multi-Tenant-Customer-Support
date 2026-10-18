# SupportDesk: Multi-Tenant Customer Support & SLA Platform

A production-style backend (Django + DRF + MySQL) where many companies ("tenants") run their own
support desk: tickets, assignment, SLA deadlines and breach alerts, real-time updates, audit trail,
notifications and dashboards. Think of a small Zendesk/Freshdesk API.

**Stack:** Python 3.12, Django 5.2, DRF, MySQL 8, JWT (SimpleJWT) + RBAC, Swagger/OpenAPI (drf-spectacular),
Celery + Celery Beat, Redis, Django Channels (WebSockets), Pytest, Docker Compose, GitHub Actions,
plus a dependency-free **frontend SPA** (HTML/CSS/JS) served by Django at `/`.

> **Honest status note:** this code was generated and syntax-checked, but the author's sandbox had no
> internet, so the test-suite has **not** been executed there. Run `pytest` first (Step 6 below). If a test fails,
> read the traceback; fixes are normally one-liners, and debugging them is excellent interview practice.

---

## 1. Features

| Area | What is implemented |
|---|---|
| Auth | JWT login/refresh/logout (refresh-token blacklist), role + org claims in the token, throttled auth endpoints |
| RBAC | Roles: `org_admin`, `manager`, `agent`, `customer` (+ platform `superuser`). 3 layers: endpoint permission, queryset scoping, service-level rules |
| Multi-tenancy | Row-level isolation via `organization` FK; every query is tenant-scoped; cross-tenant access returns 404 |
| Tickets | Create, list, filter, search, sort, paginate, assign/claim, status state machine, comments, internal notes |
| SLA engine | Per-org, per-priority policies; deadlines computed on creation; Celery Beat flags breaches; idempotent |
| Real time | WebSocket per ticket (`ws/tickets/<id>/?token=JWT`); staff and customers get different channels so internal notes never leak |
| Notifications | In-app notifications + emails sent via Celery **after** the DB transaction commits |
| Audit trail | Append-only `TicketEvent` timeline (staff only) |
| Files | Validated uploads (type + size), private storage, authorised download endpoint |
| Concurrency | Optimistic locking with a `version` field (HTTP 409 on conflict) |
| Reports | Cached summary dashboard (status/priority counts, SLA breaches, avg first response, agent workload) |
| API docs | Swagger UI `/api/docs/`, ReDoc `/api/redoc/`, schema `/api/schema/` |
| Frontend | Single-page app: login/sign-up, ticket list + filters, ticket detail with live updates, dashboard, team & SLA admin, notifications (see `docs/FRONTEND.md`) |
| Ops | Health check `/health/`, structured logging, Docker, CI pipeline, consistent JSON error envelope |

## 2. Project layout

```
supportdesk/
├── config/               settings, urls, asgi (HTTP + WebSocket), celery app
├── apps/
│   ├── frontend/         single-page web UI (template + static JS/CSS), served at /
│   ├── core/             shared: base model, permissions, pagination, error handler, tenant mixin
│   ├── accounts/         Organization, User(role), auth endpoints, user management, seed_demo command
│   └── tickets/          models, services (business logic), sla, tasks, notifications,
│                         serializers, filters, views, reports, consumers (WebSocket), middleware
├── tests/                55 tests: auth, tenancy, tickets, SLA, WebSocket
├── docs/                 architecture, new-tech notes, interview Q&A, resume text, industry use, AWS deploy
├── Dockerfile, docker-compose.yml, .github/workflows/ci.yml
└── requirements.txt, requirements-dev.txt, pytest.ini, .env.example
```

## 3. How to run on your local system

You need: **Python 3.11+** (3.12 recommended) and **Git**. Pick ONE option.

### Option A: Quickest start (SQLite, no Redis, no Docker), about 3 minutes

```bash
cd supportdesk
python -m venv .venv
# Windows:  .venv\Scripts\activate        Linux/Mac:  source .venv/bin/activate
pip install -r requirements-dev.txt
```
> If `mysqlclient` fails to build on Windows, delete that single line from `requirements.txt` for this option
> (SQLite doesn't need it), or use Option C (Docker).

Do **not** create a `.env` yet (defaults = SQLite, in-memory cache/channels, Celery runs tasks inline).

```bash
python manage.py makemigrations accounts tickets   # creates the migration files (first time only)
python manage.py migrate
python manage.py seed_demo                          # demo org + users + tickets
python manage.py runserver
```
Open **http://127.0.0.1:8000/** for the web app (sign in as `customer1`, `agent1`, `manager` or `admin`, password `Pass@12345`),
or **http://127.0.0.1:8000/api/docs/** for Swagger UI. If you set up before the frontend existed, run `pip install -r requirements-dev.txt` again (it added WhiteNoise).

### Option B: Local MySQL (the "real" setup)

1. Install MySQL 8 and create the database and user:
```sql
CREATE DATABASE supportdesk CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'supportdesk'@'%' IDENTIFIED BY 'supportdesk';
GRANT ALL PRIVILEGES ON *.* TO 'supportdesk'@'%';   -- *.* lets pytest create its test_ database
FLUSH PRIVILEGES;
```
2. `cp .env.example .env` and set `DB_HOST=127.0.0.1` (keep `DB_ENGINE=mysql`).
3. Run the same 4 commands as Option A (`makemigrations`, `migrate`, `seed_demo`, `runserver`).

Windows: `mysqlclient` normally installs from a wheel on Python 3.12. If not, install "Microsoft C++ Build Tools" or use Docker.

### Option C: Full stack with Docker (MySQL + Redis + API + Celery worker + Celery Beat)

```bash
docker compose up --build
# in a second terminal, once "web" is running:
docker compose exec web python manage.py seed_demo
```
API: http://localhost:8000/api/docs/  (MySQL is exposed on host port 3307).
Watch `docker compose logs -f worker beat` to see SLA checks run every minute and emails being "sent" (console backend).

### Option D: Run Redis + Celery without Docker for the app

```bash
docker run -d -p 6379:6379 redis:7-alpine     # just Redis in Docker, or install Redis natively
# .env:  REDIS_URL=redis://127.0.0.1:6379/0
python manage.py runserver                     # terminal 1
celery -A config worker -l info                # terminal 2  (use "-P solo" on Windows)
celery -A config beat -l info                  # terminal 3  (the SLA scheduler)
```

### Step 6: Run the tests
```bash
pytest                      # all tests
pytest tests/test_tenancy.py -v
pytest --cov=apps --cov-report=term-missing
```
Tests use SQLite by default; with `DB_ENGINE=mysql` in `.env` they run against MySQL.

## 4. Try the API (5-minute walkthrough)

Demo users (after `seed_demo`), all with password `Pass@12345`:
`admin` (org_admin), `manager`, `agent1`, `agent2`, `customer1`, `customer2`. Org slug: `acme`.

```bash
# 1) Login as customer -> get tokens
curl -s -X POST localhost:8000/api/v1/auth/login/ -H "Content-Type: application/json" \
  -d '{"username":"customer1","password":"Pass@12345"}'
# copy the "access" value:  export C="<access>"

# 2) Create a ticket (note the SLA deadlines in the response)
curl -s -X POST localhost:8000/api/v1/tickets/ -H "Authorization: Bearer $C" -H "Content-Type: application/json" \
  -d '{"subject":"Cannot export report","description":"Export button does nothing since yesterday","priority":"high"}'

# 3) Login as agent1 (export A=...), list unassigned tickets, claim one, reply, resolve
curl -s "localhost:8000/api/v1/tickets/?unassigned=true&ordering=created_at" -H "Authorization: Bearer $A"
curl -s -X POST localhost:8000/api/v1/tickets/1/assign/  -H "Authorization: Bearer $A" -H "Content-Type: application/json" -d '{"assignee_id": 3}'
curl -s -X POST localhost:8000/api/v1/tickets/1/comments/ -H "Authorization: Bearer $A" -H "Content-Type: application/json" -d '{"body":"Fixing now","is_internal":false}'
curl -s -X POST localhost:8000/api/v1/tickets/1/status/  -H "Authorization: Bearer $A" -H "Content-Type: application/json" -d '{"status":"resolved"}'

# 4) Manager dashboard (login as manager first)
curl -s localhost:8000/api/v1/reports/summary/ -H "Authorization: Bearer $M"
```
Tip: easiest is Swagger UI: click **Authorize**, paste `Bearer <access>`... (paste only the token; the UI adds "Bearer").

### Real-time demo (WebSocket)
Open a browser console (any page) and run, using an access token and a ticket id:
```js
const ws = new WebSocket("ws://127.0.0.1:8000/ws/tickets/1/?token=PASTE_ACCESS_TOKEN");
ws.onmessage = (e) => console.log(JSON.parse(e.data));
```
Now post a comment or change the status on ticket 1 from Swagger as another user. The event appears instantly.
A customer will **not** receive internal notes; an agent will.

### Onboard a brand-new tenant
`POST /api/v1/auth/register-organization/` with `organization_name, username, email, password`:
creates the organization, its first admin and the 4 default SLA policies.

## 5. API reference (all under `/api/v1/`)

| Method & path | Who | Purpose |
|---|---|---|
| POST `auth/register-organization/` | public | New tenant + first admin |
| POST `auth/register/` | public | Customer self-signup (`org_slug`) |
| POST `auth/login/`, `auth/refresh/`, `auth/logout/` | public / any | JWT lifecycle |
| GET `auth/me/` | any | Current user |
| GET/POST `users/`, GET/PATCH `users/{id}/` | manager+ read, org_admin write | User management |
| GET/POST `tickets/` | any (scoped) | List (filter/search/sort/paginate) / create |
| GET `tickets/{id}/` | any (scoped) | Detail |
| POST `tickets/{id}/assign/` | staff | Assign/claim/unassign |
| POST `tickets/{id}/status/` | any (rules apply) | State-machine transition |
| GET/POST `tickets/{id}/comments/` | any (scoped) | Comments + internal notes |
| GET/POST `tickets/{id}/attachments/`, GET `.../attachments/{aid}/download/` | any (scoped) | Private files |
| GET `tickets/{id}/timeline/` | staff | Audit trail |
| GET `notifications/`, POST `notifications/{id}/read/`, POST `notifications/read-all/` | any | In-app notifications |
| GET/PATCH `sla-policies/` | staff read, org_admin write | SLA targets |
| GET `reports/summary/` | manager+ | Dashboard numbers |

Ticket list filters: `status, priority, assignee, requester, unassigned, assigned_to_me, breached,
created_after, created_before`, plus `?search=`, `?ordering=` and `?page=&page_size=`.

Error format (always): `{"error": {"code": "...", "message": "...", "details": ...}}`

## 6. Troubleshooting

| Problem | Fix |
|---|---|
| `ValueError: Dependency on app with no migrations: accounts` | You skipped `python manage.py makemigrations accounts tickets` |
| `mysqlclient` install error | Install build tools, use Docker, or use Option A without it |
| `Access denied` / unknown database (MySQL) | Create the DB and user from Option B; check `.env` |
| Tests can't create `test_supportdesk` DB (MySQL) | Grant the MySQL user global privileges (see Option B) |
| Emails not arriving | Default backend prints emails in the terminal running Django/worker |
| WebSocket closes with 4401 / 4403 | 4401 = missing/invalid token, 4403 = not your ticket |
| Celery tasks don't run | Set `REDIS_URL`, and start `worker` and `beat` (Option D) |

## 7. Next steps (extensions that make great interview stories)

Email-to-ticket ingestion, SLA pause while "waiting for customer", MySQL FULLTEXT or OpenSearch for search,
django-storages + S3 presigned URLs, AI reply suggestions (FastAPI + vector DB), per-tenant rate limits,
OpenTelemetry/Sentry, committing migrations and a release pipeline to AWS (see `docs/DEPLOYMENT_AWS.md`).

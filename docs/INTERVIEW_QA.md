# Interview Questions & Answers: SupportDesk

Answer in your own words and always point to **where it is in your code**. Interviewers trust specifics.

---
## A. Project overview
**1. Explain your project in 60 seconds.**
SupportDesk is a multi-tenant helpdesk backend. Companies register as organizations; customers raise tickets; agents and managers handle them. It enforces SLA deadlines per priority, flags breaches with Celery Beat, pushes live updates through Django Channels, keeps an audit trail, and exposes secured, documented REST APIs. It runs on MySQL with Redis, Docker, and a GitHub Actions pipeline.

**2. Why these technologies?**
DRF for the API layer; MySQL as the relational source of truth; Celery/Redis for work that must not block requests (emails, SLA scanning); Channels for real-time; JWT for stateless auth; Pytest for fast, expressive tests. I deliberately did *not* add microservices; one deployable unit is simpler until scale demands splitting.

**3. What was the hardest part?**
Keeping tenant isolation airtight while supporting several roles, real-time channels and background jobs, since each of those is a new place where data could leak. I solved it with a tenant-scoping mixin, 404-for-other-tenants, separate staff/public WebSocket groups, and tests that deliberately try to cross tenants.

## B. Authentication & authorization
**4. How does JWT auth work in your project?**
`/auth/login/` validates credentials and returns an access token (30 min) and a refresh token (7 days). Clients send `Authorization: Bearer`. SimpleJWT verifies the signature and expiry. I add `role` and `org_id` claims. Logout blacklists the refresh token; refresh tokens rotate.

**5. JWT vs sessions?**
Sessions are server-side state (revocable, CSRF concerns, need shared store when scaled). JWTs are stateless and good for APIs/mobile, but can't be revoked before expiry, so keep them short and rotate refresh tokens.

**6. How did you implement RBAC?**
Three layers: permission classes by role for the endpoint; queryset scoping for *which rows*; service rules for *what you may do to this row* (e.g., agents can only claim unassigned tickets for themselves). Relying only on the first layer is a common bug.

**7. Why return 404 instead of 403 for another tenant's ticket?**
403 confirms the ID exists. 404 leaks nothing (prevents enumeration).

**8. How do you stop brute-force login?**
Scoped throttle `auth` (10/min) on login/register, strong password validators, and (next step) account lockout/captcha.

**9. How do WebSockets authenticate?**
Browsers can't set headers on WebSocket handshakes, so the JWT goes in the query string; my `JWTAuthMiddleware` validates it and sets `scope["user"]`. The consumer then checks tenant/ticket access and closes with 4401/4403 otherwise. Trade-off: tokens can show up in logs, so keep them short-lived or exchange for a one-time ticket.

## C. Multi-tenancy
**10. What multi-tenancy strategies exist?**
Shared DB + tenant column (mine), schema-per-tenant, database-per-tenant. Isolation and cost both increase in that order; operational complexity too.

**11. How do you guarantee no cross-tenant leaks?**
Central `TenantScopedMixin`, every service re-validates org membership (e.g. assignee must be in the ticket's org), DB constraints scoped by org, and a dedicated test module that attempts cross-tenant reads/writes.

**12. Downsides of your approach?**
A forgotten filter leaks data; noisy-neighbour risk; per-tenant backup/restore is harder. Mitigations: mixin, tests, per-tenant rate limits, and moving big tenants to dedicated DBs.

## D. Database & performance
**13. Which indexes did you add and why?**
Composite `(organization, status)`, `(organization, assignee)`, `(organization, created_at)` for list/filter screens, and `(breached_flag, due_at)` for the SLA scanner so it does range scans instead of full scans. Column order matters: equality columns first.

**14. What is the N+1 problem? Where did you avoid it?**
Looping over rows and issuing one query per row for related data. Ticket lists use `select_related("requester","assignee")`; comments use `select_related("author")`.

**15. `select_related` vs `prefetch_related`?**
`select_related` does a SQL JOIN (FK/OneToOne, single query). `prefetch_related` does a second query and joins in Python (many-to-many / reverse FK).

**16. How does pagination work and why does it matter?**
`PageNumberPagination` with max page size 100 → bounded memory and response time. For very deep pages use cursor pagination (offset gets slow).

**17. How would you scale the DB?**
Indexes → query tuning → read replica for reports → cache → partition large append-only tables (`ticket_event`) → archive closed tickets → shard by tenant if needed.

**18. Why `DecimalField`/`BigAutoField`/`utf8mb4`?** (follow-ups often asked)
BigAutoField avoids ID exhaustion; utf8mb4 supports full Unicode including emoji; Decimal is for money (not used here, but know it).

## E. Concurrency & transactions
**19. Two agents update the same ticket. What happens?**
Each update is `UPDATE ... WHERE id=? AND version=?` with `version = version + 1`. The second one affects 0 rows, so I raise 409 Conflict and the client reloads. That's optimistic locking.

**20. Optimistic vs pessimistic locking?**
Optimistic assumes conflicts are rare, takes no locks, detects at write time. Pessimistic (`select_for_update`) locks rows until commit; better for high-contention critical sections like balances.

**21. Why `transaction.on_commit` for emails/WebSocket events?**
So we never notify about something that later rolls back, and the Celery worker can't run before the row is visible.

**22. What are the limitations of on_commit?**
If the process crashes after commit but before enqueue, the side effect is lost. A transactional **outbox** table processed by a worker makes it durable.

**23. Explain transaction isolation levels. Which does MySQL use by default?**
READ UNCOMMITTED, READ COMMITTED, REPEATABLE READ, SERIALIZABLE; InnoDB defaults to REPEATABLE READ. Higher levels prevent more anomalies (dirty/non-repeatable/phantom reads) at a performance cost.

## F. Celery, Redis, async
**24. Why Celery here?**
Emails and SLA scans are slow/periodic and must not block requests. Celery workers run them; Beat schedules the periodic ones.

**25. What does "idempotent task" mean? Example?**
Running it twice has the same effect as once. `_mark_breached` updates `WHERE breached=False`, so a duplicate run changes 0 rows and sends no second alert.

**26. What if a task fails?**
`autoretry_for=(Exception,)` with exponential backoff and max 3 retries; failures are logged; next step is a dead-letter queue and alerting.

**27. What happens if the Beat process dies?**
SLA checks stop. Run one Beat instance (it's a singleton) with a supervisor/ECS restart policy; checks resume and catch up because the query is "everything overdue", not "overdue in the last minute".

**28. What is the Redis role in your system?**
Celery broker, Django cache (dashboards), and Channels layer for WebSocket fan-out between processes.

**29. WSGI vs ASGI?**
WSGI: synchronous request/response only. ASGI: async-capable, supports WebSockets and long-lived connections. Daphne is the ASGI server in the project.

**30. How do you broadcast an event to browsers?**
Service → `transaction.on_commit` → `group_send` to `ticket_<id>_staff` / `_public` → each consumer's `ticket_event` handler → `send_json`.

## G. API design & DRF
**31. Why a service layer instead of fat views or signals?**
Explicit, testable, reusable (views, tasks, commands). Signals hide control flow and make ordering/debugging hard.

**32. How are errors handled?**
A custom exception handler wraps every error as `{error:{code,message,details}}`; domain exceptions (`ConflictError`, `InvalidTransition`) map to 409/400; unknown exceptions are logged with traceback and returned as a clean 500.

**33. How do you document and version the API?**
drf-spectacular generates OpenAPI; `/api/docs/` serves Swagger. URLs are prefixed `/api/v1/` so breaking changes can ship as `/v2/`.

**34. How do you validate file uploads?**
Extension allow-list, size cap, UUID file names, private storage, and downloads only through an authorised view. Next: content sniffing (python-magic) and virus scanning (ClamAV).

**35. Implement filtering/search/sorting?**
`django-filter` FilterSet with custom methods, `SearchFilter`, `OrderingFilter` (explicit `ordering_fields` whitelist so clients can't sort by arbitrary columns).

**36. PUT vs PATCH? Idempotency of HTTP methods?**
PUT replaces the full resource; PATCH partially updates. GET/PUT/DELETE are idempotent; POST is not (use idempotency keys for payments-like POSTs).

## H. Testing, CI/CD, deployment
**37. What do your tests cover?**
54 tests: auth/JWT lifecycle, RBAC matrix, tenant isolation, state machine, optimistic locking, SLA scanner idempotency, attachments, notifications/email-after-commit, WebSocket access and internal-note secrecy.

**38. Unit vs integration tests?**
Unit: a service function in isolation. Integration: HTTP through the full stack. Mine are mostly API-level integration tests with a few service-level ones.

**39. How do you test Celery and on_commit?**
Eager mode in test settings; `django_capture_on_commit_callbacks(execute=True)` to run commit hooks inside a test transaction.

**40. Describe your CI pipeline.**
On push/PR: install, `manage.py check`, build migrations, run pytest with coverage against a real MySQL service container, then build the Docker image. Deploy job (next step) pushes to ECR and updates ECS.

**41. How would you deploy on AWS?**
Docker image in ECR → ECS Fargate services (web/worker/beat) behind an ALB; RDS MySQL (Multi-AZ); ElastiCache Redis; S3 for attachments; SES for email; Secrets Manager for config; CloudWatch for logs/alarms.

**42. How do you manage secrets and config?**
12-factor: everything from environment variables; production refuses to start with the default `SECRET_KEY`; secrets come from AWS Secrets Manager, never from git.

**43. Zero-downtime deployment and migrations?**
Rolling deploy behind ALB with health checks (`/health/`); migrations run as a one-off task *before* the new version; use expand/contract (add nullable column → deploy → backfill → enforce) so old and new code both work.

## I. Design-thinking questions
**44. How would you handle 1 million tickets per tenant?**
Archive/partition old data, OpenSearch for search, cursor pagination, pre-aggregated reports, read replicas, and caching hot lists.

**45. How would you add email-to-ticket?**
An inbound email webhook (SES → SNS/Lambda → API) creates tickets/comments via the same services; reply-to headers carry the ticket ID; dedupe on Message-ID.

**46. How would you add AI reply suggestions?**
A separate FastAPI service: embed knowledge-base articles into a vector DB, retrieve top-k for a ticket, call an LLM, return suggestions. Django calls it asynchronously via Celery with timeouts, caching and a kill-switch; agents always approve before sending.

**47. What would you improve next?**
SLA pause when waiting on customer, business-hours calendars, outbox table, per-tenant rate limits, OpenTelemetry tracing, S3 presigned uploads, committed migrations plus blue/green deploys.

**48. Tell me about a bug you hit.** (prepare your own!)
Good candidates from this build: forgetting `on_commit` so emails fired before commit; stale object after update needing `refresh_from_db`; WebSocket auth + `database_sync_to_async`; MySQL test DB privileges.

## I2. Frontend questions
**49. Why a vanilla-JS SPA instead of React?**
Zero build tooling and same-origin deployment (no CORS), so the focus stays on the backend contract. The architecture (API client with refresh, router, role-aware views, WebSocket hook) ports directly to React; I'd move when the UI needs component reuse and state management at scale.

**50. How does the frontend handle expired tokens?**
The API wrapper catches 401, calls `/auth/refresh/` once (parallel calls share one refresh promise), retries the request, and logs out if refresh fails. Logout also blacklists the refresh token server-side.

**51. Is hiding buttons by role a security measure?**
No, it's UX only. The server enforces permissions on every request; a user who calls the API directly still gets 403/404.

**52. How do you prevent XSS in the UI?**
All server data is escaped before being inserted as HTML; no `eval`, no inline event attributes with data. Next steps: a CSP header and HttpOnly-cookie auth.

**53. localStorage vs HttpOnly cookies for tokens?**
localStorage is simple but readable by any XSS; HttpOnly cookies are not readable by JS but need CSRF protection and CORS care. Choose based on threat model.

**54. How does the UI avoid overwriting someone else's change?**
It sends the ticket `version` with each action; on 409 it shows a message and reloads the latest data.

## J. Rapid-fire Python/Django basics often mixed in
- `@property` vs method; `*args/**kwargs`; generators vs lists; decorators; context managers.
- Django request lifecycle; middleware order; ORM lazy evaluation; `F()` and `Q()`; `bulk_create` vs `save`; signals vs services; `AbstractUser` vs custom `User`; migrations (`makemigrations` vs `migrate`).
- DRF: serializer validation order (`validate_<field>` → `validate`), `ModelViewSet` vs `GenericViewSet`+mixins, permissions vs throttles vs filters.

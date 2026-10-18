# Resume, Naukri & LinkedIn Text (SupportDesk)

**Rule:** only claim what you built and can explain. Replace bracketed numbers with your real measurements after you run the project.

---
## 1. Resume: project entry

**SupportDesk: Multi-Tenant Customer Support & SLA Management Platform** | Python, Django, DRF, MySQL, Redis, Celery, Channels, Docker | GitHub: [link]

- Designed and built a multi-tenant helpdesk backend (Django, DRF, MySQL) with JWT authentication and 4-role RBAC; enforced strict tenant isolation using scoped querysets and cross-tenant test cases.
- Implemented an SLA engine with Celery Beat that computes per-priority deadlines and detects first-response/resolution breaches idempotently, triggering manager alerts via in-app and email notifications.
- Built real-time ticket updates using Django Channels (WebSockets, Redis channel layer) with JWT-authenticated connections and separate staff/customer channels so internal notes never leak.
- Applied optimistic locking (version-based compare-and-swap) and a ticket state machine to prevent lost updates and illegal status transitions; returned consistent 409/400 error contracts.
- Optimised query performance with composite indexes, `select_related`, pagination, filtering/search and Redis-cached dashboards.
- Built a role-aware single-page frontend (vanilla JS) with silent JWT refresh, live WebSocket updates, optimistic-lock conflict handling and an analytics dashboard, served from the same Django deployment.
- Wrote 50+ Pytest tests (RBAC matrix, tenancy, SLA jobs, WebSockets); containerised with Docker Compose (MySQL, Redis, API, worker, beat) and set up GitHub Actions CI running tests against MySQL.
- Documented APIs with OpenAPI/Swagger (drf-spectacular); deployment design for AWS (ECS Fargate, RDS, ElastiCache, S3, SES).

**Shorter version (4 bullets)** for a tight one-page resume: use bullets 1, 2, 3 and 7.

## 2. Naukri "Project" section (keep within ~1,000 characters)

**Title:** SupportDesk – Multi-Tenant Support & SLA Platform

**Description:**
Backend platform where multiple companies run their own customer-support desk. Features: JWT auth with role-based access (with a web UI for every role) (Admin, Manager, Agent, Customer), tenant data isolation, ticket lifecycle with a validated state machine, per-priority SLA deadlines with automatic breach detection (Celery Beat), real-time updates (Django Channels/WebSockets), email and in-app notifications, audit trail, secure file uploads, optimistic locking for concurrent edits, cached analytics dashboard and Swagger API docs. Tested with 50+ Pytest cases; containerised with Docker Compose; CI with GitHub Actions on MySQL.

**Tools used:** Python, Django, Django REST Framework, MySQL, Redis, Celery, Django Channels, JWT, Docker, GitHub Actions, Pytest, Swagger/OpenAPI, Git

**Role:** Backend Developer (individual project)  **Duration:** [e.g. Oct 2026 – Nov 2026]  **Project URL:** [GitHub link]

## 3. Naukri key skills to add / headline

Python · Django · Django REST Framework · MySQL · REST API · JWT · Celery · Redis · WebSockets · Docker · CI/CD · GitHub Actions · Pytest · System Design · Multi-tenant SaaS · Swagger/OpenAPI · SQL Optimisation

**Headline idea:** `Python Backend Developer | Django, DRF, MySQL | Celery, Redis, Docker | Multi-tenant SaaS APIs`

## 4. GitHub repository "About" + README opener
*Multi-tenant customer support & SLA platform built with Django REST Framework, MySQL, Celery, Redis and Django Channels. JWT + RBAC, real-time updates, automated SLA breach detection, Docker, CI.*
Topics: `django` `drf` `mysql` `celery` `redis` `websockets` `jwt` `docker` `github-actions` `multi-tenant` `saas`

## 5. LinkedIn post (draft)
I just finished building **SupportDesk**, a multi-tenant support & SLA platform, to level up my backend skills (Django, DRF, MySQL, Celery, Channels). The most interesting problems: keeping tenant data isolated across REST *and* WebSockets, making SLA breach detection idempotent, and preventing lost updates with optimistic locking. 50+ tests, Dockerised, CI on GitHub Actions. Code + architecture notes: [link]. Feedback welcome! #Python #Django #BackendDevelopment

## 6. Interview "tell me about this project" (90 seconds)
1. **Problem:** companies lose customers when tickets are slow; they need SLA tracking.
2. **What I built:** multi-tenant API: roles, tickets, SLA engine, real-time, notifications, dashboards.
3. **Hard parts:** tenant isolation, idempotent background jobs, concurrency, auth over WebSockets.
4. **Quality:** 50+ tests, CI with MySQL, Dockerised, documented API.
5. **Next:** email-to-ticket, outbox pattern, AI reply suggestions via FastAPI + vector DB.

## 7. Before you publish
- Run it, deploy it (even a small AWS/Render instance), put the **live URL + Swagger link** in the README.
- Replace "50+" with your actual passing test count and add a coverage badge.
- Commit migrations, add screenshots/GIF of Swagger and the WebSocket demo.

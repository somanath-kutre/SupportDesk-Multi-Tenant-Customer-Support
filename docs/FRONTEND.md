# SupportDesk Frontend (single-page app)

A dependency-free SPA (plain HTML, CSS and JavaScript, **no Node, no build step**) served by Django itself.
Open **http://127.0.0.1:8000/** after `python manage.py runserver`.

Why this choice: same origin as the API (no CORS setup), nothing extra to install, and every line maps 1:1 to an API
call you can explain in an interview. A React/Vue version is a natural next step (see the end of this file).

## Files
```
apps/frontend/
├── templates/frontend/index.html     page shell (loads CSS + JS via {% static %})
└── static/frontend/
    ├── app.css                       responsive layout, light/dark theme (prefers-color-scheme)
    └── app.js                        the whole app (~500 lines): API client, router, pages, WebSocket
```
`config/urls.py` serves the template at `/`. In production WhiteNoise serves the static files (`collectstatic` runs in the Dockerfile).

## Screens and who sees them
| Route | Screen | Roles |
|---|---|---|
| `#/login` | Sign in, customer sign-up (org slug), create new organization | public |
| `#/tickets` | Ticket list: search, status/priority filters, scope (unassigned / mine / SLA-breached), sorting, pagination, "New ticket" | all (customers see only their own) |
| `#/tickets/<id>` | Detail: conversation, internal notes, SLA status, status buttons, assign / claim, attachments, audit timeline, **live updates** | all (timeline and internal notes: staff) |
| `#/dashboard` | Totals, SLA breaches, avg first response, status/priority bars, agent workload | manager, org admin |
| `#/team` | Users (add, change role, deactivate) and SLA policy editor | manager (read), org admin (edit) |
| `#/notifications` | In-app notifications, mark read / mark all, click to open ticket; badge in the top bar | all |

## How it works (explain this in interviews)
1. **JWT handling:** tokens live in `localStorage`. The access token's payload is decoded client-side to read `role`, `username`
   and `user_id` (the claims added by the backend) to decide which menu items and buttons to show.
   *This is only for UX; the server enforces every permission.*
2. **Silent refresh:** `api()` attaches `Authorization: Bearer`; on a 401 it calls `/auth/refresh/` once (shared in-flight promise
   so parallel requests don't refresh twice), retries the request, and logs out if refresh fails. Logout also blacklists the refresh token.
3. **Hash router:** `#/tickets/12` etc. A `route()` function picks the page; guards redirect unauthenticated users to login and
   non-managers away from manager pages.
4. **Optimistic locking in the UI:** every assign/status action sends the ticket's `version`. On HTTP 409 the UI shows
   "Someone else changed this ticket" and reloads the fresh data.
5. **Real time:** the ticket page opens `ws://host/ws/tickets/<id>/?token=<access>`. Any event (comment, status, assignment, SLA breach)
   triggers a refresh of that ticket. The green "● live" label shows the socket state. Customers are on the *public* channel, so
   they never receive internal notes.
6. **Notifications badge:** polled every 30 s (a user-level WebSocket would be the next improvement).
7. **Private downloads:** attachments are fetched with the auth header, converted to a Blob and saved; there are no public file URLs.
8. **XSS safety:** every server-provided string is passed through `esc()` before going into `innerHTML`.
9. **Role-aware UI:** buttons mirror the backend rules (staff transitions vs. the three customer transitions), but the backend is authoritative.

## 5-minute demo script
1. `python manage.py seed_demo`, then open `/`.
2. Window A (normal): sign in as `customer1`, open an existing ticket. Window B (private/incognito): sign in as `agent1`, open the same ticket.
3. In B, send an **internal note**: A shows nothing. Send a normal reply: A shows it instantly ("● live").
4. In B click **Mark resolved**; A's status updates live and the customer now sees **Close** / **Reopen**.
5. Sign in as `manager` → **Dashboard** and **Team & SLA** (edit an SLA target, add a user).
6. Open the ticket in two browsers as two different staff and assign it in both to see the **409 conflict** toast.

## Security notes
- Tokens in `localStorage` are readable by any XSS bug; that is why output is escaped. For higher security use `HttpOnly` cookies + CSRF protection.
- Add a Content-Security-Policy header in production.

## Next step: a React version
Keep the same API and rebuild with Vite + React + TanStack Query + React Router: `AuthContext` (tokens/role), an `apiClient`
with the same refresh logic, one component per screen above, and a `useTicketSocket(id)` hook. The backend needs
`django-cors-headers` if the React app runs on a different origin (e.g. `localhost:5173`).

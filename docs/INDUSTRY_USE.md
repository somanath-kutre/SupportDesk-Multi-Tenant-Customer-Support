# Real Industry Use: Where This Kind of System Is Used

## 1. The business problem
Every company that serves customers receives requests: "my payment failed", "server is down", "how do I reset my password".
Handled over email/WhatsApp, requests get lost, nobody owns them, and nobody knows whether the promised response time was met.
A **ticketing / service-desk platform** gives every request an owner, a status, a deadline (SLA) and a history.

## 2. Real products in this category
Zendesk, Freshdesk, Jira Service Management, ServiceNow, Intercom, Zoho Desk, HappyFox, Help Scout. Many Indian IT and BPO companies
run internal service desks of the same shape (Infosys, TCS, Wipro, HCL support teams use ServiceNow/Jira SM-style tools).

## 3. Where companies use it
| Industry | Typical use |
|---|---|
| IT services & MNC support | L1/L2/L3 incident and request management with strict SLAs per client contract |
| SaaS companies | Customer support, bug reports, feature requests |
| Banking & fintech | Transaction disputes, KYC issues, with compliance audit trails |
| E-commerce / logistics | Order, refund and delivery complaints at high volume |
| Telecom | Network faults, billing complaints, prioritised by customer tier |
| Healthcare / education | Internal helpdesk, admission/patient-service requests |
| HR & facilities | Internal employee requests (IT access, leave queries, repairs) |

## 4. Why each feature of the project exists in the real world
- **Multi-tenancy:** a SaaS vendor serves hundreds of companies from one deployment; data must never mix.
- **RBAC:** customers, agents, supervisors and admins see and do different things; auditors need proof.
- **SLA engine:** contracts promise "urgent issues answered in 30 minutes"; breaches cost money (penalties) and trust.
- **Real-time updates:** agents handling many chats need live changes without refreshing.
- **Audit trail:** needed for compliance, dispute resolution and performance reviews.
- **Notifications:** managers must learn about breaches *before* the customer complains.
- **Optimistic locking:** two agents editing one ticket must not silently overwrite each other.
- **Reports:** managers staff the desk using first-response time, backlog and agent workload.
- **Attachments:** screenshots and logs speed up diagnosis; they must be access-controlled (they may contain sensitive data).

## 5. Business value (how companies justify it)
Faster response and resolution times, fewer lost requests, measurable SLA compliance, better staffing decisions,
searchable history of known issues, and happier customers → lower churn.

## 6. How production systems go beyond this project (be honest in interviews)
Omnichannel intake (email, chat, WhatsApp, voice), business-hours SLA calendars and SLA pause states, automation rules and
macros, ML-based routing/priority prediction, knowledge-base deflection and LLM reply suggestions, full-text search (OpenSearch),
SSO/SAML, data residency and retention policies, event-streaming (Kafka) for analytics, multi-region deployment and 24x7 SRE.

## 7. How to talk about it
"I built a scaled-down version of the core of Zendesk/ServiceNow: the data model, permissions, SLA logic, real-time and
background processing. Production systems add omnichannel intake, search and ML on top of the same foundation."

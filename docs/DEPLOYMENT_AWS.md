# Production Deployment on AWS (Phase 7 guide)

## Target architecture
```
Route 53 → CloudFront (optional) → ALB (HTTPS, ACM cert)
                                     └─► ECS Fargate service "web"    (daphne, 2+ tasks, health check /health/)
                                         ECS Fargate service "worker" (celery worker)
                                         ECS Fargate service "beat"   (celery beat, desired count = 1)
RDS MySQL 8 (Multi-AZ, private subnets)   ElastiCache Redis (private)   S3 (attachments)   SES (email)
Secrets Manager (SECRET_KEY, DB password)   CloudWatch Logs + alarms   ECR (images)
```
Cheaper learning path: one EC2 (t3.small) with Docker Compose + RDS Free Tier. Same images, less moving parts.

## Steps (ECS path)
1. **Network:** VPC with public subnets (ALB) and private subnets (ECS, RDS, Redis); security groups: ALB→web:8000, web/worker/beat→RDS:3306 and Redis:6379.
2. **Data:** create RDS MySQL (db.t3.micro to start), ElastiCache Redis, S3 bucket (block public access ON).
3. **Image:** `docker build -t supportdesk .` → push to ECR.
4. **Config:** put secrets in Secrets Manager; pass as ECS task env: `DEBUG=False`, `SECRET_KEY`, `ALLOWED_HOSTS`, `DB_*`, `REDIS_URL`, `EMAIL_BACKEND` (SES SMTP).
5. **Migrations:** run as a one-off ECS task *before* each release: `python manage.py migrate --noinput` (commit your migrations first!).
6. **Services:** three task definitions from the same image, different commands:
   - web: `daphne -b 0.0.0.0 -p 8000 config.asgi:application`
   - worker: `celery -A config worker -l info`
   - beat: `celery -A config beat -l info` (exactly one task)
7. **ALB:** HTTPS listener → target group on port 8000, health check `/health/`; enable stickiness is NOT required (JWT + Redis channel layer).
8. **Static/admin assets:** `collectstatic` + serve via WhiteNoise or S3/CloudFront.
9. **Attachments:** add `django-storages[boto3]`, set `DEFAULT_FILE_STORAGE` to S3 with private ACL; return presigned URLs instead of streaming.
10. **Observability:** CloudWatch log groups, alarms on 5xx, queue depth, RDS CPU; add Sentry for exceptions.

## CI/CD extension (GitHub Actions)
On tag `v*`: build image → push to ECR (OIDC role, no long-lived keys) → run migration task → `aws ecs update-service --force-new-deployment`.

## Production checklist
`DEBUG=False` · real `SECRET_KEY` · restricted `ALLOWED_HOSTS` · HTTPS only · DB backups + PITR · least-privilege IAM ·
private subnets for data stores · rate limits · log retention · cost alarms · committed migrations · rollback plan.

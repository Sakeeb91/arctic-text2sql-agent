# Operations Runbooks

This directory contains operational runbooks for Arctic Text2SQL. Each runbook provides step-by-step procedures for common operational tasks.

## Runbook Index

| Runbook | Description | When to Use |
|---------|-------------|-------------|
| [DEPLOYMENT.md](./DEPLOYMENT.md) | Deployment procedures | New releases, updates |
| [SCALING.md](./SCALING.md) | Scaling operations | Capacity changes |
| [DATABASE.md](./DATABASE.md) | Database operations | Backups, migrations, maintenance |
| [INCIDENT_RESPONSE.md](./INCIDENT_RESPONSE.md) | Incident handling | Outages, issues |
| [TROUBLESHOOTING.md](./TROUBLESHOOTING.md) | Problem diagnosis | Debugging issues |

## Quick Reference

### Emergency Contacts

| Role | Contact | Escalation |
|------|---------|------------|
| On-Call Engineer | PagerDuty | Immediate |
| Platform Lead | Slack #platform | 15 min |
| Security Lead | Slack #security | 5 min (security issues) |

### Critical Commands

```bash
# Check service health
curl https://api.text2sql.example.com/api/v1/health

# View logs
kubectl logs -f -l app.kubernetes.io/name=arctic-text2sql -n arctic-text2sql

# Rollback deployment
kubectl rollout undo deployment/arctic-text2sql-api -n arctic-text2sql

# Scale service
kubectl scale deployment/arctic-text2sql-api --replicas=5 -n arctic-text2sql
```

### Key URLs

| Service | URL |
|---------|-----|
| API | https://api.text2sql.example.com |
| Grafana | https://grafana.example.com |
| Prometheus | https://prometheus.example.com |
| Jaeger | https://jaeger.example.com |

## Runbook Guidelines

### Format

Each runbook follows this structure:

1. **Overview** - What the runbook covers
2. **Prerequisites** - Required access and tools
3. **Procedure** - Step-by-step instructions
4. **Verification** - How to confirm success
5. **Rollback** - How to undo if needed
6. **Related** - Links to other resources

### Best Practices

1. **Always verify before proceeding** - Check current state
2. **Document what you do** - Log actions in incident channel
3. **Escalate early** - Don't wait if unsure
4. **Test in staging first** - When possible
5. **Communicate status** - Keep stakeholders informed

## Updating Runbooks

When updating runbooks:

1. Test procedures in staging environment
2. Update timestamps and version numbers
3. Get peer review before merging
4. Notify team of significant changes

---

*Last Updated: 2024-01-15*
*Version: 1.0.0*

# Incident Response Runbook

## Overview

This runbook provides procedures for responding to production incidents affecting Arctic Text2SQL.

## Severity Levels

| Severity | Description | Response Time | Examples |
|----------|-------------|---------------|----------|
| SEV1 | Complete outage | Immediate | Service down, data loss |
| SEV2 | Major degradation | < 15 min | High error rate, slow response |
| SEV3 | Minor impact | < 1 hour | Partial functionality affected |
| SEV4 | Low impact | < 4 hours | Non-critical issues |

---

## Incident Response Process

### Step 1: Acknowledge

1. Acknowledge alert in PagerDuty/Slack
2. Join incident Slack channel: `#incident-active`
3. Post initial status:
   ```
   @here INCIDENT: [Service] [Issue Description]
   Severity: SEV[X]
   Impact: [User impact]
   Status: Investigating
   IC: @[your-name]
   ```

### Step 2: Assess

```bash
# Quick health check
curl -s https://api.text2sql.example.com/api/v1/health | jq

# Check pods
kubectl get pods -n arctic-text2sql

# Check recent events
kubectl get events -n arctic-text2sql --sort-by='.lastTimestamp' | tail -20

# Check error logs
kubectl logs -l app.kubernetes.io/name=arctic-text2sql -n arctic-text2sql --tail=100 | grep -i error
```

### Step 3: Mitigate

Choose appropriate mitigation based on issue:

| Issue | Mitigation |
|-------|------------|
| High latency | Scale up, enable caching |
| High error rate | Rollback deployment |
| Database issues | Failover to replica |
| Resource exhaustion | Scale up, restart pods |

### Step 4: Resolve

Document resolution in incident channel:
```
STATUS UPDATE:
Root Cause: [Description]
Resolution: [Actions taken]
Impact Duration: [Start] to [End]
Next Steps: [Follow-up items]
```

### Step 5: Post-Incident

1. Create incident report
2. Schedule postmortem (SEV1/SEV2)
3. Track action items
4. Update runbooks if needed

---

## SEV1: Complete Service Outage

### Symptoms
- All health checks failing
- 5xx errors on all endpoints
- No metrics from service

### Immediate Actions

```bash
# 1. Check deployment status
kubectl get deployment -n arctic-text2sql

# 2. Check for recent changes
kubectl rollout history deployment/arctic-text2sql-api -n arctic-text2sql

# 3. If recent deployment, rollback
kubectl rollout undo deployment/arctic-text2sql-api -n arctic-text2sql

# 4. Check if pods can start
kubectl describe pods -l app.kubernetes.io/name=arctic-text2sql -n arctic-text2sql

# 5. Check database connectivity
kubectl exec -it deployment/arctic-text2sql-api -n arctic-text2sql -- \
  python -c "from db.connection import get_database; import asyncio; asyncio.run(get_database().health_check())"
```

### Escalation

If not resolved in 15 minutes:
1. Page platform lead
2. Enable maintenance page
3. Notify stakeholders

---

## SEV2: High Error Rate

### Symptoms
- Error rate > 5%
- Specific endpoints failing
- Intermittent failures

### Diagnostic Commands

```bash
# Check error distribution
kubectl logs -l app.kubernetes.io/name=arctic-text2sql -n arctic-text2sql --tail=1000 | \
  grep -oP '"status":\K[0-9]+' | sort | uniq -c

# Check slow endpoints
kubectl logs -l app.kubernetes.io/name=arctic-text2sql -n arctic-text2sql --tail=1000 | \
  jq -r 'select(.duration > 2) | .path' | sort | uniq -c

# Check pod resource usage
kubectl top pods -l app.kubernetes.io/name=arctic-text2sql -n arctic-text2sql
```

### Resolution Steps

1. **If specific endpoint failing:**
   ```bash
   # Check that endpoint's dependencies
   # e.g., for /api/v1/query - check model service
   kubectl exec -it deployment/arctic-text2sql-api -- curl localhost:8000/monitoring/health
   ```

2. **If resource pressure:**
   ```bash
   # Scale up
   kubectl scale deployment/arctic-text2sql-api --replicas=6 -n arctic-text2sql
   ```

3. **If database issues:**
   ```bash
   # Check DB connections
   kubectl exec -it arctic-db-primary -- psql -U postgres -c "SELECT count(*) FROM pg_stat_activity;"
   ```

---

## SEV2: High Latency

### Symptoms
- P95 response time > 5s
- Query timeouts
- Slow model inference

### Diagnostic Commands

```bash
# Check latency metrics
curl -s https://api.text2sql.example.com/monitoring/metrics | \
  grep "request_duration_seconds"

# Check model inference times
kubectl logs -l app.kubernetes.io/name=arctic-text2sql -n arctic-text2sql --tail=500 | \
  jq -r 'select(.message | contains("inference")) | .duration'

# Check database query times
kubectl exec -it arctic-db-primary -- psql -U postgres -c "
  SELECT query, mean_exec_time
  FROM pg_stat_statements
  ORDER BY mean_exec_time DESC
  LIMIT 10;"
```

### Resolution Steps

1. **Model inference slow:**
   ```bash
   # Check model cache
   kubectl exec -it deployment/arctic-text2sql-api -- ls -la /home/appuser/.cache/huggingface

   # Restart to reload model
   kubectl rollout restart deployment/arctic-text2sql-api -n arctic-text2sql
   ```

2. **Database slow:**
   ```bash
   # Check for locks
   kubectl exec -it arctic-db-primary -- psql -U postgres -c "
     SELECT * FROM pg_stat_activity WHERE wait_event IS NOT NULL;"

   # Run vacuum if needed
   kubectl exec -it arctic-db-primary -- psql -U postgres -c "VACUUM ANALYZE;"
   ```

3. **Cache issues:**
   ```bash
   # Check Redis
   kubectl exec -it arctic-redis -- redis-cli INFO memory

   # Flush cache if corrupted
   kubectl exec -it arctic-redis -- redis-cli FLUSHDB
   ```

---

## SEV2: Database Failure

### Symptoms
- Connection refused errors
- Query timeout errors
- Replication lag alerts

### Immediate Actions

```bash
# 1. Check primary status
kubectl exec -it arctic-db-primary -- pg_isready

# 2. If primary down, check replica
kubectl exec -it arctic-db-replica -- pg_isready

# 3. If replica healthy, failover
kubectl exec -it arctic-db-replica -- /deploy/postgres/scripts/promote-replica.sh

# 4. Update connection string
kubectl set env deployment/arctic-text2sql-api \
  DATABASE_URL=postgresql://postgres:password@db-replica:5432/text2sql \
  -n arctic-text2sql
```

---

## SEV3: Cache Degradation

### Symptoms
- High cache miss rate
- Increased database load
- Slower response times

### Resolution

```bash
# Check Redis status
kubectl exec -it arctic-redis -- redis-cli PING

# Check memory
kubectl exec -it arctic-redis -- redis-cli INFO memory

# If memory full, increase or clear
kubectl exec -it arctic-redis -- redis-cli CONFIG SET maxmemory 2gb

# Restart if unresponsive
kubectl rollout restart deployment/arctic-redis -n arctic-text2sql
```

---

## Communication Templates

### Initial Notification
```
[INCIDENT] Arctic Text2SQL - [Service Impact]

We are aware of issues affecting [description].
Impact: [User-facing impact]
Status: Our team is investigating.
ETA: Investigating root cause, update in 15 minutes.
```

### Update
```
[UPDATE] Arctic Text2SQL Incident

Status: [Investigating/Mitigating/Resolved]
Root Cause: [If known]
Current Impact: [Remaining issues]
Next Update: [Time]
```

### Resolution
```
[RESOLVED] Arctic Text2SQL Incident

The issue affecting [service] has been resolved.
Duration: [Start time] to [End time]
Root Cause: [Brief description]
Resolution: [What was done]

We apologize for any inconvenience caused.
```

---

## Post-Incident Checklist

- [ ] Incident documented in system
- [ ] Timeline recorded
- [ ] Root cause identified
- [ ] Action items created
- [ ] Postmortem scheduled (SEV1/2)
- [ ] Stakeholders notified of resolution
- [ ] Monitoring gaps identified
- [ ] Runbooks updated if needed

---

## Related Documentation

- [Deployment Runbook](./DEPLOYMENT.md)
- [Database Runbook](./DATABASE.md)
- [Troubleshooting](./TROUBLESHOOTING.md)

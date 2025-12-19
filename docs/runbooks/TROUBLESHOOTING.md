# Troubleshooting Guide

## Overview

This guide provides troubleshooting procedures for common issues with Arctic Text2SQL.

---

## Quick Diagnostics

### System Health Check

```bash
#!/bin/bash
# Run comprehensive health check

echo "=== API Health ==="
curl -s https://api.text2sql.example.com/api/v1/health | jq

echo "=== Pod Status ==="
kubectl get pods -n arctic-text2sql

echo "=== Resource Usage ==="
kubectl top pods -n arctic-text2sql

echo "=== Recent Errors ==="
kubectl logs -l app.kubernetes.io/name=arctic-text2sql -n arctic-text2sql --tail=50 | grep -i error | tail -10

echo "=== Database Connection ==="
kubectl exec -it arctic-db-primary -- pg_isready

echo "=== Redis Status ==="
kubectl exec -it arctic-redis -- redis-cli PING
```

---

## Common Issues

### 1. API Not Responding

**Symptoms:**
- Connection refused
- 502/503 errors
- Timeout errors

**Diagnosis:**

```bash
# Check if pods are running
kubectl get pods -n arctic-text2sql

# Check pod logs
kubectl logs -l app.kubernetes.io/name=arctic-text2sql -n arctic-text2sql --tail=100

# Check pod events
kubectl describe pod -l app.kubernetes.io/name=arctic-text2sql -n arctic-text2sql | grep -A10 Events
```

**Solutions:**

| Cause | Solution |
|-------|----------|
| Pods not running | Check image pull, resources |
| Crash loop | Check logs for error, fix code |
| Liveness probe failing | Increase probe timeout |
| OOM killed | Increase memory limits |

```bash
# Restart deployment
kubectl rollout restart deployment/arctic-text2sql-api -n arctic-text2sql

# Check if image exists
docker pull ghcr.io/sakeeb91/arctic-text2sql-agent:latest
```

---

### 2. Model Loading Failed

**Symptoms:**
- Startup taking too long
- Model not loaded error
- CUDA out of memory

**Diagnosis:**

```bash
# Check startup logs
kubectl logs -l app.kubernetes.io/name=arctic-text2sql -n arctic-text2sql | grep -i model

# Check HuggingFace cache
kubectl exec -it deployment/arctic-text2sql-api -- ls -la /home/appuser/.cache/huggingface

# Check memory usage
kubectl top pods -n arctic-text2sql
```

**Solutions:**

| Cause | Solution |
|-------|----------|
| HF token missing | Set HUGGINGFACE_TOKEN secret |
| Disk space full | Clear cache, increase PVC |
| OOM during load | Enable quantization, increase memory |
| Network timeout | Check internet access, retry |

```bash
# Verify HuggingFace token
kubectl get secret arctic-text2sql-secrets -n arctic-text2sql -o jsonpath='{.data.HUGGINGFACE_TOKEN}' | base64 -d

# Clear and reload cache
kubectl exec -it deployment/arctic-text2sql-api -- rm -rf /home/appuser/.cache/huggingface/*
kubectl rollout restart deployment/arctic-text2sql-api -n arctic-text2sql
```

---

### 3. Database Connection Issues

**Symptoms:**
- Connection refused
- Too many connections
- Query timeout

**Diagnosis:**

```bash
# Test database connection
kubectl exec -it arctic-db-primary -- pg_isready

# Check connection count
kubectl exec -it arctic-db-primary -- psql -U postgres -c "SELECT count(*) FROM pg_stat_activity;"

# Check for locks
kubectl exec -it arctic-db-primary -- psql -U postgres -c "SELECT * FROM pg_stat_activity WHERE wait_event IS NOT NULL;"
```

**Solutions:**

| Cause | Solution |
|-------|----------|
| DB not running | Restart database container |
| Connection limit | Increase max_connections |
| Pool exhaustion | Increase pool size, use PgBouncer |
| Long-running query | Kill query, add timeout |

```bash
# Terminate idle connections
kubectl exec -it arctic-db-primary -- psql -U postgres -c "
  SELECT pg_terminate_backend(pid)
  FROM pg_stat_activity
  WHERE state = 'idle'
    AND state_change < now() - interval '10 minutes';"

# Increase connection limit
kubectl exec -it arctic-db-primary -- psql -U postgres -c "ALTER SYSTEM SET max_connections = 200;"
```

---

### 4. High Memory Usage

**Symptoms:**
- OOM kills
- Slow response times
- Pod restarts

**Diagnosis:**

```bash
# Check memory usage
kubectl top pods -n arctic-text2sql

# Check memory in container
kubectl exec -it deployment/arctic-text2sql-api -- cat /sys/fs/cgroup/memory/memory.usage_in_bytes

# Check for memory leaks in logs
kubectl logs -l app.kubernetes.io/name=arctic-text2sql -n arctic-text2sql | grep -i memory
```

**Solutions:**

| Cause | Solution |
|-------|----------|
| Model too large | Enable quantization |
| Memory leak | Update code, restart regularly |
| Too many concurrent requests | Reduce replicas, add rate limiting |
| Cache too large | Reduce cache size |

```bash
# Enable 8-bit quantization
kubectl set env deployment/arctic-text2sql-api ENABLE_8BIT_QUANTIZATION=true -n arctic-text2sql

# Increase memory limit
kubectl patch deployment arctic-text2sql-api -n arctic-text2sql --patch '{
  "spec": {"template": {"spec": {"containers": [{"name": "api", "resources": {"limits": {"memory": "48Gi"}}}]}}}
}'
```

---

### 5. Slow Query Response

**Symptoms:**
- High latency
- Query timeouts
- User complaints

**Diagnosis:**

```bash
# Check response time metrics
curl -s https://api.text2sql.example.com/monitoring/metrics | \
  grep request_duration_seconds

# Check slow queries in logs
kubectl logs -l app.kubernetes.io/name=arctic-text2sql -n arctic-text2sql | \
  jq -r 'select(.duration > 5)'

# Check database slow queries
kubectl exec -it arctic-db-primary -- psql -U postgres -c "
  SELECT query, calls, mean_exec_time
  FROM pg_stat_statements
  ORDER BY mean_exec_time DESC
  LIMIT 10;"
```

**Solutions:**

| Cause | Solution |
|-------|----------|
| Model inference slow | Check GPU, reduce model size |
| Database slow | Add indexes, vacuum |
| No caching | Enable Redis caching |
| Network latency | Check network, use CDN |

```bash
# Enable query result caching
kubectl set env deployment/arctic-text2sql-api ENABLE_QUERY_CACHE=true -n arctic-text2sql

# Vacuum database
kubectl exec -it arctic-db-primary -- psql -U postgres -c "VACUUM ANALYZE;"
```

---

### 6. Cache Issues

**Symptoms:**
- High miss rate
- Redis errors in logs
- Increased database load

**Diagnosis:**

```bash
# Check Redis status
kubectl exec -it arctic-redis -- redis-cli INFO

# Check cache hit rate
kubectl exec -it arctic-redis -- redis-cli INFO stats | grep keyspace

# Check memory usage
kubectl exec -it arctic-redis -- redis-cli INFO memory
```

**Solutions:**

| Cause | Solution |
|-------|----------|
| Redis down | Restart Redis |
| Memory full | Increase maxmemory |
| Wrong eviction policy | Set volatile-lru |
| Connection refused | Check network policy |

```bash
# Clear corrupted cache
kubectl exec -it arctic-redis -- redis-cli FLUSHDB

# Increase memory
kubectl exec -it arctic-redis -- redis-cli CONFIG SET maxmemory 2gb

# Set eviction policy
kubectl exec -it arctic-redis -- redis-cli CONFIG SET maxmemory-policy volatile-lru
```

---

### 7. SSL/TLS Issues

**Symptoms:**
- Certificate errors
- HTTPS not working
- Mixed content warnings

**Diagnosis:**

```bash
# Check certificate
openssl s_client -connect api.text2sql.example.com:443 -servername api.text2sql.example.com

# Check certificate expiry
echo | openssl s_client -servername api.text2sql.example.com -connect api.text2sql.example.com:443 2>/dev/null | \
  openssl x509 -noout -dates
```

**Solutions:**

| Cause | Solution |
|-------|----------|
| Expired certificate | Renew with cert-manager |
| Wrong domain | Update certificate SANs |
| Missing intermediate | Add CA bundle |

```bash
# Force certificate renewal (cert-manager)
kubectl delete certificate arctic-text2sql-cert -n arctic-text2sql
kubectl apply -f deploy/kubernetes/base/ingress.yaml
```

---

### 8. Rate Limiting Issues

**Symptoms:**
- 429 Too Many Requests
- Legitimate users blocked
- Inconsistent blocking

**Diagnosis:**

```bash
# Check current limits
kubectl get configmap arctic-text2sql-config -n arctic-text2sql -o yaml | grep RATE

# Check rate limit logs
kubectl logs -l app.kubernetes.io/name=arctic-text2sql -n arctic-text2sql | grep -i "rate limit"
```

**Solutions:**

```bash
# Increase rate limit
kubectl set env deployment/arctic-text2sql-api \
  RATE_LIMIT_REQUESTS=200 \
  RATE_LIMIT_WINDOW=60 \
  -n arctic-text2sql

# Whitelist IP (in nginx)
# Add to allow list in ingress annotations
```

---

## Log Analysis

### Finding Errors

```bash
# All errors
kubectl logs -l app.kubernetes.io/name=arctic-text2sql -n arctic-text2sql | grep -i error

# Specific error code
kubectl logs -l app.kubernetes.io/name=arctic-text2sql -n arctic-text2sql | jq 'select(.status == 500)'

# Errors in time range
kubectl logs -l app.kubernetes.io/name=arctic-text2sql -n arctic-text2sql --since=1h | grep -i error
```

### Correlation with Traces

```bash
# Find trace for specific request
kubectl logs -l app.kubernetes.io/name=arctic-text2sql -n arctic-text2sql | \
  jq 'select(.request_id == "abc123")'

# View in Jaeger
# Open https://jaeger.example.com/trace/{trace_id}
```

---

## Metrics Investigation

### Prometheus Queries

```promql
# Error rate
sum(rate(arctic_text2sql_http_requests_total{status=~"5.."}[5m])) /
sum(rate(arctic_text2sql_http_requests_total[5m]))

# Latency percentiles
histogram_quantile(0.95, rate(arctic_text2sql_http_request_duration_seconds_bucket[5m]))

# Model inference time
arctic_text2sql_model_inference_duration_seconds{quantile="0.95"}

# Cache hit rate
sum(arctic_text2sql_cache_hits_total) /
(sum(arctic_text2sql_cache_hits_total) + sum(arctic_text2sql_cache_misses_total))
```

---

## Recovery Procedures

### Full Stack Restart

```bash
# 1. Scale down
kubectl scale deployment --all --replicas=0 -n arctic-text2sql

# 2. Clear state if needed
kubectl exec -it arctic-redis -- redis-cli FLUSHALL

# 3. Scale up database first
kubectl scale statefulset arctic-postgres --replicas=1 -n arctic-text2sql
sleep 60

# 4. Scale up Redis
kubectl scale deployment arctic-redis --replicas=1 -n arctic-text2sql
sleep 30

# 5. Scale up API
kubectl scale deployment arctic-text2sql-api --replicas=3 -n arctic-text2sql

# 6. Verify
kubectl get pods -n arctic-text2sql
curl https://api.text2sql.example.com/api/v1/health
```

---

## Related Documentation

- [Incident Response](./INCIDENT_RESPONSE.md)
- [Deployment Runbook](./DEPLOYMENT.md)
- [Database Operations](./DATABASE.md)

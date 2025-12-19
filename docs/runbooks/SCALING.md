# Scaling Operations Runbook

## Overview

This runbook covers scaling procedures for Arctic Text2SQL to handle varying workloads.

## Prerequisites

- [ ] Kubernetes cluster access
- [ ] Monitoring dashboard access
- [ ] Understanding of current capacity

---

## Procedure 1: Manual Horizontal Scaling

### When to Use

- Anticipated traffic spike (marketing campaign, product launch)
- Current capacity insufficient
- HPA not responding fast enough

### Step 1: Check Current State

```bash
# Current replica count
kubectl get deployment arctic-text2sql-api -n arctic-text2sql

# Current HPA status
kubectl get hpa arctic-text2sql-api -n arctic-text2sql

# Resource utilization
kubectl top pods -l app.kubernetes.io/name=arctic-text2sql -n arctic-text2sql
```

### Step 2: Scale Deployment

```bash
# Scale to specific number
kubectl scale deployment/arctic-text2sql-api --replicas=6 -n arctic-text2sql

# Verify scaling
kubectl get pods -n arctic-text2sql -w
```

### Step 3: Verify New Capacity

```bash
# Wait for all pods ready
kubectl wait --for=condition=Ready pods -l app.kubernetes.io/name=arctic-text2sql -n arctic-text2sql --timeout=300s

# Check health
for pod in $(kubectl get pods -l app.kubernetes.io/name=arctic-text2sql -n arctic-text2sql -o name); do
  kubectl exec $pod -n arctic-text2sql -- curl -s localhost:8000/api/v1/health
done
```

---

## Procedure 2: Modify HPA Limits

### When to Use

- Need to increase maximum capacity
- Adjusting scaling thresholds
- Changing minimum replicas

### Step 1: Review Current HPA

```bash
kubectl describe hpa arctic-text2sql-api -n arctic-text2sql
```

### Step 2: Update HPA

```bash
# Update max replicas
kubectl patch hpa arctic-text2sql-api -n arctic-text2sql --patch '{
  "spec": {
    "maxReplicas": 15
  }
}'

# Update target utilization
kubectl patch hpa arctic-text2sql-api -n arctic-text2sql --patch '{
  "spec": {
    "metrics": [{
      "type": "Resource",
      "resource": {
        "name": "cpu",
        "target": {
          "type": "Utilization",
          "averageUtilization": 60
        }
      }
    }]
  }
}'
```

### Step 3: Apply Configuration File

For permanent changes:

```bash
# Edit the HPA manifest
kubectl edit hpa arctic-text2sql-api -n arctic-text2sql

# Or apply updated file
kubectl apply -f deploy/kubernetes/base/hpa.yaml
```

---

## Procedure 3: Scale Database

### When to Use

- Connection pool exhaustion
- Query performance degradation
- Read replica needed

### Step 1: Add Read Replica

```bash
# Docker Compose
docker-compose -f docker-compose.yml -f docker-compose.db-ha.yml up -d db-replica

# Kubernetes - scale StatefulSet
kubectl scale statefulset arctic-postgres -n arctic-text2sql --replicas=2
```

### Step 2: Verify Replication

```bash
# Check replication status
docker exec arctic-db-primary psql -U postgres -c "SELECT * FROM pg_stat_replication;"

# Check replica lag
docker exec arctic-db-replica /deploy/postgres/scripts/check-replication.sh
```

### Step 3: Update Connection Routing

For read-heavy workloads, route reads to replica:

```python
# Application configuration
READ_DATABASE_URL = "postgresql://...@db-replica:5432/text2sql"
WRITE_DATABASE_URL = "postgresql://...@db-primary:5432/text2sql"
```

---

## Procedure 4: Scale Redis Cache

### When to Use

- Cache memory pressure
- High cache miss rate
- Need for cache clustering

### Step 1: Check Cache Status

```bash
# Memory usage
docker exec arctic-redis redis-cli INFO memory

# Connected clients
docker exec arctic-redis redis-cli CLIENT LIST | wc -l

# Cache hit rate
docker exec arctic-redis redis-cli INFO stats | grep keyspace
```

### Step 2: Increase Memory

```bash
# Docker - update compose file and restart
docker-compose up -d redis

# Kubernetes - update resource limits
kubectl patch deployment arctic-redis -n arctic-text2sql --patch '{
  "spec": {
    "template": {
      "spec": {
        "containers": [{
          "name": "redis",
          "resources": {
            "limits": {"memory": "2Gi"},
            "requests": {"memory": "1Gi"}
          }
        }]
      }
    }
  }
}'
```

---

## Procedure 5: Emergency Scale-Out

### When to Use

- Production incident
- Immediate capacity needed
- Automated scaling insufficient

### Step 1: Immediate Actions

```bash
# Scale to maximum immediately
kubectl scale deployment/arctic-text2sql-api --replicas=10 -n arctic-text2sql

# Temporarily disable PDB (with caution)
kubectl delete pdb arctic-text2sql-api -n arctic-text2sql --ignore-not-found
```

### Step 2: Request Additional Nodes (if needed)

```bash
# AWS EKS - scale node group
aws eks update-nodegroup-config \
  --cluster-name production \
  --nodegroup-name api-nodes \
  --scaling-config minSize=3,maxSize=20,desiredSize=10

# GKE - resize node pool
gcloud container clusters resize production \
  --node-pool api-pool \
  --num-nodes 10 \
  --zone us-central1-a
```

### Step 3: Verify Capacity

```bash
# Check all pods running
kubectl get pods -n arctic-text2sql -o wide

# Monitor response times
watch 'curl -s -o /dev/null -w "%{time_total}" https://api.text2sql.example.com/api/v1/health'
```

---

## Procedure 6: Scale Down

### When to Use

- After traffic spike
- Cost optimization
- Maintenance window

### Step 1: Verify Low Utilization

```bash
# Check metrics for past hour
kubectl top pods -l app.kubernetes.io/name=arctic-text2sql -n arctic-text2sql

# Verify request rate has dropped
# Check Grafana dashboard
```

### Step 2: Gradual Scale Down

```bash
# Reduce gradually (not all at once)
kubectl scale deployment/arctic-text2sql-api --replicas=4 -n arctic-text2sql
sleep 300
kubectl scale deployment/arctic-text2sql-api --replicas=2 -n arctic-text2sql
```

### Step 3: Restore HPA Control

```bash
# Re-enable HPA (it will manage replicas)
kubectl patch hpa arctic-text2sql-api -n arctic-text2sql --patch '{
  "spec": {
    "minReplicas": 2,
    "maxReplicas": 10
  }
}'
```

---

## Capacity Planning Reference

### Resource Requirements per Pod

| Resource | Request | Limit |
|----------|---------|-------|
| CPU | 2 cores | 8 cores |
| Memory | 16Gi | 32Gi |
| GPU (optional) | 0 | 1 |

### Capacity Table

| Concurrent Users | API Pods | DB Connections | Redis Memory |
|------------------|----------|----------------|--------------|
| 100 | 2 | 50 | 512Mi |
| 500 | 4 | 100 | 1Gi |
| 1,000 | 6 | 200 | 2Gi |
| 5,000 | 10 | 500 | 4Gi |

---

## Verification

After scaling:

- [ ] All pods in Ready state
- [ ] No pending pods
- [ ] Health checks passing
- [ ] Response times acceptable
- [ ] No error spike
- [ ] Metrics being collected

---

## Related Documentation

- [Auto-Scaling Configuration](../deployment/AUTO_SCALING.md)
- [Architecture Overview](../deployment/ARCHITECTURE.md)
- [Troubleshooting](./TROUBLESHOOTING.md)

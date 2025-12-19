# Deployment Runbook

## Overview

This runbook covers deployment procedures for Arctic Text2SQL across all environments.

## Prerequisites

- [ ] Access to GitHub repository
- [ ] Kubernetes cluster access (kubectl configured)
- [ ] Docker registry credentials
- [ ] Environment secrets configured

## Pre-Deployment Checklist

- [ ] All tests passing in CI
- [ ] Security scan completed
- [ ] Version tag created
- [ ] Changelog updated
- [ ] Stakeholders notified

---

## Procedure 1: Deploy to Staging

### Step 1: Verify CI Status

```bash
# Check latest CI run
gh run list --workflow=ci.yml --limit 5

# View specific run
gh run view <run-id>
```

### Step 2: Deploy to Staging

**Option A: Automatic (via GitHub Actions)**

Push to `develop` branch triggers automatic staging deployment.

```bash
git checkout develop
git pull origin develop
git merge feature/your-branch
git push origin develop
```

**Option B: Manual Deployment**

```bash
# Build and push image
docker build -t ghcr.io/sakeeb91/arctic-text2sql-agent:staging .
docker push ghcr.io/sakeeb91/arctic-text2sql-agent:staging

# Deploy to Kubernetes
kubectl apply -k deploy/kubernetes/overlays/staging

# Or Docker Compose
docker-compose -f docker-compose.yml -f docker-compose.staging.yml up -d
```

### Step 3: Verify Deployment

```bash
# Check pod status
kubectl get pods -n arctic-text2sql-staging -w

# Check logs
kubectl logs -f -l app.kubernetes.io/name=arctic-text2sql -n arctic-text2sql-staging

# Test health endpoint
curl https://api-staging.text2sql.example.com/api/v1/health
```

### Step 4: Run Smoke Tests

```bash
# Test query endpoint
curl -X POST https://api-staging.text2sql.example.com/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"query": "Show all tables", "database_id": "test"}'
```

---

## Procedure 2: Deploy to Production

### Step 1: Create Release

```bash
# Ensure on main branch
git checkout main
git pull origin main

# Create release tag
git tag -a v1.2.3 -m "Release v1.2.3: Description"
git push origin v1.2.3
```

This triggers the release workflow which:
1. Builds and tests the image
2. Pushes to container registry
3. Creates GitHub release

### Step 2: Approve Production Deployment

1. Navigate to GitHub Actions
2. Find the `deploy-production` workflow
3. Click "Review deployments"
4. Select "production" environment
5. Click "Approve and deploy"

### Step 3: Monitor Deployment

```bash
# Watch rollout
kubectl rollout status deployment/arctic-text2sql-api -n arctic-text2sql

# Check pod status
kubectl get pods -n arctic-text2sql -w

# View events
kubectl get events -n arctic-text2sql --sort-by='.lastTimestamp'
```

### Step 4: Verify Production

```bash
# Health check
curl https://api.text2sql.example.com/api/v1/health

# Check metrics
curl https://api.text2sql.example.com/monitoring/metrics | grep arctic_text2sql

# Verify in Grafana
# Open https://grafana.example.com/d/arctic-text2sql
```

---

## Procedure 3: Rollback Deployment

### Immediate Rollback (Kubernetes)

```bash
# Rollback to previous version
kubectl rollout undo deployment/arctic-text2sql-api -n arctic-text2sql

# Rollback to specific revision
kubectl rollout undo deployment/arctic-text2sql-api -n arctic-text2sql --to-revision=3

# Verify rollback
kubectl rollout status deployment/arctic-text2sql-api -n arctic-text2sql
```

### Rollback via GitHub Actions

1. Go to Actions → Rollback
2. Click "Run workflow"
3. Enter target version (e.g., `v1.2.2`)
4. Select environment
5. Provide reason

### Rollback Docker Compose

```bash
# Stop current deployment
docker-compose -f docker-compose.yml -f docker-compose.prod.yml down

# Deploy previous version
IMAGE_TAG=v1.2.2 docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

---

## Procedure 4: Blue-Green Deployment

### Step 1: Deploy Green Environment

```bash
# Create green deployment
kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: arctic-text2sql-api-green
  namespace: arctic-text2sql
spec:
  replicas: 3
  selector:
    matchLabels:
      app: arctic-text2sql
      version: green
  template:
    metadata:
      labels:
        app: arctic-text2sql
        version: green
    spec:
      containers:
        - name: api
          image: ghcr.io/sakeeb91/arctic-text2sql-agent:v1.2.3
EOF
```

### Step 2: Test Green Environment

```bash
# Port-forward to green pods
kubectl port-forward deployment/arctic-text2sql-api-green 8001:8000 -n arctic-text2sql

# Test locally
curl http://localhost:8001/api/v1/health
```

### Step 3: Switch Traffic

```bash
# Update service selector to green
kubectl patch service arctic-text2sql-api -n arctic-text2sql \
  -p '{"spec":{"selector":{"version":"green"}}}'
```

### Step 4: Cleanup Blue

After verification (wait at least 30 minutes):

```bash
# Delete blue deployment
kubectl delete deployment arctic-text2sql-api-blue -n arctic-text2sql
```

---

## Verification

### Health Check Matrix

| Endpoint | Expected | Actual |
|----------|----------|--------|
| `/api/v1/health` | 200 OK | |
| `/monitoring/metrics` | 200 OK | |
| `/api/v1/schema/test` | 200 OK | |

### Post-Deployment Checklist

- [ ] Health endpoints responding
- [ ] Metrics being collected
- [ ] Logs flowing to aggregator
- [ ] No error spike in dashboards
- [ ] Response times normal
- [ ] Cache functioning

---

## Troubleshooting

### Deployment Stuck

```bash
# Check pod events
kubectl describe pod -l app.kubernetes.io/name=arctic-text2sql -n arctic-text2sql

# Check if image can be pulled
kubectl get events -n arctic-text2sql | grep -i pull

# Check resource constraints
kubectl describe nodes | grep -A5 "Allocated resources"
```

### Image Not Found

```bash
# Verify image exists
docker pull ghcr.io/sakeeb91/arctic-text2sql-agent:v1.2.3

# Check registry credentials
kubectl get secret regcred -n arctic-text2sql -o yaml
```

### Rollout Timeout

```bash
# Increase timeout
kubectl rollout status deployment/arctic-text2sql-api -n arctic-text2sql --timeout=10m

# Check readiness probe
kubectl describe pod -l app.kubernetes.io/name=arctic-text2sql -n arctic-text2sql | grep -A10 "Readiness"
```

---

## Related Documentation

- [Architecture Overview](../deployment/ARCHITECTURE.md)
- [Environment Configuration](../deployment/ENVIRONMENTS.md)
- [Incident Response](./INCIDENT_RESPONSE.md)

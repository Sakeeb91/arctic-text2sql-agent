# Deployment

## Quick Start (Development)

```bash
uvicorn app.main:app --reload --port 8000
```

## Docker

### Build and Run

```bash
# Build
docker build -t text2sql-agent .

# Run
docker run -p 8000:8000 --env-file .env text2sql-agent
```

### Docker Compose

```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f

# Stop
docker-compose down
```

### Build Options

```bash
# CPU-only build (smaller image)
docker build --build-arg TORCH_CPU=true -t text2sql-agent .

# Production target
docker build --target production -t text2sql-agent .

# Development target (includes test tools)
docker build --target development -t text2sql-agent .
```

## Production Deployment

### Environment Configuration

Create separate configs for each environment:

```bash
# Staging
docker-compose -f docker-compose.yml -f docker-compose.staging.yml up -d

# Production
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# With load balancer
docker-compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.lb.yml up -d
```

### Kubernetes

```bash
# Staging
kubectl apply -k deploy/kubernetes/overlays/staging

# Production
kubectl apply -k deploy/kubernetes/overlays/production
```

## Production Checklist

### Database
- [ ] Use PostgreSQL or MySQL (not SQLite)
- [ ] Enable connection pooling
- [ ] Set up read replicas for scaling
- [ ] Configure automated backups

### Security
- [ ] Set strong `SECRET_KEY`
- [ ] Enable HTTPS with valid certificates
- [ ] Configure rate limiting
- [ ] Restrict CORS origins
- [ ] Enable authentication

### Performance
- [ ] Enable query caching
- [ ] Use 8-bit quantization for memory efficiency
- [ ] Configure horizontal scaling
- [ ] Set up CDN for static assets

### Monitoring
- [ ] Enable Prometheus metrics
- [ ] Set up Grafana dashboards
- [ ] Configure alerting rules
- [ ] Enable structured logging

### Infrastructure
- [ ] Set up load balancer
- [ ] Configure auto-scaling
- [ ] Plan disaster recovery
- [ ] Document runbooks

## Scaling

### Horizontal Scaling

The API is stateless and can be scaled horizontally:

```yaml
# docker-compose.prod.yml
services:
  api:
    deploy:
      replicas: 3
```

### Auto-Scaling (Kubernetes)

```yaml
# HPA configuration
spec:
  minReplicas: 2
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        targetAverageUtilization: 70
```

## Health Checks

```bash
# Liveness
curl http://localhost:8000/monitoring/health/live

# Readiness
curl http://localhost:8000/monitoring/health/ready

# Full health
curl http://localhost:8000/api/v1/health
```

## Monitoring Stack

```bash
# Start with monitoring
docker-compose -f docker-compose.yml -f docker-compose.monitoring.yml up -d

# Access UIs
# Grafana:      http://localhost:3000 (admin/admin)
# Prometheus:   http://localhost:9090
# Jaeger:       http://localhost:16686
```

## GitHub Container Registry

Images are published to GHCR on release:

```bash
# Pull latest
docker pull ghcr.io/sakeeb91/text2sql-agent:latest

# Pull specific version
docker pull ghcr.io/sakeeb91/text2sql-agent:1.0.0
```

## Rollback

```bash
# Docker Compose
docker-compose pull  # Get previous version
docker-compose up -d

# Kubernetes
kubectl rollout undo deployment/text2sql-agent
```

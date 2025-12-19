# Environment Configuration

## Overview

Arctic Text2SQL supports three deployment environments: Development, Staging, and Production. Each environment has specific configurations optimized for its purpose.

## Environment Comparison

| Aspect | Development | Staging | Production |
|--------|-------------|---------|------------|
| **Purpose** | Local development | Testing & QA | Live traffic |
| **Data** | Sample/mock | Production clone | Real data |
| **Scale** | Single instance | 2 replicas | 2-10+ replicas |
| **Logging** | Console, DEBUG | JSON, DEBUG | JSON, INFO |
| **Monitoring** | Optional | Full stack | Full stack + alerts |
| **SSL** | Self-signed | Valid cert | Valid cert + HSTS |
| **Model** | CPU mode | CPU/GPU | GPU recommended |

## Development Environment

### Quick Start

```bash
# Start development stack
docker-compose up -d

# Or with monitoring
docker-compose --profile monitoring up -d
```

### Configuration

```yaml
# docker-compose.yml (default development settings)
services:
  api:
    environment:
      - API_DEBUG=true
      - LOG_LEVEL=DEBUG
      - LOG_FORMAT=console
      - MODEL_DEVICE=cpu
      - AGENT_MIN_CONFIDENCE=0.7
      - AGENT_VERBOSITY=2
```

### Environment Variables

Create a `.env` file from the template:

```bash
cp .env.example .env
```

Key development settings:

```bash
# .env (development)
API_DEBUG=true
LOG_LEVEL=DEBUG
LOG_FORMAT=console
MODEL_DEVICE=cpu

# Database (local PostgreSQL)
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/text2sql

# HuggingFace (required)
HUGGINGFACE_TOKEN=hf_xxxxxxxxxxxxx

# Agent settings
AGENT_MAX_STEPS=5
AGENT_MIN_CONFIDENCE=0.7
AGENT_VERBOSITY=2

# Cache
REDIS_URL=redis://localhost:6379/0
```

### Hot Reload

Source directories are mounted for hot reload:

```yaml
volumes:
  - ./app:/app/app:ro
  - ./db:/app/db:ro
  - ./models:/app/models:ro
```

## Staging Environment

### Deployment

```bash
# Deploy staging
docker-compose -f docker-compose.yml \
               -f docker-compose.staging.yml \
               -f docker-compose.monitoring.yml up -d
```

### Configuration

```yaml
# docker-compose.staging.yml
services:
  api:
    image: ghcr.io/sakeeb91/arctic-text2sql-agent:${IMAGE_TAG:-latest}
    environment:
      - API_DEBUG=false
      - LOG_LEVEL=DEBUG
      - LOG_FORMAT=json
      - AGENT_MIN_CONFIDENCE=0.7
      - AGENT_VERBOSITY=2
    deploy:
      replicas: 2
      resources:
        limits:
          memory: 16G
        reservations:
          memory: 8G
```

### Environment Variables

```bash
# .env.staging
API_DEBUG=false
LOG_LEVEL=DEBUG
LOG_FORMAT=json

# Database
DATABASE_URL=postgresql://text2sql:${DB_PASSWORD}@db:5432/text2sql_staging

# Model
MODEL_DEVICE=cpu
TEXT2SQL_MODEL=Snowflake/Arctic-Text2SQL-R1-7B

# Agent
AGENT_MAX_STEPS=5
AGENT_MIN_CONFIDENCE=0.7
AGENT_VERBOSITY=2

# Monitoring
ENABLE_METRICS=true
ENABLE_TRACING=true
OTLP_ENDPOINT=http://jaeger:4317
TRACE_SAMPLE_RATE=1.0

# Security
SECRET_KEY=${STAGING_SECRET_KEY}
RATE_LIMIT_REQUESTS=100
RATE_LIMIT_WINDOW=60
```

### Staging-Specific Features

- Full monitoring stack enabled
- Debug logging for troubleshooting
- Lower confidence threshold for testing
- High verbosity for agent reasoning
- Full trace sampling

## Production Environment

### Deployment

```bash
# Deploy production with full stack
docker-compose -f docker-compose.yml \
               -f docker-compose.prod.yml \
               -f docker-compose.lb.yml \
               -f docker-compose.db-ha.yml \
               -f docker-compose.monitoring.yml up -d
```

### Configuration

```yaml
# docker-compose.prod.yml
services:
  api:
    image: ghcr.io/sakeeb91/arctic-text2sql-agent:${IMAGE_TAG}
    environment:
      - API_DEBUG=false
      - LOG_LEVEL=INFO
      - LOG_FORMAT=json
      - AGENT_MIN_CONFIDENCE=0.8
      - AGENT_VERBOSITY=0
    deploy:
      mode: replicated
      replicas: ${REPLICAS:-2}
      resources:
        limits:
          memory: 32G
        reservations:
          memory: 16G
      update_config:
        parallelism: 1
        delay: 30s
        failure_action: rollback
        order: start-first
```

### Environment Variables

```bash
# .env.production (use secrets management in practice)
API_DEBUG=false
LOG_LEVEL=INFO
LOG_FORMAT=json

# Database (use connection pooler)
DATABASE_URL=postgresql://text2sql:${DB_PASSWORD}@pgbouncer:6432/text2sql_prod
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20

# Model
MODEL_DEVICE=cuda
TEXT2SQL_MODEL=Snowflake/Arctic-Text2SQL-R1-7B
ENABLE_8BIT_QUANTIZATION=true

# Agent (stricter settings)
AGENT_MAX_STEPS=5
AGENT_MIN_CONFIDENCE=0.8
AGENT_VERBOSITY=0

# Monitoring
ENABLE_METRICS=true
ENABLE_TRACING=true
OTLP_ENDPOINT=http://jaeger:4317
TRACE_SAMPLE_RATE=0.1  # 10% sampling in production

# Security (use secrets)
SECRET_KEY=${PRODUCTION_SECRET_KEY}
RATE_LIMIT_REQUESTS=100
RATE_LIMIT_WINDOW=60

# CORS
CORS_ORIGINS=https://app.example.com,https://admin.example.com
```

### Production-Specific Features

- Pre-built Docker images (no source mounts)
- Higher confidence threshold
- GPU acceleration enabled
- Reduced trace sampling (10%)
- Rolling updates with auto-rollback
- Resource limits and reservations
- JSON structured logging

## Secrets Management

### Recommended Approaches

| Tool | Use Case | Integration |
|------|----------|-------------|
| Docker Secrets | Docker Swarm | Native |
| Kubernetes Secrets | Kubernetes | Native |
| AWS Secrets Manager | AWS deployment | External |
| HashiCorp Vault | Multi-cloud | External |
| GitHub Actions Secrets | CI/CD | Native |

### Docker Secrets Example

```yaml
# docker-compose.prod.yml
services:
  api:
    secrets:
      - db_password
      - secret_key
      - huggingface_token
    environment:
      - DATABASE_URL=postgresql://text2sql:$(cat /run/secrets/db_password)@db:5432/text2sql

secrets:
  db_password:
    external: true
  secret_key:
    external: true
  huggingface_token:
    external: true
```

### Kubernetes Secrets

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: arctic-text2sql-secrets
type: Opaque
stringData:
  database-url: postgresql://...
  secret-key: your-secret-key
  huggingface-token: hf_xxxxx
```

## Configuration Validation

### Startup Checks

The application validates configuration at startup:

```python
# app/config.py
class Settings(BaseSettings):
    @validator("database_url")
    def validate_database_url(cls, v):
        if not v or v == "":
            raise ValueError("DATABASE_URL is required")
        return v
```

### Health Endpoint

Check configuration via health endpoint:

```bash
curl http://localhost:8000/api/v1/health

# Response
{
  "status": "healthy",
  "components": {
    "database": {"status": "healthy"},
    "model": {"status": "healthy"},
    "cache": {"status": "healthy"}
  },
  "config": {
    "environment": "production",
    "debug": false,
    "model_device": "cuda"
  }
}
```

## Environment Transitions

### Development → Staging

1. Build and tag Docker image
2. Push to container registry
3. Update `IMAGE_TAG` in staging
4. Deploy with staging compose files

### Staging → Production

1. Run full test suite
2. Create release tag
3. Promote image to production
4. Deploy with approval gate

```bash
# Promote staging image to production
docker tag ghcr.io/sakeeb91/arctic-text2sql-agent:staging \
           ghcr.io/sakeeb91/arctic-text2sql-agent:v1.0.0
docker push ghcr.io/sakeeb91/arctic-text2sql-agent:v1.0.0
```

## Related Documentation

- [Architecture Overview](./ARCHITECTURE.md)
- [Deployment Runbook](../runbooks/DEPLOYMENT.md)
- [Security Configuration](./SECURITY.md)

# Deployment Architecture

## Overview

Arctic Text2SQL uses a microservices-based architecture designed for horizontal scaling, high availability, and fault tolerance. This document describes the production deployment architecture and its components.

## Architecture Diagram

```
                                    ┌─────────────────────────────────────────────────────────────┐
                                    │                     INTERNET                                │
                                    └─────────────────────────────────────────────────────────────┘
                                                              │
                                                              ▼
                                    ┌─────────────────────────────────────────────────────────────┐
                                    │                  CDN (CloudFlare/AWS CloudFront)            │
                                    │              - Static asset caching                          │
                                    │              - DDoS protection                               │
                                    │              - SSL termination (optional)                    │
                                    └─────────────────────────────────────────────────────────────┘
                                                              │
                                                              ▼
                                    ┌─────────────────────────────────────────────────────────────┐
                                    │               LOAD BALANCER (Nginx/ALB)                      │
                                    │              - SSL termination                               │
                                    │              - Health checks                                 │
                                    │              - Request routing                               │
                                    │              - Rate limiting (L7)                            │
                                    └─────────────────────────────────────────────────────────────┘
                                                              │
                          ┌───────────────────────────────────┼───────────────────────────────────┐
                          │                                   │                                   │
                          ▼                                   ▼                                   ▼
              ┌───────────────────────┐       ┌───────────────────────┐       ┌───────────────────────┐
              │    API Instance 1     │       │    API Instance 2     │       │    API Instance N     │
              │  ┌─────────────────┐  │       │  ┌─────────────────┐  │       │  ┌─────────────────┐  │
              │  │ FastAPI (8000)  │  │       │  │ FastAPI (8000)  │  │       │  │ FastAPI (8000)  │  │
              │  │ + ML Model      │  │       │  │ + ML Model      │  │       │  │ + ML Model      │  │
              │  │ + ReAct Agent   │  │       │  │ + ReAct Agent   │  │       │  │ + ReAct Agent   │  │
              │  └─────────────────┘  │       │  └─────────────────┘  │       │  └─────────────────┘  │
              │  Memory: 16-32GB      │       │  Memory: 16-32GB      │       │  Memory: 16-32GB      │
              │  GPU: Optional        │       │  GPU: Optional        │       │  GPU: Optional        │
              └───────────────────────┘       └───────────────────────┘       └───────────────────────┘
                          │                                   │                                   │
                          └───────────────────────────────────┼───────────────────────────────────┘
                                                              │
                          ┌───────────────────────────────────┴───────────────────────────────────┐
                          │                                                                       │
                          ▼                                                                       ▼
              ┌───────────────────────────────────────┐                       ┌───────────────────────────────────────┐
              │         REDIS CLUSTER                  │                       │     POSTGRESQL HA CLUSTER             │
              │  ┌─────────────┐  ┌─────────────┐     │                       │  ┌─────────────┐  ┌─────────────┐     │
              │  │   Master    │  │   Replica   │     │                       │  │   Primary   │  │   Replica   │     │
              │  │  (6379)     │◄─│  (6379)     │     │                       │  │  (5432)     │──▶│  (5432)     │     │
              │  └─────────────┘  └─────────────┘     │                       │  └─────────────┘  └─────────────┘     │
              │  - Query caching                       │                       │  - Streaming replication              │
              │  - Session storage                     │                       │  - Auto-failover                      │
              │  - Rate limiting                       │                       │  - Connection pooling                 │
              └───────────────────────────────────────┘                       └───────────────────────────────────────┘

                                    ┌─────────────────────────────────────────────────────────────┐
                                    │                 MONITORING STACK                             │
                                    │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐            │
                                    │  │ Prometheus  │ │   Grafana   │ │   Jaeger    │            │
                                    │  │  (9090)     │ │   (3000)    │ │  (16686)    │            │
                                    │  └─────────────┘ └─────────────┘ └─────────────┘            │
                                    │  ┌─────────────┐ ┌─────────────┐                            │
                                    │  │Alertmanager │ │Node Exporter│                            │
                                    │  │  (9093)     │ │   (9100)    │                            │
                                    │  └─────────────┘ └─────────────┘                            │
                                    └─────────────────────────────────────────────────────────────┘
```

## Core Components

### 1. API Service Layer

The API layer consists of horizontally scalable FastAPI instances, each running:

- **FastAPI Application**: REST API endpoints for Text2SQL operations
- **ML Model**: Snowflake Arctic-Text2SQL-R1-7B model (loaded once per instance)
- **ReAct Agent**: Multi-step reasoning with self-correction capabilities
- **In-memory Cache**: Per-instance caching for frequently used schemas

**Resource Requirements (per instance):**
| Resource | Minimum | Recommended | GPU-Enabled |
|----------|---------|-------------|-------------|
| CPU | 4 cores | 8 cores | 8 cores |
| Memory | 16GB | 32GB | 32GB |
| GPU | - | - | NVIDIA T4/A10 |
| Storage | 20GB | 50GB | 50GB |

### 2. Load Balancer

Nginx or AWS ALB handles request distribution with:

- **SSL/TLS Termination**: Offloads encryption from application servers
- **Health Checks**: Removes unhealthy instances from rotation
- **Request Routing**: Path-based routing for API versions
- **Rate Limiting**: Layer 7 rate limiting for abuse prevention
- **Connection Pooling**: Efficient connection reuse

### 3. Database Layer (PostgreSQL HA)

High-availability PostgreSQL cluster with:

- **Streaming Replication**: Real-time data synchronization
- **Auto-Failover**: Automatic promotion of replica on primary failure
- **Connection Pooling**: PgBouncer for efficient connection management
- **Read Replicas**: Query distribution for read-heavy workloads

### 4. Cache Layer (Redis)

Redis cluster provides:

- **Query Caching**: Cache SQL generation results by query hash
- **Schema Caching**: Cache database schemas for faster lookups
- **Session Storage**: JWT token and session management
- **Rate Limiting**: Per-user/IP rate limit tracking

### 5. Monitoring Stack

Comprehensive observability with:

- **Prometheus**: Metrics collection and alerting
- **Grafana**: Visualization and dashboards
- **Jaeger**: Distributed tracing
- **Alertmanager**: Alert routing and notification

## Deployment Patterns

### Docker Compose (Development/Staging)

```bash
# Development
docker-compose up -d

# Staging with monitoring
docker-compose -f docker-compose.yml \
               -f docker-compose.staging.yml \
               -f docker-compose.monitoring.yml up -d

# Production
docker-compose -f docker-compose.yml \
               -f docker-compose.prod.yml \
               -f docker-compose.lb.yml \
               -f docker-compose.db-ha.yml up -d
```

### Kubernetes (Production)

```bash
# Apply all manifests
kubectl apply -k deploy/kubernetes/overlays/production

# Or individual components
kubectl apply -f deploy/kubernetes/base/
kubectl apply -f deploy/kubernetes/overlays/production/
```

### Docker Swarm

```bash
# Initialize swarm
docker swarm init

# Deploy stack
docker stack deploy -c docker-compose.yml \
                    -c docker-compose.prod.yml \
                    arctic-text2sql
```

## Scaling Strategy

### Horizontal Scaling

API instances scale based on:

1. **CPU Utilization**: Target 70% average
2. **Memory Utilization**: Target 75% average
3. **Request Queue Length**: Target < 10 pending requests
4. **Response Latency**: P95 < 2 seconds

```yaml
# Kubernetes HPA example
spec:
  minReplicas: 2
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
```

### Vertical Scaling

When to scale vertically:

- ML model requires more GPU memory
- Complex queries exhausting per-instance resources
- Cache hit rates dropping due to memory pressure

## High Availability

### Multi-Zone Deployment

```
Zone A                     Zone B                     Zone C
┌──────────────────┐      ┌──────────────────┐      ┌──────────────────┐
│ API Instance 1   │      │ API Instance 2   │      │ API Instance 3   │
│ Redis Replica    │      │ Redis Replica    │      │ Redis Master     │
│ PG Replica       │      │ PG Primary       │      │ PG Replica       │
└──────────────────┘      └──────────────────┘      └──────────────────┘
```

### Failover Procedures

1. **API Instance Failure**: Load balancer removes from rotation (30s)
2. **Redis Master Failure**: Sentinel promotes replica (< 30s)
3. **PostgreSQL Primary Failure**: Patroni promotes replica (< 60s)

## Network Security

### Network Policies

```
Internet → CDN → LB → API (port 8000 only)
                   ↓
              Internal Network
              ├── Redis (port 6379)
              ├── PostgreSQL (port 5432)
              └── Monitoring (ports 9090, 3000, 16686)
```

### Firewall Rules

| Source | Destination | Port | Protocol | Purpose |
|--------|-------------|------|----------|---------|
| Internet | Load Balancer | 443 | HTTPS | API Access |
| Load Balancer | API Instances | 8000 | HTTP | Request Routing |
| API Instances | PostgreSQL | 5432 | TCP | Database |
| API Instances | Redis | 6379 | TCP | Cache |
| Monitoring | All Services | Various | TCP | Metrics Scraping |

## Disaster Recovery

### Backup Strategy

| Component | Frequency | Retention | Storage |
|-----------|-----------|-----------|---------|
| PostgreSQL | Hourly | 7 days | S3/GCS |
| PostgreSQL | Daily | 30 days | S3/GCS |
| Redis | 6 hours | 3 days | S3/GCS |
| Configs | On change | 90 days | Git |

### Recovery Time Objectives

| Scenario | RTO | RPO |
|----------|-----|-----|
| Single Instance Failure | < 1 min | 0 |
| Zone Failure | < 5 min | 0 |
| Region Failure | < 30 min | < 1 hour |
| Data Corruption | < 1 hour | < 1 hour |

## Performance Targets

### Service Level Objectives (SLOs)

| Metric | Target | Measurement |
|--------|--------|-------------|
| Availability | 99.9% | Uptime per month |
| Latency (P50) | < 500ms | End-to-end response |
| Latency (P95) | < 2s | End-to-end response |
| Error Rate | < 0.1% | 5xx responses |
| Throughput | > 100 req/s | Per instance |

### Capacity Planning

| Users | API Instances | Database | Redis | Total Memory |
|-------|---------------|----------|-------|--------------|
| 100 | 2 | 1 Primary | 1 Node | 48GB |
| 1,000 | 4 | 1P + 1R | 1 Node | 96GB |
| 10,000 | 8 | 1P + 2R | 3 Nodes | 192GB |
| 100,000 | 16+ | 1P + 4R | 6 Nodes | 384GB+ |

## Related Documentation

- [Load Balancing Configuration](./LOAD_BALANCING.md)
- [Database Replication Setup](./DATABASE_REPLICATION.md)
- [Auto-Scaling Configuration](./AUTO_SCALING.md)
- [CDN Configuration](./CDN_CONFIGURATION.md)
- [Runbooks](../runbooks/README.md)

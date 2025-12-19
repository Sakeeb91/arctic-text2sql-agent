# Load Balancing Configuration

## Overview

This document describes the load balancing setup for Arctic Text2SQL using Nginx as the primary load balancer. The configuration supports SSL termination, health checks, request routing, and upstream management.

## Architecture

```
                    ┌─────────────────┐
                    │    Internet     │
                    └────────┬────────┘
                             │ HTTPS (443)
                             ▼
                    ┌─────────────────┐
                    │     Nginx       │
                    │  Load Balancer  │
                    │                 │
                    │ - SSL Terminate │
                    │ - Health Check  │
                    │ - Rate Limit    │
                    │ - Route Request │
                    └────────┬────────┘
                             │ HTTP (8000)
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
       ┌───────────┐  ┌───────────┐  ┌───────────┐
       │  API #1   │  │  API #2   │  │  API #N   │
       │  :8000    │  │  :8000    │  │  :8000    │
       └───────────┘  └───────────┘  └───────────┘
```

## Nginx Configuration Files

### Directory Structure

```
deploy/nginx/
├── nginx.conf              # Main Nginx configuration
├── conf.d/
│   ├── upstream.conf       # Upstream server definitions
│   ├── ssl.conf            # SSL/TLS settings
│   ├── security.conf       # Security headers and policies
│   └── api.conf            # API routing rules
├── ssl/
│   ├── dhparam.pem         # DH parameters (generate locally)
│   └── README.md           # SSL certificate placement guide
└── scripts/
    └── generate-dhparam.sh # DH parameter generation script
```

## Configuration Details

### Main Configuration (nginx.conf)

Key settings for production:

```nginx
worker_processes auto;
worker_rlimit_nofile 65535;

events {
    worker_connections 4096;
    use epoll;
    multi_accept on;
}

http {
    # Performance
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    keepalive_timeout 65;
    keepalive_requests 1000;

    # Buffers
    client_body_buffer_size 16k;
    client_max_body_size 10m;

    # Timeouts
    proxy_connect_timeout 60s;
    proxy_send_timeout 60s;
    proxy_read_timeout 90s;

    # Logging
    log_format json_combined escape=json '{'
        '"time":"$time_iso8601",'
        '"remote_addr":"$remote_addr",'
        '"request":"$request",'
        '"status":$status,'
        '"body_bytes_sent":$body_bytes_sent,'
        '"request_time":$request_time,'
        '"upstream_response_time":"$upstream_response_time",'
        '"upstream_addr":"$upstream_addr"'
    '}';
}
```

### Upstream Configuration

Load balancing methods available:

| Method | Use Case | Configuration |
|--------|----------|---------------|
| Round Robin | Default, equal distribution | `upstream api {}` |
| Least Connections | Variable request duration | `least_conn;` |
| IP Hash | Session affinity | `ip_hash;` |
| Weighted | Mixed capacity servers | `server api1 weight=3;` |

```nginx
upstream arctic_api {
    least_conn;
    keepalive 32;

    server api-1:8000 weight=1 max_fails=3 fail_timeout=30s;
    server api-2:8000 weight=1 max_fails=3 fail_timeout=30s;
    server api-3:8000 weight=1 max_fails=3 fail_timeout=30s backup;
}
```

### Health Checks

Active health checks (requires Nginx Plus or open-source alternatives):

```nginx
upstream arctic_api {
    zone arctic_api 64k;

    server api-1:8000;
    server api-2:8000;

    # Health check configuration
    health_check interval=5s fails=3 passes=2;
    health_check_timeout 3s;
}
```

For open-source Nginx, use passive health checks:

```nginx
upstream arctic_api {
    server api-1:8000 max_fails=3 fail_timeout=30s;
    server api-2:8000 max_fails=3 fail_timeout=30s;
}
```

### SSL/TLS Configuration

Security-focused SSL settings:

```nginx
# SSL protocols and ciphers
ssl_protocols TLSv1.2 TLSv1.3;
ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256;
ssl_prefer_server_ciphers on;

# Session caching
ssl_session_cache shared:SSL:50m;
ssl_session_timeout 1d;
ssl_session_tickets off;

# OCSP Stapling
ssl_stapling on;
ssl_stapling_verify on;
resolver 8.8.8.8 8.8.4.4 valid=300s;

# DH Parameters
ssl_dhparam /etc/nginx/ssl/dhparam.pem;
```

### Rate Limiting

Rate limiting configuration:

```nginx
# Define rate limiting zones
limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;
limit_req_zone $http_authorization zone=auth_limit:10m rate=100r/s;
limit_conn_zone $binary_remote_addr zone=conn_limit:10m;

# Apply rate limits
location /api/ {
    limit_req zone=api_limit burst=20 nodelay;
    limit_conn conn_limit 10;

    proxy_pass http://arctic_api;
}
```

## Request Routing

### API Version Routing

```nginx
# API v1 routes
location /api/v1/ {
    proxy_pass http://arctic_api;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Request-ID $request_id;
}

# Health check (bypass rate limiting)
location /api/v1/health {
    proxy_pass http://arctic_api;
    limit_req off;
    limit_conn off;
}

# Metrics endpoint (internal only)
location /monitoring/metrics {
    allow 10.0.0.0/8;
    allow 172.16.0.0/12;
    deny all;
    proxy_pass http://arctic_api;
}
```

### WebSocket Support

For streaming responses:

```nginx
location /api/v1/query/stream {
    proxy_pass http://arctic_api;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_read_timeout 3600s;
}
```

## Deployment

### Using Docker Compose

```bash
# Start with load balancer
docker-compose -f docker-compose.yml \
               -f docker-compose.lb.yml up -d
```

### SSL Certificate Setup

1. **Let's Encrypt (Recommended)**:
   ```bash
   certbot certonly --webroot -w /var/www/certbot \
       -d api.text2sql.example.com
   ```

2. **Self-signed (Development)**:
   ```bash
   openssl req -x509 -nodes -days 365 \
       -newkey rsa:2048 \
       -keyout deploy/nginx/ssl/server.key \
       -out deploy/nginx/ssl/server.crt
   ```

### Testing Configuration

```bash
# Test Nginx configuration
docker exec arctic-nginx nginx -t

# Reload configuration without downtime
docker exec arctic-nginx nginx -s reload

# Check upstream status
curl http://localhost:8080/nginx_status
```

## Monitoring

### Key Metrics to Monitor

| Metric | Description | Alert Threshold |
|--------|-------------|-----------------|
| nginx_connections_active | Active connections | > 80% of limit |
| nginx_http_requests_total | Request rate | Baseline +50% |
| nginx_upstream_response_time | Backend latency | P95 > 2s |
| nginx_http_responses_5xx | Error rate | > 1% |

### Prometheus Metrics

Enable the stub_status module:

```nginx
location /nginx_status {
    stub_status on;
    allow 127.0.0.1;
    allow 10.0.0.0/8;
    deny all;
}
```

## Troubleshooting

### Common Issues

1. **502 Bad Gateway**
   - Check if API instances are running
   - Verify upstream configuration
   - Check health check settings

2. **504 Gateway Timeout**
   - Increase `proxy_read_timeout`
   - Check API response times
   - Verify network connectivity

3. **Connection Refused**
   - Verify port bindings
   - Check firewall rules
   - Confirm container networking

### Debug Commands

```bash
# Check Nginx error logs
docker logs arctic-nginx --tail 100

# Test upstream connectivity
docker exec arctic-nginx curl http://api-1:8000/api/v1/health

# Check active connections
docker exec arctic-nginx nginx -s status
```

## Scaling Considerations

### When to Scale

- **Horizontal**: Add more API instances when:
  - CPU utilization > 70%
  - Response times increasing
  - Queue depth growing

- **Vertical**: Increase Nginx resources when:
  - Connection limits reached
  - Worker processes saturated
  - Memory pressure detected

### Auto-Discovery

For dynamic backend discovery, consider:

- **Consul Template**: Auto-update upstream config
- **Kubernetes**: Use Ingress controller
- **Docker Swarm**: Built-in DNS discovery

## Related Documentation

- [Architecture Overview](./ARCHITECTURE.md)
- [Auto-Scaling Configuration](./AUTO_SCALING.md)
- [Deployment Runbook](../runbooks/DEPLOYMENT.md)

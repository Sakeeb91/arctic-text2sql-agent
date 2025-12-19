# CDN Configuration

## Overview

While Arctic Text2SQL is primarily an API service, CDN (Content Delivery Network) integration can benefit certain use cases such as caching API responses, serving documentation, and providing DDoS protection.

## Use Cases

| Use Case | Benefit | Cacheable |
|----------|---------|-----------|
| Schema Endpoints | Reduce DB queries | Yes (5-15 min TTL) |
| Health Checks | Edge availability | Yes (1 min TTL) |
| API Documentation | Fast global access | Yes (1 hour TTL) |
| Static Assets | Bandwidth savings | Yes (long TTL) |
| DDoS Protection | Security layer | N/A |

## Architecture

```
                    ┌─────────────────────────────────────────────────────┐
                    │                      Internet                        │
                    └─────────────────────────────────────────────────────┘
                                              │
                                              ▼
                    ┌─────────────────────────────────────────────────────┐
                    │                     CDN Edge                         │
                    │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐    │
                    │  │ Edge POP 1  │ │ Edge POP 2  │ │ Edge POP N  │    │
                    │  │ (US-East)   │ │ (EU-West)   │ │ (APAC)      │    │
                    │  └─────────────┘ └─────────────┘ └─────────────┘    │
                    │                                                      │
                    │  Features:                                           │
                    │  • DDoS protection                                   │
                    │  • SSL termination                                   │
                    │  • Response caching                                  │
                    │  • Request filtering                                 │
                    │  • Rate limiting                                     │
                    └─────────────────────────────────────────────────────┘
                                              │
                                              ▼
                    ┌─────────────────────────────────────────────────────┐
                    │                   Origin Servers                     │
                    │              (Arctic Text2SQL API)                   │
                    └─────────────────────────────────────────────────────┘
```

## CloudFlare Configuration

### Basic Setup

1. **Add Domain to CloudFlare**
   - Add `api.text2sql.example.com` to CloudFlare
   - Update nameservers at registrar

2. **Configure DNS**
   ```
   Type: A
   Name: api
   Content: <origin-ip>
   Proxy status: Proxied (orange cloud)
   ```

3. **SSL/TLS Settings**
   - Mode: Full (Strict)
   - Always Use HTTPS: On
   - Automatic HTTPS Rewrites: On

### Page Rules

```yaml
# Cache API Documentation
URL: api.text2sql.example.com/docs/*
Settings:
  - Cache Level: Cache Everything
  - Edge Cache TTL: 1 hour
  - Browser Cache TTL: 1 hour

# Cache Schema Endpoints (with short TTL)
URL: api.text2sql.example.com/api/v1/schema/*
Settings:
  - Cache Level: Cache Everything
  - Edge Cache TTL: 5 minutes
  - Cache by Device Type: Off

# Bypass Cache for Query Endpoints
URL: api.text2sql.example.com/api/v1/query*
Settings:
  - Cache Level: Bypass
  - Security Level: High

# Cache Health Checks
URL: api.text2sql.example.com/api/v1/health
Settings:
  - Cache Level: Cache Everything
  - Edge Cache TTL: 1 minute
```

### Cache Rules (Rules > Cache Rules)

```javascript
// Rule 1: Cache static documentation
if (http.request.uri.path matches "^/docs/") {
  cache: eligible
  edge_ttl: 3600
  browser_ttl: 3600
}

// Rule 2: Cache schema with validation
if (http.request.uri.path matches "^/api/v1/schema/") {
  cache: eligible
  edge_ttl: 300
  cache_key: {
    include_query_string: true
    include_headers: ["authorization"]
  }
}

// Rule 3: Bypass cache for mutations
if (http.request.method in {"POST" "PUT" "DELETE" "PATCH"}) {
  cache: bypass
}
```

### Security Rules

```javascript
// Rate limiting rule
if (http.request.uri.path matches "^/api/v1/query") {
  rate_limit: {
    period: 60
    requests: 30
    action: challenge
  }
}

// Block known bad actors
if (ip.geoip.country in {"XX" "YY"} and http.request.uri.path matches "^/api/") {
  action: block
}

// Challenge suspicious requests
if (cf.threat_score > 10) {
  action: managed_challenge
}
```

### Transform Rules

```javascript
// Add security headers
add_response_header: {
  "X-Content-Type-Options": "nosniff"
  "X-Frame-Options": "DENY"
  "X-XSS-Protection": "1; mode=block"
  "Strict-Transport-Security": "max-age=31536000; includeSubDomains"
}

// Add cache status header for debugging
add_response_header: {
  "X-Cache-Status": cf.cache.status
}
```

## AWS CloudFront Configuration

### Distribution Settings

```yaml
# CloudFormation template
AWSTemplateFormatVersion: '2010-09-09'
Resources:
  APIDistribution:
    Type: AWS::CloudFront::Distribution
    Properties:
      DistributionConfig:
        Origins:
          - DomainName: origin.text2sql.example.com
            Id: APIOrigin
            CustomOriginConfig:
              HTTPSPort: 443
              OriginProtocolPolicy: https-only
              OriginSSLProtocols:
                - TLSv1.2

        DefaultCacheBehavior:
          TargetOriginId: APIOrigin
          ViewerProtocolPolicy: redirect-to-https
          AllowedMethods:
            - GET
            - HEAD
            - OPTIONS
            - PUT
            - POST
            - PATCH
            - DELETE
          CachedMethods:
            - GET
            - HEAD
          CachePolicyId: !Ref APICachePolicy
          OriginRequestPolicyId: !Ref APIOriginRequestPolicy

        CacheBehaviors:
          # Cache schema endpoints
          - PathPattern: /api/v1/schema/*
            TargetOriginId: APIOrigin
            ViewerProtocolPolicy: https-only
            AllowedMethods: [GET, HEAD, OPTIONS]
            CachePolicyId: !Ref SchemaCachePolicy
            TTL:
              DefaultTTL: 300
              MaxTTL: 600

          # Cache health checks
          - PathPattern: /api/v1/health
            TargetOriginId: APIOrigin
            ViewerProtocolPolicy: https-only
            AllowedMethods: [GET, HEAD]
            CachePolicyId: !Ref HealthCachePolicy
            TTL:
              DefaultTTL: 60
              MaxTTL: 60

        PriceClass: PriceClass_100  # US, Canada, Europe
        Enabled: true
        HttpVersion: http2and3
        ViewerCertificate:
          AcmCertificateArn: !Ref SSLCertificate
          SslSupportMethod: sni-only
          MinimumProtocolVersion: TLSv1.2_2021

  # Cache policy for API calls (no caching by default)
  APICachePolicy:
    Type: AWS::CloudFront::CachePolicy
    Properties:
      CachePolicyConfig:
        Name: arctic-text2sql-api
        DefaultTTL: 0
        MaxTTL: 0
        MinTTL: 0
        ParametersInCacheKeyAndForwardedToOrigin:
          EnableAcceptEncodingGzip: true
          HeadersConfig:
            HeaderBehavior: whitelist
            Headers:
              - Authorization
              - Content-Type
          QueryStringsConfig:
            QueryStringBehavior: all

  # Cache policy for schema endpoints
  SchemaCachePolicy:
    Type: AWS::CloudFront::CachePolicy
    Properties:
      CachePolicyConfig:
        Name: arctic-text2sql-schema
        DefaultTTL: 300
        MaxTTL: 600
        MinTTL: 60
        ParametersInCacheKeyAndForwardedToOrigin:
          EnableAcceptEncodingGzip: true
          HeadersConfig:
            HeaderBehavior: none
          QueryStringsConfig:
            QueryStringBehavior: all
```

### Lambda@Edge for Custom Logic

```javascript
// viewer-request.js - Add custom headers
exports.handler = async (event) => {
    const request = event.Records[0].cf.request;

    // Add request ID for tracing
    request.headers['x-request-id'] = [{
        key: 'X-Request-Id',
        value: `cdn-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`
    }];

    return request;
};

// origin-response.js - Add cache headers
exports.handler = async (event) => {
    const response = event.Records[0].cf.response;

    // Add security headers
    response.headers['strict-transport-security'] = [{
        key: 'Strict-Transport-Security',
        value: 'max-age=31536000; includeSubDomains'
    }];

    response.headers['x-content-type-options'] = [{
        key: 'X-Content-Type-Options',
        value: 'nosniff'
    }];

    return response;
};
```

## Cache Invalidation

### Manual Invalidation

```bash
# CloudFlare
curl -X POST "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}/purge_cache" \
    -H "Authorization: Bearer ${CF_API_TOKEN}" \
    -H "Content-Type: application/json" \
    --data '{"files":["https://api.text2sql.example.com/api/v1/schema/*"]}'

# AWS CloudFront
aws cloudfront create-invalidation \
    --distribution-id ${DISTRIBUTION_ID} \
    --paths "/api/v1/schema/*"
```

### Programmatic Invalidation

Integrate cache invalidation into deployment:

```python
# deploy/scripts/invalidate_cache.py
import boto3
import requests
import os

def invalidate_cloudfront(paths: list[str]):
    """Invalidate CloudFront cache after deployment."""
    client = boto3.client('cloudfront')
    distribution_id = os.environ['CLOUDFRONT_DISTRIBUTION_ID']

    response = client.create_invalidation(
        DistributionId=distribution_id,
        InvalidationBatch={
            'Paths': {
                'Quantity': len(paths),
                'Items': paths
            },
            'CallerReference': str(time.time())
        }
    )
    return response['Invalidation']['Id']

def invalidate_cloudflare(paths: list[str]):
    """Purge CloudFlare cache after deployment."""
    zone_id = os.environ['CF_ZONE_ID']
    api_token = os.environ['CF_API_TOKEN']

    response = requests.post(
        f'https://api.cloudflare.com/client/v4/zones/{zone_id}/purge_cache',
        headers={'Authorization': f'Bearer {api_token}'},
        json={'files': paths}
    )
    return response.json()
```

## Monitoring CDN Performance

### Key Metrics

| Metric | Description | Target |
|--------|-------------|--------|
| Cache Hit Ratio | % requests served from cache | > 80% for static |
| Origin Response Time | Time to fetch from origin | < 500ms |
| Edge Response Time | Time to serve from edge | < 50ms |
| Bandwidth Savings | Data served from cache | > 60% |
| Error Rate | 4xx/5xx from CDN | < 0.1% |

### CloudFlare Analytics

```bash
# Get cache analytics
curl -X GET "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}/analytics/dashboard" \
    -H "Authorization: Bearer ${CF_API_TOKEN}"
```

### CloudFront Metrics

```bash
# Enable real-time logs
aws cloudfront create-realtime-log-config \
    --name arctic-text2sql-logs \
    --end-points '...' \
    --fields 'timestamp,c-ip,cs-uri-stem,sc-status,x-edge-result-type'
```

## Best Practices

1. **Cache Key Design**
   - Include only necessary query parameters
   - Consider user-specific data in cache key
   - Avoid cache pollution with unique URLs

2. **TTL Strategy**
   - Short TTL for dynamic data (1-5 min)
   - Long TTL for static assets (1 hour+)
   - Use stale-while-revalidate when possible

3. **Origin Protection**
   - Use origin shield (single cache layer)
   - Rate limit at CDN edge
   - Block malicious traffic before it reaches origin

4. **Monitoring**
   - Set up alerts for cache hit ratio drops
   - Monitor origin error rates
   - Track bandwidth costs

## Related Documentation

- [Architecture Overview](./ARCHITECTURE.md)
- [Load Balancing Configuration](./LOAD_BALANCING.md)
- [Security Configuration](./SECURITY.md)

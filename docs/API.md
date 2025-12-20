# API Reference

Complete API documentation for Text2SQL Agent.

## Base URL

```
http://localhost:8000/api/v1
```

## Interactive Documentation

When the server is running, visit:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

---

## Core Endpoints

### Generate SQL

Convert natural language to SQL with optional execution.

```http
POST /api/v1/query
```

**Request Body:**
```json
{
    "query": "Show me all customers from California",
    "database_id": "my_database",
    "execute": true,
    "show_reasoning": true,
    "max_rows": 100
}
```

**Response:**
```json
{
    "sql": "SELECT * FROM customers WHERE state = 'California'",
    "confidence": 0.95,
    "execution_time_ms": 1823,
    "dialect": "postgresql",
    "valid_syntax": true,
    "validation_status": "validated",
    "results": [...],
    "reasoning_trace": [
        {
            "step": 1,
            "thought": "Need to filter customers by state",
            "action": "sql_engine",
            "observation": "Query executed successfully"
        }
    ]
}
```

### Batch Query

Process multiple queries in one request.

```http
POST /api/v1/query/batch
```

### Stream Query

Stream SQL generation results in real-time.

```http
POST /api/v1/query/stream
```

### Validate SQL

Validate SQL syntax and semantics without execution.

```http
POST /api/v1/validate
```

---

## Schema Endpoints

### Get Schema

```http
GET /api/v1/schema/{database_id}
```

### Register Schema

```http
POST /api/v1/schema/register
```

---

## Agent Endpoints

### Get Reasoning Trace

Retrieve detailed reasoning for a specific query.

```http
GET /api/v1/agent/reasoning/{query_id}
```

### Retry Query

Retry a failed query with correction hints.

```http
POST /api/v1/agent/retry
```

---

## Database Management

### Register Database

```http
POST /api/v1/databases
```

**Request Body:**
```json
{
    "database_id": "analytics",
    "connection_string": "postgresql://user:pass@host/db",
    "display_name": "Analytics Database",
    "pool_size": 10
}
```

### List Databases

```http
GET /api/v1/databases
```

### Get Database Details

```http
GET /api/v1/databases/{database_id}
```

### Check Database Health

```http
GET /api/v1/databases/{database_id}/health
```

### Delete Database

```http
DELETE /api/v1/databases/{database_id}
```

### Health Check All

```http
GET /api/v1/databases/health/all
```

---

## Explanation and Visualization

### Explain SQL

Generate natural language explanation of a SQL query.

```http
POST /api/v1/explain
```

### Visualize Query

Generate query structure visualization.

```http
POST /api/v1/visualize
```

### Get Cached Explanation

```http
GET /api/v1/explain/{query_id}
```

### Batch Explain

```http
POST /api/v1/explain/batch
```

---

## Few-Shot Learning

### Add Example

```http
POST /api/v1/examples
```

### Search Examples

```http
POST /api/v1/examples/search
```

### List Examples

```http
GET /api/v1/examples
```

### Get/Update/Delete Example

```http
GET /api/v1/examples/{example_id}
PATCH /api/v1/examples/{example_id}
DELETE /api/v1/examples/{example_id}
```

---

## Feedback

### Submit Feedback

```http
POST /api/v1/feedback
```

### List Feedback

```http
GET /api/v1/feedback
```

### Get Feedback

```http
GET /api/v1/feedback/{feedback_id}
```

### Update Feedback Status

```http
PATCH /api/v1/feedback/{feedback_id}/status
```

---

## Model Versioning

### List Versions

```http
GET /api/v1/models/versions
```

### Get Active Version

```http
GET /api/v1/models/versions/active
```

### Register Version

```http
POST /api/v1/models/versions
```

### Activate Version

```http
POST /api/v1/models/versions/{version_id}/activate
```

---

## Management

### Health Check

```http
GET /api/v1/health
```

### Model Info

```http
GET /api/v1/models/info
```

### Prometheus Metrics

```http
GET /monitoring/metrics
```

### Cache Stats

```http
GET /api/v1/cache/stats
```

### Invalidate Cache

```http
POST /api/v1/cache/invalidate
```

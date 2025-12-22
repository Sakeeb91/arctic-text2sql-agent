# Workflow Guide

A practical guide for integrating the Text2SQL Agent into your applications and workflows.

---

## Table of Contents

- [Overview](#overview)
- [Authentication Setup](#authentication-setup)
- [Basic Query Workflow](#basic-query-workflow)
- [Streaming Workflow](#streaming-workflow)
- [Multi-Database Workflow](#multi-database-workflow)
- [Batch Processing Workflow](#batch-processing-workflow)
- [Error Handling & Retry](#error-handling--retry)
- [Integration Patterns](#integration-patterns)
- [Best Practices](#best-practices)

---

## Overview

The Text2SQL Agent converts natural language questions into SQL queries using a multi-step reasoning process. The typical workflow is:

```
1. Authenticate (JWT or API key)
2. Register database(s) if using multi-db
3. Send natural language query
4. Receive SQL + optional execution results
5. Handle errors/retries as needed
```

---

## Authentication Setup

All API endpoints (except `/api/v1/health`) require authentication.

### Option 1: API Key (Recommended for Services)

```bash
# Set in environment
API_KEYS=your-api-key-here:read,write

# Use in requests
curl -X POST http://localhost:8000/api/v1/query \
  -H "X-API-Key: your-api-key-here" \
  -H "Content-Type: application/json" \
  -d '{"query": "Show all users", "database_id": "default"}'
```

### Option 2: JWT Token (Recommended for Users)

```bash
# 1. Get a token
curl -X POST http://localhost:8000/api/v1/auth/token \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "your-password"}'

# Response: {"access_token": "eyJ...", "token_type": "bearer"}

# 2. Use the token
curl -X POST http://localhost:8000/api/v1/query \
  -H "Authorization: Bearer eyJ..." \
  -H "Content-Type: application/json" \
  -d '{"query": "Show all users", "database_id": "default"}'
```

### Python Authentication Helper

```python
import requests
from dataclasses import dataclass

@dataclass
class Text2SQLClient:
    base_url: str
    api_key: str | None = None
    token: str | None = None

    @property
    def headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        elif self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def query(self, question: str, database_id: str = "default", execute: bool = True) -> dict:
        response = requests.post(
            f"{self.base_url}/api/v1/query",
            headers=self.headers,
            json={
                "query": question,
                "database_id": database_id,
                "execute": execute,
                "show_reasoning": True,
            },
        )
        response.raise_for_status()
        return response.json()

# Usage
client = Text2SQLClient(
    base_url="http://localhost:8000",
    api_key="your-api-key",
)
result = client.query("Show me top 10 customers by revenue")
print(result["sql"])
```

---

## Basic Query Workflow

### Step 1: Send a Query

```python
import requests

response = requests.post(
    "http://localhost:8000/api/v1/query",
    headers={"X-API-Key": "your-key"},
    json={
        "query": "Which products have sales over $1000?",
        "database_id": "default",
        "execute": True,
        "show_reasoning": True,
        "max_rows": 100,
    },
)
result = response.json()
```

### Step 2: Process the Response

```python
# Check confidence level
if result["confidence"] < 0.7:
    print("Warning: Low confidence query")

# Access the generated SQL
sql = result["sql"]
print(f"Generated SQL: {sql}")

# Access execution results (if execute=True)
if "results" in result:
    for row in result["results"]:
        print(row)

# Review reasoning trace (if show_reasoning=True)
if "reasoning_trace" in result:
    for step in result["reasoning_trace"]:
        print(f"Step {step['step']}: {step['thought']}")
```

### Step 3: Validate Before Production Use

```python
# Validate SQL without executing
validation = requests.post(
    "http://localhost:8000/api/v1/validate",
    headers={"X-API-Key": "your-key"},
    json={
        "sql": result["sql"],
        "database_id": "default",
    },
)
val_result = validation.json()

if val_result["valid"]:
    print("SQL is valid and safe to execute")
else:
    print(f"Validation errors: {val_result['errors']}")
    print(f"Warnings: {val_result['warnings']}")
```

---

## Streaming Workflow

For long-running queries or real-time feedback, use the streaming endpoint.

### Server-Sent Events (SSE) Client

```python
import json
import sseclient  # pip install sseclient-py
import requests

def stream_query(question: str, database_id: str = "default"):
    response = requests.post(
        "http://localhost:8000/api/v1/query/stream",
        headers={
            "X-API-Key": "your-key",
            "Accept": "text/event-stream",
        },
        json={
            "query": question,
            "database_id": database_id,
            "execute": True,
            "show_reasoning": True,
        },
        stream=True,
    )

    client = sseclient.SSEClient(response)

    for event in client.events():
        data = json.loads(event.data)
        event_type = data.get("event")

        if event_type == "reasoning_step":
            step = data["data"]
            print(f"[Step {step['step']}] {step['thought']}")

        elif event_type == "sql_generated":
            sql_data = data["data"]
            print(f"\nGenerated SQL: {sql_data['sql']}")
            print(f"Confidence: {sql_data['confidence']}")

        elif event_type == "result_batch":
            rows = data["data"]["rows"]
            print(f"\nReceived {len(rows)} rows...")
            for row in rows:
                print(row)

        elif event_type == "query_complete":
            print("\nQuery completed!")
            break

        elif event_type == "query_error":
            print(f"\nError: {data['data']['error']}")
            break

# Usage
stream_query("Show me monthly sales trends for 2024")
```

### JavaScript/TypeScript Client

```typescript
async function streamQuery(question: string, databaseId: string = "default") {
  const response = await fetch("http://localhost:8000/api/v1/query/stream", {
    method: "POST",
    headers: {
      "X-API-Key": "your-key",
      "Content-Type": "application/json",
      "Accept": "text/event-stream",
    },
    body: JSON.stringify({
      query: question,
      database_id: databaseId,
      execute: true,
      show_reasoning: true,
    }),
  });

  const reader = response.body?.getReader();
  const decoder = new TextDecoder();

  while (reader) {
    const { done, value } = await reader.read();
    if (done) break;

    const chunk = decoder.decode(value);
    const lines = chunk.split("\n");

    for (const line of lines) {
      if (line.startsWith("data:")) {
        const data = JSON.parse(line.slice(5));
        console.log(`Event: ${data.event}`, data.data);
      }
    }
  }
}
```

---

## Multi-Database Workflow

Connect to multiple databases and route queries dynamically.

### Step 1: Enable Multi-Database Mode

```bash
# In .env
MULTIDB_ENABLED=true
MULTIDB_REQUIRE_CONNECTION_TEST=true
MULTIDB_MAX_DATABASES=50
```

### Step 2: Register Databases

```python
import requests

# Register analytics database
requests.post(
    "http://localhost:8000/api/v1/schema/register",
    headers={"X-API-Key": "your-key"},
    json={
        "database_id": "analytics",
        "connection_string": "postgresql://user:pass@analytics-db:5432/warehouse",
        "dialect": "postgresql",
    },
)

# Register CRM database
requests.post(
    "http://localhost:8000/api/v1/schema/register",
    headers={"X-API-Key": "your-key"},
    json={
        "database_id": "crm",
        "connection_string": "mysql://user:pass@crm-db:3306/customers",
        "dialect": "mysql",
    },
)
```

### Step 3: Query Specific Databases

```python
# Query analytics database
analytics_result = requests.post(
    "http://localhost:8000/api/v1/query",
    headers={"X-API-Key": "your-key"},
    json={
        "query": "Show daily active users this month",
        "database_id": "analytics",  # Route to analytics
        "execute": True,
    },
).json()

# Query CRM database
crm_result = requests.post(
    "http://localhost:8000/api/v1/query",
    headers={"X-API-Key": "your-key"},
    json={
        "query": "Find customers who haven't ordered in 90 days",
        "database_id": "crm",  # Route to CRM
        "execute": True,
    },
).json()
```

### Step 4: Check Database Health

```python
# Check all databases
health = requests.get(
    "http://localhost:8000/api/v1/databases/health/all",
    headers={"X-API-Key": "your-key"},
).json()

for db_id, status in health.items():
    print(f"{db_id}: {status['status']} ({status['latency_ms']}ms)")
```

---

## Batch Processing Workflow

Process multiple queries efficiently.

### Batch Query Request

```python
import requests

queries = [
    "Total revenue by region",
    "Top 5 products by quantity sold",
    "Customer churn rate this quarter",
    "Average order value by customer segment",
]

response = requests.post(
    "http://localhost:8000/api/v1/query/batch",
    headers={"X-API-Key": "your-key"},
    json={
        "queries": [{"query": q, "database_id": "default"} for q in queries],
        "execute": False,  # Just generate SQL
    },
)

results = response.json()

for i, result in enumerate(results["results"]):
    print(f"\nQuery: {queries[i]}")
    print(f"SQL: {result['sql']}")
    print(f"Confidence: {result['confidence']}")
```

### Parallel Processing with asyncio

```python
import asyncio
import aiohttp

async def query_async(session: aiohttp.ClientSession, question: str) -> dict:
    async with session.post(
        "http://localhost:8000/api/v1/query",
        headers={"X-API-Key": "your-key"},
        json={"query": question, "database_id": "default", "execute": False},
    ) as response:
        return await response.json()

async def batch_query(questions: list[str]) -> list[dict]:
    async with aiohttp.ClientSession() as session:
        tasks = [query_async(session, q) for q in questions]
        return await asyncio.gather(*tasks)

# Usage
questions = [
    "Total sales by month",
    "Top customers by lifetime value",
    "Product inventory levels",
]
results = asyncio.run(batch_query(questions))
```

---

## Error Handling & Retry

### Handling Common Errors

```python
import requests
from requests.exceptions import HTTPError
import time

def query_with_retry(question: str, max_retries: int = 3) -> dict:
    for attempt in range(max_retries):
        try:
            response = requests.post(
                "http://localhost:8000/api/v1/query",
                headers={"X-API-Key": "your-key"},
                json={
                    "query": question,
                    "database_id": "default",
                    "execute": True,
                },
                timeout=30,
            )
            response.raise_for_status()
            return response.json()

        except HTTPError as e:
            status = e.response.status_code

            if status == 401:
                raise ValueError("Authentication failed - check API key")

            elif status == 429:
                # Rate limited - wait and retry
                retry_after = int(e.response.headers.get("Retry-After", 60))
                print(f"Rate limited. Waiting {retry_after}s...")
                time.sleep(retry_after)

            elif status == 422:
                # Validation error - don't retry
                error_detail = e.response.json()
                raise ValueError(f"Validation error: {error_detail}")

            elif status >= 500:
                # Server error - retry with backoff
                wait_time = 2 ** attempt
                print(f"Server error. Retrying in {wait_time}s...")
                time.sleep(wait_time)

            else:
                raise

        except requests.Timeout:
            print(f"Timeout on attempt {attempt + 1}")
            time.sleep(2 ** attempt)

    raise Exception("Max retries exceeded")
```

### Using the Retry Endpoint

If a query fails validation or produces incorrect results, use the retry endpoint with hints:

```python
# Original query returned incorrect SQL
original_result = query("Show users who signed up last week")

# Retry with correction hints
retry_response = requests.post(
    "http://localhost:8000/api/v1/agent/retry",
    headers={"X-API-Key": "your-key"},
    json={
        "query_id": original_result["query_id"],
        "hint": "The created_at column is in UTC, adjust for local timezone",
    },
)
corrected_result = retry_response.json()
```

---

## Integration Patterns

### Pattern 1: Data Pipeline Integration

```python
# Apache Airflow DAG example
from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime

def generate_report_sql():
    client = Text2SQLClient(base_url="http://text2sql:8000", api_key="...")

    queries = [
        "Daily active users by platform",
        "Revenue by product category",
        "Customer acquisition cost by channel",
    ]

    sql_statements = []
    for q in queries:
        result = client.query(q, execute=False)
        if result["confidence"] >= 0.8:
            sql_statements.append(result["sql"])

    return sql_statements

dag = DAG("text2sql_reports", start_date=datetime(2024, 1, 1))

generate_task = PythonOperator(
    task_id="generate_sql",
    python_callable=generate_report_sql,
    dag=dag,
)
```

### Pattern 2: Chatbot Integration

```python
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()
client = Text2SQLClient(base_url="http://text2sql:8000", api_key="...")

class ChatMessage(BaseModel):
    message: str
    session_id: str

@app.post("/chat")
async def chat(msg: ChatMessage):
    # Detect if message is a data question
    if is_data_question(msg.message):
        result = client.query(msg.message, execute=True, show_reasoning=True)

        return {
            "response": format_results_as_text(result["results"]),
            "sql": result["sql"],
            "confidence": result["confidence"],
            "reasoning": result.get("reasoning_trace"),
        }
    else:
        return {"response": handle_general_chat(msg.message)}
```

### Pattern 3: BI Tool Integration

```python
# Metabase/Superset integration via custom data source
class Text2SQLDataSource:
    def __init__(self, api_url: str, api_key: str, database_id: str):
        self.client = Text2SQLClient(base_url=api_url, api_key=api_key)
        self.database_id = database_id

    def execute_natural_query(self, question: str) -> pd.DataFrame:
        result = self.client.query(
            question,
            database_id=self.database_id,
            execute=True,
        )

        if result.get("results"):
            return pd.DataFrame(result["results"])
        return pd.DataFrame()

    def get_sql(self, question: str) -> str:
        result = self.client.query(
            question,
            database_id=self.database_id,
            execute=False,
        )
        return result["sql"]
```

### Pattern 4: Slack Bot Integration

```python
from slack_bolt import App

app = App(token="xoxb-...")
client = Text2SQLClient(base_url="http://text2sql:8000", api_key="...")

@app.message(re.compile(r"^data:\s*(.+)$"))
def handle_data_query(message, say, context):
    question = context["matches"][0]

    # Send thinking message
    say("Analyzing your question...")

    try:
        result = client.query(question, execute=True)

        # Format response
        response = f"*Query:* {question}\n"
        response += f"*SQL:* ```{result['sql']}```\n"
        response += f"*Confidence:* {result['confidence']:.0%}\n"

        if result.get("results"):
            response += f"*Results:* {len(result['results'])} rows\n"
            # Format first few rows as table
            response += format_slack_table(result["results"][:5])

        say(response)

    except Exception as e:
        say(f"Error: {str(e)}")
```

---

## Best Practices

### 1. Validate Before Executing in Production

```python
# Always validate generated SQL before running against production
result = client.query(question, execute=False)

validation = client.validate(result["sql"], database_id)
if validation["valid"] and result["confidence"] >= 0.8:
    # Safe to execute
    execution_result = client.execute(result["sql"], database_id)
```

### 2. Use Appropriate Confidence Thresholds

| Use Case | Minimum Confidence |
|----------|-------------------|
| Auto-execute (internal dashboards) | 0.9+ |
| Human review before execution | 0.7+ |
| Suggestion only | 0.5+ |
| Reject query | < 0.5 |

### 3. Leverage Caching

```python
# Use consistent query phrasing for cache hits
# Bad: Different phrasing = cache miss
"show me users"
"Show me the users"
"list all users"

# Good: Consistent canonical phrasing
"List all users from the users table"
```

### 4. Monitor and Log

```python
import structlog

logger = structlog.get_logger()

def query_with_logging(question: str) -> dict:
    start = time.time()

    result = client.query(question)

    logger.info(
        "text2sql_query",
        question=question,
        sql=result["sql"],
        confidence=result["confidence"],
        duration_ms=(time.time() - start) * 1000,
        cached=result.get("cached", False),
    )

    return result
```

### 5. Handle Schema Changes

```python
# Invalidate cache when schema changes
def on_schema_migration():
    requests.post(
        "http://localhost:8000/api/v1/cache/invalidate",
        headers={"X-API-Key": "admin-key"},
        json={"namespace": "schema", "database_id": "default"},
    )
```

### 6. Set Appropriate Timeouts

```python
# Short timeout for interactive queries
response = requests.post(url, json=data, timeout=10)

# Longer timeout for complex analytical queries
response = requests.post(url, json=complex_data, timeout=60)

# Use streaming for very long queries
# (no timeout issues, progressive results)
stream_query(complex_question)
```

---

## Quick Reference

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `API_KEYS` | Comma-separated API keys with scopes | - |
| `AUTH_USERS` | User credentials for JWT auth | - |
| `MULTIDB_ENABLED` | Enable multi-database routing | `false` |
| `AGENT_MIN_CONFIDENCE` | Minimum confidence threshold | `0.7` |
| `CACHE_ENABLED` | Enable query/schema caching | `true` |
| `CACHE_TTL` | Cache time-to-live (seconds) | `3600` |

### Common HTTP Status Codes

| Code | Meaning | Action |
|------|---------|--------|
| 200 | Success | Process result |
| 401 | Unauthorized | Check API key/token |
| 422 | Validation Error | Fix request body |
| 429 | Rate Limited | Wait and retry |
| 500 | Server Error | Retry with backoff |

### Useful Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/query` | POST | Generate + execute SQL |
| `/api/v1/query/stream` | POST | Stream results (SSE) |
| `/api/v1/query/batch` | POST | Batch processing |
| `/api/v1/validate` | POST | Validate SQL |
| `/api/v1/schema/{db_id}` | GET | Get schema info |
| `/api/v1/databases` | GET | List databases |
| `/api/v1/health` | GET | Health check |

---

## Next Steps

- [API Reference](API.md) - Complete endpoint documentation
- [Configuration](CONFIGURATION.md) - All environment variables
- [Troubleshooting](TROUBLESHOOTING.md) - Common issues and solutions
- [Development](DEVELOPMENT.md) - Contributing guide

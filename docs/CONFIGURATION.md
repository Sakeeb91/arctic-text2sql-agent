# Configuration

All configuration is done via environment variables. Copy `.env.example` to `.env` and customize.

## Required Variables

| Variable | Description |
|----------|-------------|
| `HUGGINGFACE_TOKEN` | Your HuggingFace API token |
| `DATABASE_URL` | Database connection string |

## HuggingFace Settings

```env
# Your HuggingFace token (get from https://huggingface.co/settings/tokens)
HUGGINGFACE_TOKEN=hf_xxxxx

# Model to use for SQL generation
TEXT2SQL_MODEL=Qwen/Qwen2.5-Coder-7B-Instruct
```

### Recommended Models

| Model | Size | Best For |
|-------|------|----------|
| `Qwen/Qwen2.5-Coder-7B-Instruct` | 7B | General SQL (recommended) |
| `Qwen/Qwen2.5-Coder-32B-Instruct` | 32B | Complex queries |
| `meta-llama/Llama-3.2-3B-Instruct` | 3B | Fast responses |
| `deepseek-ai/DeepSeek-R1-Distill-Qwen-32B` | 32B | Advanced reasoning |

## Inference Backend

### Option 1: HuggingFace Inference API (Recommended)

Uses HuggingFace's hosted inference. Free tier available.

```env
AGENT_MODEL_BACKEND=hf_inference
AGENT_INFERENCE_PROVIDER=         # Leave empty for auto-routing
AGENT_INFERENCE_TIMEOUT=120
AGENT_USE_LEGACY_FALLBACK=false
```

**Important**: Do NOT set `AGENT_INFERENCE_PROVIDER=hf-inference` - that is not a valid provider name. Leave it empty or use specific providers like `nebius`, `together`, `fireworks`.

### Option 2: Local Inference

Runs the model on your machine. Requires GPU for reasonable performance.

```env
AGENT_MODEL_BACKEND=local
MODEL_DEVICE=cuda                 # cuda, cpu, mps, or auto
ENABLE_8BIT_QUANTIZATION=false    # Reduces memory usage
ENABLE_4BIT_QUANTIZATION=false    # Maximum compression
```

## Database Settings

```env
# Connection string (supports PostgreSQL, MySQL, SQLite)
DATABASE_URL=postgresql://user:password@localhost:5432/mydb

# Connection pool
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=10
DB_POOL_TIMEOUT=30
```

### Connection String Examples

```env
# PostgreSQL
DATABASE_URL=postgresql://user:pass@localhost:5432/dbname

# MySQL
DATABASE_URL=mysql://user:pass@localhost:3306/dbname

# SQLite
DATABASE_URL=sqlite:///./data/app.db

# PostgreSQL with SSL (Neon, Supabase, etc.)
DATABASE_URL=postgresql://user:pass@host.neon.tech/db?sslmode=require
```

## Agent Settings

```env
AGENT_ENABLED=true                # Enable the agent
AGENT_MAX_STEPS=5                 # Max reasoning steps (3-5 recommended)
AGENT_MIN_CONFIDENCE=0.7          # Minimum confidence threshold
AGENT_ENABLE_VALIDATION=true      # Validate SQL before returning
AGENT_EXECUTION_TIMEOUT=30        # Query execution timeout (seconds)
```

## API Settings

```env
API_HOST=0.0.0.0
API_PORT=8000
API_DEBUG=false

# CORS (comma-separated origins)
CORS_ORIGINS=http://localhost:3000,http://localhost:8080
```

## Security Settings

```env
SECRET_KEY=your-secret-key-here   # For JWT tokens
RATE_LIMIT_PER_MINUTE=60
RATE_LIMIT_BURST=10
```

## Monitoring Settings

```env
ENABLE_METRICS=true
METRICS_PORT=9090
ENABLE_TRACING=false
OTLP_ENDPOINT=http://localhost:4317
```

## Multi-Database Support

```env
MULTIDB_ENABLED=true
MULTIDB_MAX_DATABASES=50
MULTIDB_DEFAULT_POOL_SIZE=5
MULTIDB_HEALTH_CHECK_INTERVAL=60
```

## Few-Shot Learning

```env
FEWSHOT_ENABLED=true
FEWSHOT_EMBEDDING_STRATEGY=hash
```

## Example Complete Configuration

```env
# Required
HUGGINGFACE_TOKEN=hf_xxxxx
DATABASE_URL=postgresql://user:pass@localhost:5432/mydb

# Inference (HF API - recommended)
TEXT2SQL_MODEL=Qwen/Qwen2.5-Coder-7B-Instruct
AGENT_MODEL_BACKEND=hf_inference
AGENT_INFERENCE_PROVIDER=
AGENT_INFERENCE_TIMEOUT=120

# Agent
AGENT_ENABLED=true
AGENT_MAX_STEPS=5
AGENT_MIN_CONFIDENCE=0.7

# API
API_HOST=0.0.0.0
API_PORT=8000
```

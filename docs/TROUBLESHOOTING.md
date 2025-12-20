# Troubleshooting

## Common Issues

### HuggingFace Authentication

**Issue**: Model download fails or 401 errors

```bash
# Solution: Set your HuggingFace token
export HUGGINGFACE_TOKEN=hf_xxxxx
```

Get your token from: https://huggingface.co/settings/tokens

---

### HF Inference API Returns 404

**Issue**: `404 Not Found for url: https://router.huggingface.co/hf-inference/...`

**Cause**: Invalid provider name `hf-inference`

**Solution**: Leave `AGENT_INFERENCE_PROVIDER` empty for auto-routing:

```env
AGENT_INFERENCE_PROVIDER=         # Empty, NOT 'hf-inference'
```

Valid provider names: `nebius`, `together`, `fireworks`, `hyperbolic`, `cerebras`

---

### Model Not Available on HF Inference

**Issue**: Model returns 404 or "model not found"

**Cause**: Not all models are hosted on HF Inference API

**Solution**: Use a supported model:

```env
# These work on free tier:
TEXT2SQL_MODEL=Qwen/Qwen2.5-Coder-7B-Instruct
TEXT2SQL_MODEL=meta-llama/Llama-3.2-3B-Instruct
TEXT2SQL_MODEL=Qwen/Qwen2.5-Coder-32B-Instruct
```

Check model availability:
```python
from huggingface_hub import model_info
info = model_info("model-name")
print(info.inference)  # Should be 'warm' or 'hot'
```

---

### Out of Memory (Local Inference)

**Issue**: CUDA out of memory or process killed

**Solution**: Enable quantization:

```env
ENABLE_8BIT_QUANTIZATION=true   # Reduces memory ~50%
# OR
ENABLE_4BIT_QUANTIZATION=true   # Maximum compression
```

Or use HF Inference API instead of local:

```env
AGENT_MODEL_BACKEND=hf_inference
```

---

### Agent Takes Too Long

**Issue**: Responses take >10 seconds

**Solutions**:

1. Reduce reasoning steps:
   ```env
   AGENT_MAX_STEPS=3
   ```

2. Use a faster model:
   ```env
   TEXT2SQL_MODEL=meta-llama/Llama-3.2-3B-Instruct
   ```

3. Enable caching (repeated queries are instant)

---

### Agent Gets Stuck in Loop

**Issue**: Agent keeps retrying without progress

**Solutions**:

1. Lower confidence threshold:
   ```env
   AGENT_MIN_CONFIDENCE=0.6
   ```

2. Check logs for validation errors:
   ```bash
   docker logs text2sql-agent 2>&1 | grep -i error
   ```

3. Verify database schema is accessible

---

### Database Connection Fails

**Issue**: Can't connect to database

**Solutions**:

1. Verify connection string format:
   ```env
   # PostgreSQL
   DATABASE_URL=postgresql://user:pass@host:5432/db

   # With SSL
   DATABASE_URL=postgresql://user:pass@host:5432/db?sslmode=require
   ```

2. Check network/firewall access

3. Verify credentials

---

### pip Resolution Errors

**Issue**: `resolution-too-deep` or dependency conflicts

**Solution**: Install with constraints:

```bash
pip install -r requirements.txt -c constraints.txt
# OR
bash scripts/install_with_constraints.sh
```

---

### Low Accuracy on Domain Queries

**Issue**: Generated SQL doesn't match your schema

**Solutions**:

1. Add few-shot examples via API:
   ```bash
   curl -X POST http://localhost:8000/api/v1/examples \
     -H "Content-Type: application/json" \
     -d '{"query": "...", "sql": "...", "database_id": "..."}'
   ```

2. Ensure schema introspection is working:
   ```bash
   curl http://localhost:8000/api/v1/schema/your_database_id
   ```

---

### Docker Build Fails

**Issue**: Build runs out of space or takes too long

**Solutions**:

1. Use CPU-only build (smaller):
   ```bash
   docker build --build-arg TORCH_CPU=true -t text2sql-agent .
   ```

2. Clean Docker cache:
   ```bash
   docker system prune -a
   ```

3. Use BuildKit caching:
   ```bash
   DOCKER_BUILDKIT=1 docker build -t text2sql-agent .
   ```

---

## Getting Help

1. Check the logs:
   ```bash
   docker logs text2sql-agent
   # Or for local:
   uvicorn app.main:app --reload 2>&1 | tee app.log
   ```

2. Enable debug mode:
   ```env
   API_DEBUG=true
   ```

3. Open an issue: https://github.com/Sakeeb91/text2sql-agent/issues

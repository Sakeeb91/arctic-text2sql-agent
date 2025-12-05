# Resilience & Error Handling

## Objectives
- Prevent repeated failures from overwhelming dependencies.
- Provide consistent, structured error responses.
- Keep APIs responsive with safe fallbacks.

## Circuit Breaker
- Guards model/database calls to short-circuit repeated errors.
- States: `closed` → `open` (on threshold) → `half_open` (after cooldown).
- Exposed via `/api/v1/health` under `components.inference_circuit`.

## Backoff & Retry
- Exponential backoff using `compute_backoff_seconds`.
- Limited retries with confidence-aware logic in the Text2SQL engine.

## Error Responses
- All API errors use the `ErrorResponse` envelope with `code`, `message`, `details`, and `request_id`.

## Operations Tips
- If CI hits pip "resolution-too-deep", install with constraints:
  ```
  pip install -r requirements.txt -c constraints.txt
  ```
- Monitor health endpoint for `inference_circuit` status to detect downstream instability early.


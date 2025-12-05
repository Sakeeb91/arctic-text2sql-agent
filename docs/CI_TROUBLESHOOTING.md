# CI Troubleshooting

## pip "resolution-too-deep"
- Cause: overly broad/unconstrained dependencies force exhaustive resolution.
- Fix: install with constraints to bound dependency space.
  ```bash
  pip install -r requirements.txt -c constraints.txt
  ```
- Ensure critical deps (e.g., `cryptography>=39.0.0`) have minimum versions.

## General Tips
- Re-run with `pip --verbose` to inspect resolution decisions.
- Clear pip cache if resolution seems stuck: `pip cache purge`.
- Keep `constraints.txt` in sync with `requirements.txt` when updating dependencies.


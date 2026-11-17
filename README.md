# Rushline

Flash-sale checkout engine built to survive Black Friday style rushes: zero overselling, a fair waiting room, measured performance.

> Work in progress. The full README (architecture diagram, benchmarks, screenshots) lands in Phase 3.

## Run the backend

```bash
docker compose up --build        # API on http://localhost:8000 (docs at /docs)
docker compose run --build --rm tests   # pytest, inside Python 3.12
```

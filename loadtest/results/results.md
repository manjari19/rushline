Measured on Apple M5, 10 cores, 16 GB RAM, Darwin 25.5.0; API, worker, Postgres and Redis in Docker Desktop; k6 on the same machine.
Run on 2026-11-17. Waiting room admission raised to 1,000/s for these runs; latency excludes `/pay` (the fake provider sleeps on purpose).

| Scenario | Mode | Buyers | Throughput (req/s) | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | Orders | Oversold |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| steady | naive | 3,001 | 100 | 2 | 3.7 | 6.4 | 0% | 3,001 / 10,000 | 0 |
| steady | safe | 3,001 | 462.2 | 1 | 2.2 | 3 | 0% | 3,001 / 10,000 | 0 |
| spike | naive | 5,000 | 1,415.2 | 2446.3 | 3239.4 | 3280.6 | 0% | 5,000 / 100 | 4,900 |
| spike | safe | 5,000 | 3,531.8 | 242.1 | 1217.4 | 2795.6 | 0% | 100 / 100 | 0 |
| abandon | naive | 601 | 2.9 | 3.9 | 6 | 8 | 0% | 100 / 100 | 0 |
| abandon | safe | 601 | 32.3 | 1.8 | 3.7 | 5.8 | 0% | 84 / 100 | 0 |

Latency of the contended step only (naive checkout, or safe-mode reserve):

| Scenario | Mode | p50 (ms) | p95 (ms) | p99 (ms) |
|---|---|---:|---:|---:|
| steady | naive | 2 | 3.7 | 6.4 |
| steady | safe | 0.8 | 1.1 | 1.5 |
| spike | naive | 2446.3 | 3239.4 | 3280.6 |
| spike | safe | 5.4 | 265.3 | 533.6 |
| abandon | naive | 3.9 | 6 | 8 |
| abandon | safe | 1.2 | 1.7 | 2.7 |

# Incident signal

- 13:30 — Datadog: search latency p95 is ~3x normal for roughly 10% of users.
- Search still returns correct results, just slowly (degraded, not down).
- Disabling the new `ranking_v2` feature flag restores normal latency — a working workaround exists.
- No data loss; no other service affected.

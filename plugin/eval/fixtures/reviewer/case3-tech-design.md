---
type: tech-design
feature: search
status: in-review
decisions:
  - Add a read-through cache in front of the search index
components:
  - query-api
  - cache
risks:
  - Increased memory usage under load
---

# Search caching design

To cut p95 latency for popular queries, `query-api` gains a read-through cache: on each
query it checks the cache first; on a miss it queries the search index and stores the
result before returning it.

The cache is keyed by the normalized query string. Hot queries are served entirely from
memory.

This document specifies how entries are written and read, but does not describe how or when
cached entries are invalidated or refreshed when the underlying index changes.

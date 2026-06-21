---
type: prd
feature: search
status: approved
goals:
  - Let users find documents by keyword in under 200ms p95
  - Rank results by relevance
  - Support incremental indexing as documents change
non_goals:
  - Personalized ranking
  - Natural-language question answering
metrics:
  - p95 query latency < 200ms
  - Top-3 relevance >= 0.8 on the eval set
acceptance:
  - A keyword query returns ranked, relevant documents
  - Newly added documents become searchable within one minute
---

# Search — product requirements

Users need to find documents across the workspace by keyword quickly. Today there is no
search; users scroll and guess. This feature adds a search box that returns ranked results.

## Context

The corpus is up to ~1M documents per workspace. Documents change frequently, so the index
must stay fresh. The existing stack is a Python service with a relational database.

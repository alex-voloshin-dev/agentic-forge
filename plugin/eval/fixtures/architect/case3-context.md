# Design request: search data layer under a hard constraint

Design the data layer for search indexing and querying.

Hard constraint: **no new external datastore may be added.** The only persistence available
is the existing relational database (PostgreSQL); introducing a dedicated search engine
(e.g. a separate Elasticsearch/OpenSearch cluster) or another service is out of scope.

Produce the design as an artifact under `docs/sdlc/search/`, mapping the indexing and query
paths onto the existing database, and call out the risks and trade-offs the constraint
creates (e.g. relevance quality, latency at scale).

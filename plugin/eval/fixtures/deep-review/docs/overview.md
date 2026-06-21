# Widget service — overview

The response **cache is enabled by default**; operators can turn it off with `CACHE=off`.

Every request is routed through the **Gatekeeper** before it reaches a handler.

## Limits

Each tenant is capped at **1000 requests/minute**.

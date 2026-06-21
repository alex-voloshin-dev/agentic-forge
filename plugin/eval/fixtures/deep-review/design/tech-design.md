---
type: tech-design
feature: notifications
status: in-review
decisions:
  - Deliver notifications via a Redis-backed queue with a delivery worker
components:
  - api
  - queue
  - worker
risks:
  - Worker backlog under traffic spikes
---

# Notifications design

The API enqueues a notification onto a Redis list; a worker pops and delivers it. We chose
Redis for low latency and because it is already in the stack.

Delivery is **at-least-once**: if a worker crashes after delivery but before acknowledging,
the message is redelivered.

## Components

- `api` — accepts a notification request and enqueues it.
- `queue` — the Redis list.
- `worker` — pops from the queue and delivers.

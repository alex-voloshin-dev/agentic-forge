---
type: prd
feature: live-order-status
status: approved
---

# PRD: live order status

## Problem

After checkout, customers sit on the order page and refresh it to see whether their order
was accepted, packed and dispatched. Support gets ~400 "where is my order" tickets a day
from people who did not notice a status change.

## Goals

1. The order page updates on its own when the order's status changes — no manual refresh.
2. **Freshness:** a status change is visible on an open order page within **60 seconds**.
3. Works in the browsers we already support (last two versions of the major browsers) and
   in the mobile web view of our app.

## Current system

- `orders-api`: stateless HTTP/JSON service behind the existing load balancer, 12 instances,
  sized for 6,000 requests/s; current peak is 2,200 requests/s. `GET /orders/{id}` is served
  from a read replica and supports `ETag` / `If-None-Match` (a 304 costs about a fifth of
  a full response).
- Order status changes are written by the fulfilment service to the `orders` table; about
  six changes per order over its life.
- Peak concurrent open order pages: ~25,000.

## Non-goals

- **No new stateful infrastructure this half.** Operations will not run a long-lived
  connection tier (WebSocket or Server-Sent-Events gateways, a pub/sub fan-out cluster);
  every new runtime component must be stateless and fit behind the existing load balancer.
- **No new third-party vendors** (procurement freeze until Q3), including hosted push or
  realtime services.
- Native app push notifications (a separate project).

## Deliverable

A technical design (`tech-design.md`) and the ADRs behind it.

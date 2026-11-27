---
type: prd
feature: wallet-balance
status: approved
---

# PRD: multi-region wallet balance

## Background

The wallet service holds a prepaid balance per customer. It runs today in one region
(eu-west). We are adding a second region (us-east) so customers in North America get the
same responsiveness as customers in Europe. Customers travel: the same customer may spend
from a phone in Europe and, an hour later, from a laptop in the US.

## Goals

1. **Both regions accept debits and credits.** A request is served by the region nearest to
   the customer at that moment; neither region is read-only.
2. **No overdraft, ever.** A debit must never succeed if the balance, counting every debit
   already acknowledged in *either* region, would go below zero. Finance treats any
   overdraft as an incident.
3. **Reads reflect every acknowledged write.** A balance read in either region shows every
   debit and credit acknowledged anywhere: a read that starts after a write was acknowledged,
   in either region, includes that write.
4. **Latency.** p99 of a debit or credit, **and** p99 of a balance read, as measured at the
   region's API edge, are each at most **50 ms** in both regions, for every customer.
5. **Availability.** If one region is down, the other keeps serving its customers.

## Facts

- Round-trip time between eu-west and us-east: **~90 ms** (p50), ~110 ms (p99).
- Current single-region debit p99: 18 ms (PostgreSQL, synchronous replica in the same region).
- Traffic: 2,000 debits/s peak; ~4 % of a customer's debits happen outside their usual region.

## Non-goals

- Changing the product's pricing or limits.
- Supporting more than two regions this year.

## Deliverable

A technical design (`tech-design.md`) and the ADRs behind it.

# Why we added task priorities

Task Store is a tiny in-memory task list for people who live in a terminal. Until now every task was equal, which is fine for six tasks and useless for sixty. This release adds a priority to each task (1 = do it first, 5 = someday) and sorts the list by it.

## What changed

- `priority_of(task)` returns a task's priority, defaulting to 5.
- `list` sorts by priority, then by creation order.
- The CLI accepts `--priority N` on add.

## Why not due dates?

Due dates lie. Priorities are a statement about *relative* importance, which is the only thing a single person can keep honest.

## Try it

```
taskstore add --priority 1 "ship the release"
```

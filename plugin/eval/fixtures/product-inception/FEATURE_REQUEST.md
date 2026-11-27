# Feature request: todo list with indexing status

Slug: `newapp-onboarding` (used for `docs/sdlc/newapp-onboarding/` in the E2E scenario).

## Goal

The todo service (`app.py`, `worker.py`) accepts a todo and hands an indexing job to an in-memory
background worker, but nobody can see the todos, and a job that fails is lost without a trace. As a
user, I want to see my todos and whether each one was indexed, so I know which ones a later search
would miss.

## Acceptance criteria

1. For API clients, `POST /todos` takes JSON `{"title": "<text>"}`, assigns the todo's id itself,
   keeps the todo in memory, enqueues its indexing job and answers `201` with `{"id", "title",
   "index_status": "queued"}`. A missing, empty or longer-than-200-character title answers `400`
   with a JSON error message and enqueues nothing.
2. `GET /todos` returns every todo in creation order as JSON, each with its `index_status`:
   `queued`, `indexed` or `failed`.
3. For people, `GET /` serves one server-rendered HTML page that lists the todos with their
   indexing status and has a plain HTML form to add one. The form posts form-encoded data
   (`title=<text>`) to `POST /`, which applies the same title rules as criterion 1: an accepted
   title redirects back to `GET /`; a rejected one re-renders the page with status `400`, the
   error message next to the field, and the typed title kept. With no todos, the page shows an
   empty state.
4. A failing indexing job is retried at most 3 times; after the last failure its todo reads
   `failed` instead of disappearing. A job that succeeds marks its todo `indexed`.
5. `python app.py` still starts the service, with the worker running in the same process; no new
   runtime dependency beyond Flask.

## Non-goals

- No authentication, accounts or per-user todos.
- No search over todos: the indexing status only says whether a later search could find one.
- No editing, completing or deleting todos.
- No persistence beyond process memory, and no external queue or broker (Redis, Celery, ...).
- No visual or brand design: the page is plain semantic HTML, with no CSS framework and no
  JavaScript build.

This one request is the scope every document phase of the `product-inception` scenario works
within: `research` investigates it, `product` specifies it, `ux-design` designs the page and its
states, `architecture` designs the change.

---
title: Auth approach - signed session cookies
type: note
tags: [decision, auth]
---

# Auth approach - signed session cookies

**Decision:** the web UI authenticates with a signed, HttpOnly session cookie (an HMAC over a
random session id, 30-minute idle timeout). No JWTs in local storage.

**Rationale:** the app is a single-origin, server-rendered page; a cookie keeps the token out of
JavaScript, and rotating it on a privilege change is one server-side call.

**Open question:** whether the CLI needs any auth at all (single-user, local files) — not decided.

Related: [[task-priority-ordering]].

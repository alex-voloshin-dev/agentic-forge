# Ledgerline — project rules

Ledgerline is the invoicing and payments service behind the customer billing portal. It is a
Python 3.12 HTTP service (a thin request layer over plain modules), backed by PostgreSQL, deployed
as a container. These rules apply to every change, by a person or an agent. Where a rule says
"reviewers", it applies to anyone reviewing a change, including an automated review.

## Repository layout

- `api/` — request handlers. One module per resource. Handlers parse and validate the request,
  call into `lib/`, and shape the response. No business logic here.
- `lib/` — business logic and data access. No knowledge of HTTP.
- `jobs/` — scheduled and queued jobs (nightly reconciliation, backups, dunning emails).
- `migrations/` — schema migrations, one file per change, never edited after merge.
- `tests/` — mirrors the source tree: `tests/lib/test_users.py` tests `lib/users.py`.
- `docs/` — design notes and runbooks. A design note lives next to the feature it describes.

## Commands

- `make check` runs everything CI runs: lint, types, tests. Run it before you push.
- `make test` runs the test suite; `make test-fast` skips the tests marked `slow`.
- `make lint` is `ruff check` plus `ruff format --check`; `make fmt` fixes formatting.
- `make types` is `mypy --strict` on `api/`, `lib/` and `jobs/`.
- `make db-up` starts a local PostgreSQL in a container for the integration tests.

## Style

- Formatting is whatever `ruff format` produces. Do not hand-format, and do not mix formatting
  changes into a functional change.
- Line length is 100.
- Names say what a thing is: `invoice_total`, not `tot` or `x`. A renamed variable that reads
  better is a welcome change on its own.
- Prefer small functions with early returns over nested conditionals.
- Module-level constants are `UPPER_SNAKE_CASE` and live at the top of the module.
- No wildcard imports. Import modules, not names, from `lib/` into `api/`
  (`from lib import users`, then `users.get_user(...)`).
- Comments explain why, not what. Delete commented-out code instead of committing it.

## Types

- Every function in `api/`, `lib/` and `jobs/` is fully annotated; `mypy --strict` must pass.
- Money is `decimal.Decimal`, never `float`. Amounts carry their currency (`lib.money.Amount`).
- Use `datetime` objects with a timezone (`datetime.now(tz=UTC)`); a naive datetime is a bug.
- Do not use `Any` to silence the type checker. If a library is untyped, add a typed wrapper.

## Errors

- Raise the domain errors in `lib/errors.py` (`NotFound`, `BadRequest`, `Conflict`); the request
  layer maps them to 404, 400 and 409. Never return an error as a value.
- Never catch a broad `Exception` except at the request boundary, where it is logged and turned
  into a 500.
- Do not use exceptions for control flow on a value you could have checked first.

## Input from a request

Everything that arrives in a request — query string, path, headers, body — is untrusted.

- Validate it where it enters, in the handler, before it reaches `lib/`: type, emptiness, length
  or range, allowed shape. Reject a bad value with `BadRequest` and a message that says which
  field was wrong.
- **An index or offset taken from a request is checked explicitly, `0 <= i < len(seq)`, before it
  is used.** A negative index does not fail in Python: it silently wraps to the end of the list
  and returns someone else's record. Catching `IndexError` afterwards is not validation, because a
  negative index never raises it. Reviewers treat an unchecked request-derived index as a major
  finding and ask for the explicit range check, not for a `try`/`except`.
- Identifiers from a request are parsed into their type (`int`, `UUID`) at the boundary; `lib/`
  functions never receive raw strings for them.

## Data access

- SQL goes through `lib/db.py`. Queries take values as bound parameters
  (`db.execute("... WHERE id = %s", (invoice_id,))`). Never build SQL with `+`, f-strings or
  `%` formatting on a value, even one you validated.
- Every query that can return many rows has a `LIMIT`.
- A change that adds a cache states how entries are invalidated when the source data changes,
  and how stale an entry may get. A cache without that is not merged.

## Running other programs

- Use `subprocess.run([...], check=True)` with an argument list. Never `os.system`, never
  `shell=True`, never a command string built from a value.
- A path from a request is never passed to a command; jobs take paths from configuration only.

## Logging and secrets

- Log with the module logger (`log = logging.getLogger(__name__)`), never `print`.
- **No secret reaches a log line, at any level, DEBUG included**: API tokens, passwords, card
  data, session cookies, signing keys. Log an identifier (a token's last four characters, a key
  id) when you need to correlate. Reviewers treat a log call that formats a secret as a major
  finding.
- Secrets come from the environment through `lib.config`; never from the repository.

## Testing

- Every behaviour change ships with tests in the same pull request, including the error paths:
  a bad request, a missing record, a conflict.
- A bug fix starts with a test that fails without the fix.
- Unit tests do not touch the network or a real database; integration tests are marked
  `integration` and use `make db-up`.
- Never delete, skip or loosen an existing test to make a change pass. If a test is wrong, say why
  in the pull request and fix it in its own commit.
- Test names say the behaviour: `test_get_user_rejects_negative_index`, not `test_get_user_2`.

## Dependencies

- Prefer the standard library and what is already in `pyproject.toml`.
- A new dependency needs a sentence in the pull request on why, and a pinned version.

## Documentation

- A change in behaviour updates the docs that describe it in the same pull request.
- A design note states the problem, the decision, the alternatives considered and what could go
  wrong. A note with an open question says so at the top.

## Commits and pull requests

- One logical change per pull request. A refactor and a feature are two pull requests.
- Commit messages: an imperative summary line under 72 characters, a blank line, then why.
- The pull request description says what changed, why, how it was tested, and what a reviewer
  should look at first.
- Never commit generated files, local configuration or credentials.

## Code review

Reviews are how this team keeps the rules above. A review returns one verdict and a list of
findings.

- **Verdict:** `approve` or `changes`. `changes` when any finding is `blocker` or `major`;
  otherwise `approve`, with the minor findings listed for the author to take or leave.
- **Severity:**
  - `blocker` — data loss, a security hole, money computed wrongly, a broken build.
  - `major` — a rule above is broken in a way that affects behaviour, or a defect a user would hit.
  - `minor` — a real but small problem: an unclear name, a missing edge-case test.
  - `nit` — taste. Never a reason for `changes`.
- **Every finding** names the file and line, says what is wrong and why it matters, and gives a
  concrete fix. "Consider improving error handling" is not a finding.
- A finding about an unvalidated input says which value, where it enters, and the check to add.
- Review the change, not the codebase. A pre-existing problem outside the diff is a follow-up
  note, not a reason to hold the change.
- Do not invent problems to have something to say. A small, correct change — a rename, a clearer
  name, a comment fix — gets `approve` with no findings, or with nits only.
- For a design note, check that it answers the questions its decision raises: for a cache, how
  entries are invalidated and how stale they may get; for a queue, what happens to a failed
  message; for a migration, how it is rolled back.
- The reviewer does not edit the code under review. Suggest the fix; the author makes it.

## Things not to do

- Do not push to `main`; every change goes through a pull request and a green `make check`.
- Do not change a migration that has been merged; add a new one.
- Do not log, print or commit a secret, even temporarily.
- Do not silence a linter or type error with an ignore comment without a reason next to it.

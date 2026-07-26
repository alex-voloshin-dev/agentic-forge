---
name: knowledge
description: Remember, recall, or capture durable PROJECT knowledge in the repo's Obsidian vault (docs/knowledge/). CAPTURE — when asked to remember, note, save, or not forget a decision, rationale, or learning ("remember this …", "note that we decided …", "don't let us relitigate …"), persist it to the vault as an atomic, wikilinked note (durable project memory, not transient chat memory). RECALL — answer "what do we know / have we already decided / did we note about X" from OUR OWN notes, including prior art WE recorded. For NEW external investigation use research; not onboarding a whole codebase (repo-onboarding), writing code (develop), or product specs (product).
allowed-tools: Read, Grep, Glob, Bash, Write, Edit
---

# Knowledge (recall + capture)

Maintain and read the project's durable knowledge — the Obsidian vault at `docs/knowledge/`
(atomic notes + `[[wikilinks]]` + maps-of-content). The deterministic vault operations are the
**installed `agentic_forge.vault` module**; this skill adds the judgement: what's worth recalling,
what's worth capturing, and how to keep notes atomic and linked. (Mechanism: ADR 0018.)

## Vault operations (deterministic core)

Invoke the helpers as an **installed module** — never look for a file by path:

```
python -c "from agentic_forge import vault; print(vault.validate_vault('.'))"
```

Use `vault.add_note(repo, name, title, body, tags=..., moc=...)` to write a note (it emits the
canonical frontmatter and links it from a MOC) and `vault.validate_vault(repo)` to check the graph
before finishing. If the module is genuinely unavailable and you must write a note by hand, its
YAML frontmatter MUST be exactly these keys:

```
---
title: <human title>
type: note        # "note" for an atomic note, "moc" for a map-of-content
tags: [tag-a, tag-b]
---
```

## When to use

- **Recall** — "what do we know about X", "have we decided / discussed X", "our notes or prior
  art on X", before designing or building. This reads **our** vault — not the outside world
  (that's `research`).
- **Capture** — "remember this", "capture this decision / rationale / learning", "note that …".
  Save durable knowledge that does **not** belong in code or git history (the *why* behind a
  choice, a gotcha, how we think about something).

## Recall

1. Detect the vault — `vault.validate_vault(repo)` (offer to `vault.scaffold(repo)` if absent).
2. `vault.recall(repo, query)` → ranked candidate notes; read the top few in full.
3. Answer **grounded in those notes**, citing `[[note]]` links. If the vault has nothing on it,
   say so plainly — never invent knowledge.

## Capture

1. Distill to **one atomic idea per note** (split if it's several). Choose a kebab-case `name`,
   a `title`, and `tags`.
2. `vault.add_note(repo, name, title, body, tags=...)` — writes the note and links it from the
   root MOC. Use `[[wikilinks]]` in the body to connect related notes; add or extend a themed
   MOC (`moc=...`) for a cluster.
3. When a note records a decision that changes a **code, config or infrastructure artifact, name
   that artifact in the note** (the file, the manifest, the flag). A reader can then verify the
   decision actually shipped with one grep — a note is an intent, and intents go unimplemented.
4. `vault.validate_vault(repo)` and fix any broken link or orphan before finishing.

## Definition of done

- Recall answers are grounded in real notes and cite `[[links]]`, or state the vault is silent.
- A recalled note asserting a code/config fact was checked against that artifact before being acted
  on, and any disagreement was surfaced rather than resolved silently.
- Captured notes are atomic, tagged, wikilinked, and reachable from a MOC; `validate_vault` is
  clean — no broken links, no orphans.

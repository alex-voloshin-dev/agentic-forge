# ADR 0112 — A handoff artifact may open with a title

Status: Accepted (implemented)
Date: 2026-11-23

Amends [0010](0010-handoff-schemas-and-pattern-references.md) (the artifact's shape: a YAML header, then the body)
and [0110](0110-the-field-queue-items-7-to-15.md) (`af.py artifact-home`'s `format`: what counts as ours).

## Context

A field report, thread 64a85c8a. A documentation repository's CI requires the first nonblank line of every Markdown
document to be a `# Title`; its retrieval index reads that line as the document's name. Since 2026.11.11 the phases
write into the repository's own feature folder (`af.py artifact-home`, ADR 0110), so the plugin's PRD, design and
plan now sit where that check runs.

`frontmatter.parse` requires the text to open with the `---` block (`\A---`). So a handoff artifact that satisfies the
repository's CI could not satisfy the plugin:

| Reader | On `# Title` then the header |
| --- | --- |
| `handoff.parse_artifact` / `load_artifact` (`af.py handoff-load`, `diagnostics`, `spine_e2e`) | refused: "missing or malformed YAML frontmatter" |
| `artifact_home.artifact_format` (`artifact-home`'s `format`) | `foreign`, so the next phase treats the plugin's own document as a foreign PRD |

Either the repository's CI failed, or every read-back did.

## Decision

**A handoff artifact may open with exactly one ATX H1 line, then its header.** The line is `# ` followed by text with
at least one non-blank character once a CommonMark closing sequence (trailing `#`s that are the whole text or follow
a blank) is removed: `# #` and `# ###` are empty headings and are refused, while `# C#` and `# Title #` are titles,
kept as written. Blank (whitespace-only) lines may come before and after it. Then the `---` block follows, as before.

- **Opt-in at the parser, on for handoff only.** `frontmatter.parse(text, *, allow_title=False)` gains a keyword-only
  flag. `handoff.parse_artifact` passes `allow_title=True`; nothing else does. `frontmatter.split_title(text)` returns
  `(title, rest)` when the text opens with one title followed by a line starting `---`, else `("", text)`; the header
  itself is checked by the caller (`parse`'s strict match, or `artifact_format`'s own probe).
  `artifact_home.artifact_format` applies it before its existing check, so the same form reads as `handoff` when the
  header names the type, and `foreign` otherwise.
- **The title stays in the body.** `parse` returns the body as the title line (with its own line ending) followed by
  the body after the header. The blank lines around the title are dropped. Nothing the author wrote above the header
  is lost to a consumer that reads `body`.
- **Errors stay loud.** Anything else before the header is not a title. The text then goes to the strict check
  unchanged and is refused:
  - a title with no header after it, or with text between the title and the header;
  - two H1 lines;
  - an H2 (`## `), an indented `#`, or `#Title` without the space;
  - an empty title (`# ` alone, or only a closing sequence: `# #`, `# ###`);
  - prose.

  With the flag, the message names both accepted forms. Without it, the message is unchanged.
- **Line endings and the BOM, as before.** CRLF is accepted in the title as in the header. A BOM (U+FEFF) before `---`
  was refused before this ADR (`\A---` does not match it, and `af.py` and `load_artifact` decode as `utf-8`, not
  `utf-8-sig`); it is still refused, with or without a title. `artifact_format` likewise still reads a BOM as
  `foreign`.
- **The default stays header-first.** The pattern (`plugin/patterns/handoff.md`) says to use the title-first form only
  when the repository requires its documents to open with a title, and to keep the title line when updating the
  header (the loop's `review_decision`).

### Who reads frontmatter, and what each does now

| Caller | Reads | Decision |
| --- | --- | --- |
| `handoff.parse_artifact` / `load_artifact` | model-written handoff artifacts | **title allowed** |
| `af.py handoff-load` and `plan-batches` (`_load` → `parse_artifact`) | the same | title allowed |
| `diagnostics` (review rounds), `spine_e2e` (`load_artifact`) | the same | title allowed |
| `artifact_home.artifact_format` | the same, as a format probe | title allowed |
| `validation`, `skill_eval`, `agent_eval`, `tier1_runner`, `pre_router`, `dev/sync_models.py`, `dev/run_agent_evals.py` | SKILL.md / agent frontmatter | strict, unchanged |
| `skill_contract` | SKILL.md bodies (does a skill *document* the fields), not an emitted artifact | strict, unchanged |
| `spine_e2e.skill_body` | SKILL.md | strict, unchanged |
| `vault` | vault notes | strict, unchanged |

No code rewrites a handoff header. `models.set_frontmatter_model` edits agent files only, and
`bin/external_review.py` writes a new review file, header-first. The only header update is the model's own edit of
`review_decision`, which the pattern covers.

## Rejected alternatives

- **A sidecar file for the header.** Declined: the header and the body are one reviewed unit (one diff, one review
  round, one commit). Two files drift, and every reader would need to find the pair.
- **The metadata in an HTML comment after the title.** Rejected: a second header syntax to parse, validate and teach,
  for a problem one optional line solves.
- **Changing `frontmatter.parse`'s default.** Rejected: skill and agent frontmatter must stay strictly first. Claude
  Code reads it there, and `validate.py` must refuse a SKILL.md that would not load.

## Consequences

- A repository whose CI wants a leading `# Title` can keep its check. The plugin's artifacts in its feature folder pass
  that check, read back with `handoff-load`, and show `format: handoff`.
- A title-first artifact read by an older plugin release is refused, as today. The default form is unchanged, so only
  a repository that chose the title-first form is affected.
- **No Markdown renderer treats the header as frontmatter in the title-first form.** Renderers (GitHub's included)
  recognise frontmatter only at the very start of the file. After a title, under CommonMark, the opening `---` is a
  thematic break, and the YAML lines above the closing `---` render as a setext H2 (a YAML block list can instead
  render as a list). A heading-based linter or retrieval index may therefore see a second heading made of the YAML.
  This is documented, not worked around: the closing-fence rule is unchanged, and the form is for repositories whose
  own check requires the title.
- `artifact_home` now imports `frontmatter`. That import is stdlib-only (`re`, `typing`; PyYAML is lazy), so the
  role-scope hook's import chain stays stdlib-only and Python 3.9.

# Design-to-code handoff (ux-design reference)

Load when the ux-spec is being handed to engineering: the per-component spec template, token
naming, and the quick accessibility pass. The goal: an engineer implements without follow-up
questions.

## Token naming (specify in tokens, not raw values)

| Foundation | Token shape | Example |
| --- | --- | --- |
| Color (brand/semantic/neutral) | `color-{category}-{shade}` | `color-danger-600` |
| Typography | `font-{property}-{size}` | `font-size-lg` |
| Spacing (4/8px base) | `spacing-{size}` | `spacing-4` |
| Radius / elevation / motion | `radius-{size}`, `shadow-{level}`, `motion-{property}-{variant}` | `shadow-2` |

Mapping for implementers: Figma Auto Layout ↔ flex/grid; component variants ↔ props; design
tokens (variables) ↔ CSS custom properties; instances ↔ component usage.

## Per-component handoff template

```
## Component: <Name>
Visual: dimensions (or fluid); padding/margin, colors, type, border, shadow — in TOKEN values
Variants: <name>: <visual difference> (primary / secondary / outline / ghost / destructive …)
Sizes: xs–xl as applicable
States: default · hover · focus (indicator spec!) · active · disabled · loading · error
Responsive: mobile / tablet / desktop behavior per breakpoint
Interactions: <trigger> → <animation: property, duration, easing>
Accessibility: ARIA role · keyboard bindings · screen-reader announcement
Code ref: <Component variant="…" size="…" /> + the tokens used
```

Never omit **focus**, **disabled**, and **error/loading** states — they are where handoffs
usually leak; if a state is genuinely N/A, say so explicitly rather than leaving it blank.

## 5-minute accessibility pass (before handing off)

1. Tab through — every interactive element reachable and operable in a sensible order?
2. Zoom 200% — content reflows, no horizontal scroll?
3. Contrast — 4.5:1 body / 3:1 large text and UI components?
4. Landmarks — headings, regions, and alt text make sense read aloud?
5. Keyboard-only — the primary task completes without a mouse?

This complements (does not replace) the WCAG requirements in the ux-spec itself.

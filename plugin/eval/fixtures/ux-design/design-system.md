# Design system — quick reference

## Components
- `Button` — variants: primary, secondary, danger; states: default, hover, focus, disabled, loading.
- `IconButton` — icon-only; requires an `aria-label`.
- `TextInput` — label, helper text, error text; states: default, focus, invalid, disabled.
- `ListRow` — one row of a list; slots: title, meta, actions (overflow `Menu`).
- `Menu` — overflow actions; roving tabindex, Escape closes, focus returns to the trigger.
- `Dialog` — modal; focus trapped, labelled by its title, Escape closes.
- `EmptyState` — illustration slot, headline, body, one primary action.
- `Toast` — transient status; `role="status"`; auto-dismisses after 6 s; never the only place an error is shown.
- `InlineAlert` — persistent error/info inside a form or panel; `role="alert"` for errors.

## Tokens
- Color: `color.text`, `color.text-muted`, `color.primary`, `color.primary-hover`, `color.danger`, `color.surface`, `color.border`, `color.focus-ring`.
- Spacing: `space.1` (4px), `space.2` (8px), `space.3` (12px), `space.4` (16px), `space.6` (24px), `space.8` (32px).
- Typography: `font.body` (16/24), `font.body-sm` (14/20), `font.heading` (20/28), `font.label` (12/16, uppercase).
- Radius: `radius.sm` (4px), `radius.md` (8px). Focus ring: 2px `color.focus-ring`, 2px offset.

## Breakpoints
- `mobile` < 600px — single column; row actions move into the overflow `Menu`.
- `tablet` 600-1023px — single column; primary row action inline, the rest in the `Menu`.
- `desktop` >= 1024px — row actions inline.

## Accessibility rules
- Every interactive element is reachable by keyboard in DOM order, with a visible focus ring.
- Text contrast >= 4.5:1 (`color.text` on `color.surface` is 12.6:1).
- Destructive actions confirm in a `Dialog`; form errors use `InlineAlert` (`role="alert"`), not only a `Toast`.

# Decision request: rendering strategy for the results page

The new search results page must be decided: server-side rendering (SSR) or client-side
rendering (CSR)?

Constraints and context:
- SEO matters: results pages should be indexable by search engines.
- The page is read-heavy and mostly static once rendered.
- The team already runs a Python web service (SSR is straightforward) and a small JS bundle.
- First-contentful-paint is a tracked metric; the team wants it fast on mobile.

Record the decision as an ADR that weighs both options, picks one with a rationale, and
states the consequences.

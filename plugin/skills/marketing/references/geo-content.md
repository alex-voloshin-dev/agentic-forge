# GEO / SEO content audit (marketing sub-procedure)

Audit a page or piece of content for **AI search readiness** (GEO/AEO — will ChatGPT / Claude /
Perplexity / Google AI Overviews extract and cite it?) and/or **technical SEO**. Works on a URL
(fetch it), pasted HTML, or markdown. Score what is actually there — never assume markup you
cannot see. Output is a scored report with prioritized fixes; chain into
[content.md](content.md) when asked to rewrite.

## GEO rubric: five categories, 0–100 total

Score each category 0–20; sum for the overall score.

| Category | What earns points |
| --- | --- |
| **Structure & chunking** | H1 literally states the topic/question (no clever wordplay); 5–9 standalone H2 sections; paragraphs 40–80 words (hard cap 120); each H2 block 120–180 words (the LLM extraction window); TOC for long articles; a TL;DR / key-takeaways close (3–5 bullets) |
| **Schema & markup** | Valid JSON-LD: `Organization`/`WebSite`, `Article`/`BlogPosting` (with dates + author), `Person`, `FAQPage` (the single highest-leverage schema), `BreadcrumbList`; markup matches the visible content |
| **Entity clarity** | Named entities on every claim (product, brand, person); no pronoun drift ("It/This/They" as subjects across paragraphs); the product's **canonical terms used consistently** (one name per concept — terminology drift confuses entity graphs); first mentions linked |
| **Content freshness** | `datePublished` / `dateModified` present; a visible "Updated on …"; stats dated and sourced; examples current |
| **Format & emphasis** | Comparison tables and lists where applicable (tables measurably lift citations); FAQ block with 4–8 Q&As; 3–5 bolded key phrases per 1,000 words; numbered steps for procedures |

Interpretation: **90–100** citation-ready · **75–89** minor fixes · **60–74** material issues,
fix before publish · **<60** rewrite required.

## The 10-point pre-publish checklist

Each is yes/no; these weigh heaviest: (1) H1 states the topic literally; (2) the first sentence
of every H2 answers it in 30–60 words — no preamble; (3) paragraphs ≤80 words, sections 120–180;
(4) ≥1 stat/source/example per 150–200 words; (5) 3–5 bolded phrases per 1,000 words;
(6) a comparison table or list where applicable; (7) an FAQ block (4–8 Q&As) **plus** FAQPage
JSON-LD; (8) Organization + Article + Person schema; (9) canonical product terms used
consistently; (10) visible dates (`datePublished`/`dateModified`, "Updated on").

## Anti-patterns to flag as critical

Bury-the-lede openings ("In this post we will…"); pronoun drift; walls of text (>120-word
paragraphs); "experts say" without names; un-dated statistics ("studies show +30%"); duplicate
FAQ (same Q&A in body and schema — LLMs de-duplicate aggressively); terminology drift; no visible
schema at all.

## FAQPage JSON-LD essentials

One `FAQPage` with `mainEntity: [{ "@type": "Question", "name": …, "acceptedAnswer": { "@type":
"Answer", "text": … } }]`. Answers 40–80 words, self-contained, no markup inside `text`. The Q&As
must exist visibly on the page; schema-only FAQs are misleading markup. Validate the JSON parses.

## Technical SEO pass (when the ask includes SEO)

- **Crawlability:** robots.txt allows the pages + names the sitemap; XML sitemap covers exactly
  the indexable set; no orphaned pages; navigation uses real `<a href>` links; no crawl traps.
- **Indexability:** no accidental `noindex`; canonicals point where intended (no
  canonical-vs-redirect conflicts); 200s not soft-404s; critical content rendered server-side.
- **On-page:** unique title + meta description; exactly one H1; logical H1→H2→H3; alt text on
  meaningful images; descriptive internal anchors.
- **Core Web Vitals:** LCP < 2.5 s, INP < 200 ms, CLS < 0.1 (PageSpeed Insights).
- **Mobile:** responsive, tap targets ≥ 48px, body font ≥ 16px, no intrusive interstitials.

## Report format

Overall score → category scores → **Critical / Medium / Low** issues (each: what + impact) →
prioritized action plan (fix + effort). Ground every issue in something visible in the content —
the evidence discipline applies to audits too: no generic advice the page didn't earn.

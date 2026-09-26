---
name: source-credibility-rules
description: How premarket-ai rates a news source (trusted, neutral, low, blocked, unknown), spots lookalike and spoofed domains, and counts independent corroboration. Use when judging whether an outlet or a link can be believed, or how many sources really report a story.
---

# Source credibility rules

## Reputation tiers
The source reputation table (`get_source_reputation`) gives each domain a
tier and a score from 0 to 1. A subdomain takes its closest listed parent's
tier (wire.vendornews.example → vendornews.example).

| Tier | Meaning |
|---|---|
| trusted | An established newswire or outlet. Its reports count as corroboration. |
| neutral | A known outlet with no special standing. Counts, but weaker. |
| low | Known for low-quality or promotional content. Never enough on its own. |
| blocked | Known to publish fabricated news. Treat every claim as unconfirmed. |
| unknown | Not listed. Treat like low until something corroborates it. |

Analysts' decisions change reputations: every time an analyst overrides a
verdict to FAKE, the item's source loses 0.05.

## Primary sources come first
- The company's own SEC filings are the strongest evidence: an 8-K (a
  material event must be filed within 4 business days) and its EX-99.1
  press release, then XBRL company facts for numbers.
- Federal Reserve and SEC press releases for macro and regulatory news.
- A material event with no filing in the 7 days before is suspicious.

## Spoofed and lookalike domains
A source is SPOOFED when:
- its domain uses a real outlet's brand as a label (reuters-news.test,
  bloomberg.markets.example), or is one edit away from an official domain
  after folding lookalike characters (0→o, 1→l, rn→m);
- the item's `source_domain` doesn't match the host of its link.
Lab data only uses reserved domains (`*.example`, `*.test`): a real
outlet's domain in vendor data is itself a warning.

## Counting corroboration
- Count **independent domains**, not articles: two pages of one outlet, or
  an outlet and its own syndication, count once.
- The vendor's own outlets never corroborate each other.
- Web search results are counted and linked, never stored, and a snippet is
  not a fact: it only shows that someone else reports the story.
- Two or more independent trusted or neutral outlets, or one primary
  source, make a story VERIFIED (see fact-check-methodology).

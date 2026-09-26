---
name: vendor-scorecard
description: How premarket-ai measures the news vendor against its contract of 100 items per day - billable items, duplicate, fake, misleading and stale rates, injection items and analyst overrides - and how to write the weekly vendor summary. Use when asked how the vendor performs or what to raise with it.
---

# Vendor scorecard

The vendor is contracted to deliver about 100 news items per day. It pads
the feed with duplicates, fake and misleading items to reach that number.
The scorecard shows what the company really gets.

## Daily metrics
- Items received and unique items (after the four duplicate levels: URL,
  exact, near copy, paraphrase).
- Duplicate rate by type (url, exact, near, paraphrase) and stale copies.
- FAKE, MISLEADING and STALE rates (of unique items).
- Injection items: items with instructions aimed at an AI.
- Average corroboration: independent outlets per unique item.
- Analyst override rate: decided reviews where the analyst changed the AI
  verdict.

## Billable items
**Billable = unique items that are VERIFIED or UNVERIFIED.** FAKE,
MISLEADING and duplicates don't count. UNVERIFIED counts, because it may be
real breaking news. Always show billable items next to the contracted 100.

## Weekly summary (for analysts and admins)
1. One sentence: billable items per day this week against 100, and the
   trend against last week.
2. The two largest problems, with numbers (for example "22% duplicates, a
   third of them paraphrases").
3. Anything new: a spoofed domain seen for the first time, a jump in
   injection items.
4. What to raise with the vendor, as facts ("Tuesday: 17 FAKE items from
   pennyrocket.example"), never as accusations.
Keep it under 150 words, plain English, numbers exactly as measured.

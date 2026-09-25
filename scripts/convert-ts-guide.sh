#!/usr/bin/env bash
# Generates a Markdown copy of the official Google TypeScript Style Guide.
#
# Uses the official HTML page as the source and converts it with pandoc, the
# same way scripts/convert-cpp-guide.sh and scripts/convert-py-guide.sh do.
#
# Usage (Ubuntu WSL, from the repo root):
#   sudo apt install pandoc        # once
#   scripts/convert-ts-guide.sh [OUTPUT.md]
# Default output: docs/Google_TypeScript_Style_Guide_20260925.md
set -euo pipefail

URL="https://google.github.io/styleguide/tsguide.html"
OUT="${1:-docs/Google_TypeScript_Style_Guide_20260925.md}"

command -v pandoc  >/dev/null || { echo "pandoc not found: sudo apt install pandoc" >&2; exit 1; }
command -v curl    >/dev/null || { echo "curl not found: sudo apt install curl" >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 not found: sudo apt install python3" >&2; exit 1; }

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
curl -fsSL "$URL" -o "$tmp"

# Clean the page before pandoc sees it:
# - keep only the guide (the <div id="content"> body) and drop the <section>
#   wrappers, which pandoc would keep as raw <div> tags;
# - the page marks examples green or red with <code class="language-ts good">
#   / "bad". pandoc can't keep two classes in a GFM fence, so each example gets
#   a "Good:" / "Bad:" line above it and a single language class (```ts).
python3 - "$tmp" <<'PY'
import re
import sys

path = sys.argv[1]
html = open(path, encoding="utf-8").read()

start = html.index('<div id="content">') + len('<div id="content">')
end = html.rindex("</body>")
html = html[start:end]
html = re.sub(r"</?section[^>]*>", "", html)

counts = {"good": 0, "bad": 0, "plain": 0}


def code_block(m):
    classes = m.group(1).split()
    lang = "ts"
    for cls in classes:
        if cls.startswith("language-"):
            lang = cls[len("language-"):].lstrip(".") or "ts"
    if "good" in classes:
        label = "<p><em>Good:</em></p>\n"
        counts["good"] += 1
    elif "bad" in classes or "badcode" in classes:
        label = "<p><em>Bad:</em></p>\n"
        counts["bad"] += 1
    else:
        label = ""
        counts["plain"] += 1
    return f'{label}<pre><code class="language-{lang}">'


html = re.sub(r'<pre>\s*<code class="([^"]*)">', code_block, html)

open(path, "w", encoding="utf-8").write(html)
print(f"Cleaned page: {counts['good']} good, {counts['bad']} bad, "
      f"{counts['plain']} other code blocks")
PY

{
  echo "<!--"
  echo "  Google TypeScript Style Guide - Markdown copy for offline reading and search."
  echo "  Source: $URL (retrieved $(date -u +%Y-%m-%d), converted with pandoc)."
  echo "  Copyright Google. License: CC-BY 3.0. Attribution: https://github.com/google/styleguide"
  echo "  Do not edit: regenerate with scripts/convert-ts-guide.sh."
  echo "-->"
  echo
  pandoc "$tmp" -f html -t gfm --wrap=none
} > "$OUT"

# The page builds its table of contents with JavaScript, so there is none in
# the HTML. Add a Markdown table after the "# " title: one row per "##"
# section, linking to its "###" topics. Anchors follow GitHub's heading slugs.
python3 - "$OUT" <<'PY'
import re
import sys

path = sys.argv[1]
text = open(path, encoding="utf-8").read()

TOC_TITLE = "Table of Contents"


def plain(md):
    """Heading markdown -> the plain text GitHub slugs from."""
    md = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", md)  # links -> text
    md = md.replace("`", "")
    md = re.sub(r"\\(.)", r"\1", md)                   # \# -> #
    return md.strip()


def github_slug(title, seen):
    slug = re.sub(r"[^\w\- ]", "", title.lower()).replace(" ", "-")
    n = seen.get(slug, 0)
    seen[slug] = n + 1
    return slug if n == 0 else f"{slug}-{n}"


# Collect headings outside fenced code, in document order. The TOC heading is
# inserted near the top, so it takes its slug first.
seen = {}
github_slug(TOC_TITLE, seen)
sections = []  # [(title, slug, [(title, slug), ...])]
in_code = False
for line in text.split("\n"):
    if line.startswith("```"):
        in_code = not in_code
        continue
    if in_code:
        continue
    m = re.match(r"^(#{1,6}) (.*)$", line)
    if not m:
        continue
    level, title = len(m.group(1)), plain(m.group(2))
    slug = github_slug(title, seen)
    if level == 2:
        sections.append((title, slug, []))
    elif level == 3 and sections:
        sections[-1][2].append((title, slug))


def cell(items):
    return " · ".join(f"[{t.replace('|', '&#124;')}](#{s})" for t, s in items)


toc = [f"## {TOC_TITLE}", "", "| Section | Topics |", "|---|---|"]
for title, slug, subs in sections:
    toc.append(f"| {cell([(title, slug)])} | {cell(subs)} |")
toc_md = "\n".join(toc)

text = re.sub(r"^(# .*)$", lambda m: m.group(1) + "\n\n" + toc_md, text,
              count=1, flags=re.M)

open(path, "w", encoding="utf-8").write(text)
print(f"Added table of contents: {len(sections)} sections, "
      f"{sum(len(s) for _, _, s in sections)} topics")
PY

echo "Wrote $OUT ($(wc -l < "$OUT") lines)"

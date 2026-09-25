#!/usr/bin/env bash
# Generates a Markdown copy of the official Google C++ Style Guide.
#
# docs/Google_Cpp_Style_Guide_20260925.pdf was made with "Microsoft Print to PDF"
# and has no text layer, so this uses the official HTML page (the same content)
# as the source and converts it with pandoc.
#
# Usage (Ubuntu WSL, from the repo root):
#   sudo apt install pandoc        # once
#   scripts/convert-cpp-guide.sh [OUTPUT.md]
# Default output: docs/Google_Cpp_Style_Guide_20260925.md
set -euo pipefail

URL="https://google.github.io/styleguide/cppguide.html"
OUT="${1:-docs/Google_Cpp_Style_Guide_20260925.md}"

command -v pandoc >/dev/null || { echo "pandoc not found: sudo apt install pandoc" >&2; exit 1; }
command -v curl   >/dev/null || { echo "curl not found: sudo apt install curl" >&2; exit 1; }

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
curl -fsSL "$URL" -o "$tmp"

{
  echo "<!--"
  echo "  Google C++ Style Guide - Markdown copy for offline reading and search."
  echo "  Source: $URL (retrieved $(date -u +%Y-%m-%d), converted with pandoc)."
  echo "  Copyright Google. License and attribution: https://github.com/google/styleguide"
  echo "  Do not edit: regenerate with scripts/convert-cpp-guide.sh."
  echo "-->"
  echo
  pandoc "$tmp" -f html -t gfm --wrap=none
} > "$OUT"

# The page builds its table of contents with JavaScript, so pandoc only sees an
# empty <div id="tocDiv">. Replace it with a Markdown table: one row per "##"
# section, linking to its "###" topics. Anchors follow GitHub's heading slugs.
command -v python3 >/dev/null || { echo "python3 not found: TOC skipped" >&2; exit 0; }
python3 - "$OUT" <<'PY'
import re
import sys

path = sys.argv[1]
text = open(path, encoding="utf-8").read()
lines = text.split("\n")

TOC_TITLE = "Table of Contents"
SKIP_SECTIONS = {"Background"}  # the official page's TOC starts at "C++ Version"


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
for line in lines:
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
    if title in SKIP_SECTIONS:
        continue
    toc.append(f"| {cell([(title, slug)])} | {cell(subs)} |")
toc_md = "\n".join(toc)

placeholder = re.compile(r'<div id="tocDiv"[^>]*>\s*</div>')
if placeholder.search(text):
    text = placeholder.sub(lambda _: toc_md, text, count=1)
else:  # fall back to just after the first "# " title
    text = re.sub(r"^(# .*)$", lambda m: m.group(1) + "\n\n" + toc_md, text,
                  count=1, flags=re.M)

open(path, "w", encoding="utf-8").write(text)
print(f"Added table of contents: {sum(t not in SKIP_SECTIONS for t, _, _ in sections)} sections, "
      f"{sum(len(s) for t, _, s in sections if t not in SKIP_SECTIONS)} topics")
PY

echo "Wrote $OUT ($(wc -l < "$OUT") lines)"

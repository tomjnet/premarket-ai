#!/usr/bin/env bash
# Generates a Markdown copy of the official Google Python Style Guide.
#
# Uses the official HTML page as the source and converts it with pandoc, the
# same way scripts/convert-cpp-guide.sh does for the C++ guide.
#
# Usage (Ubuntu WSL, from the repo root):
#   sudo apt install pandoc        # once
#   scripts/convert-py-guide.sh [OUTPUT.md]
# Default output: docs/Google_Python_Style_Guide_20260925.md
set -euo pipefail

URL="https://google.github.io/styleguide/pyguide.html"
OUT="${1:-docs/Google_Python_Style_Guide_20260925.md}"

command -v pandoc  >/dev/null || { echo "pandoc not found: sudo apt install pandoc" >&2; exit 1; }
command -v curl    >/dev/null || { echo "curl not found: sudo apt install curl" >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 not found: sudo apt install python3" >&2; exit 1; }

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
curl -fsSL "$URL" -o "$tmp"

# Clean the page before pandoc sees it:
# - keep only the guide (from its <h1> to the site footer), which drops the
#   "Google Style Guides" site header and the "Improve this page" footer;
# - turn the collapsed <details> table of contents into a "## Table of
#   Contents" heading (pandoc drops <details>/<summary>);
# - rewrite Jekyll's highlighted code blocks as <pre><code class="language-X">
#   so pandoc keeps the language (```python) instead of ```highlight.
python3 - "$tmp" <<'PY'
import re
import sys

path = sys.argv[1]
html = open(path, encoding="utf-8").read()

start = html.index('<h1 id="google-python-style-guide">')
end = html.index('<div class="footer')
html = html[start:end]

html = re.sub(r"<details>\s*<summary>(.*?)</summary>", r"<h2>\1</h2>", html,
              count=1, flags=re.S)
html = html.replace("</details>", "", 1)

html, opened = re.subn(
    r'<div class="language-(\w+) highlighter-rouge">\s*<div class="highlight">'
    r'\s*<pre class="highlight"><code>',
    r'<pre><code class="language-\1">', html)
html, closed = re.subn(r"</code></pre>\s*</div>\s*</div>", "</code></pre>", html)
if opened != closed:
    sys.exit(f"code blocks: {opened} opened but {closed} closed; page changed?")

open(path, "w", encoding="utf-8").write(html)
print(f"Cleaned page: {opened} code blocks")
PY

{
  echo "<!--"
  echo "  Google Python Style Guide - Markdown copy for offline reading and search."
  echo "  Source: $URL (retrieved $(date -u +%Y-%m-%d), converted with pandoc)."
  echo "  Copyright Google. License: CC-BY 3.0. Attribution: https://github.com/google/styleguide"
  echo "  Do not edit: regenerate with scripts/convert-py-guide.sh."
  echo "-->"
  echo
  pandoc "$tmp" -f html -t gfm --wrap=none
} > "$OUT"

echo "Wrote $OUT ($(wc -l < "$OUT") lines)"

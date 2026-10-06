#!/usr/bin/env bash
# Renders the first page of Chapter I of the reading guide EPUB to docs/media/hero.png.
# Needs Google Chrome or Chromium; set CHROME to its binary if it is not found.
set -euo pipefail

repo="$(cd "$(dirname "$0")/../.." && pwd)"
out="$repo/docs/media/hero.png"

chrome="${CHROME:-}"
if [ -z "$chrome" ]; then
  for candidate in \
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
    "$(command -v google-chrome || true)" \
    "$(command -v chromium || true)"; do
    if [ -n "$candidate" ] && [ -x "$candidate" ]; then chrome="$candidate"; break; fi
  done
fi
[ -n "$chrome" ] || { echo "hero.sh: no Chrome or Chromium found; set CHROME" >&2; exit 1; }

work="$(mktemp -d)"
pid=""
trap '[ -n "$pid" ] && kill "$pid" 2>/dev/null; rm -rf "$work"' EXIT
unzip -q "$repo/Blood_Meridian_Vocabulary_Companion.epub" -d "$work/epub"

# Headless Chrome on macOS can stay running after it writes the screenshot,
# so wait for its "written to file" line instead of its exit.
"$chrome" --headless=new --disable-gpu --hide-scrollbars \
  --user-data-dir="$work/profile" --no-first-run \
  --force-device-scale-factor=2 --window-size=720,880 \
  --screenshot="$out" "file://$work/epub/OEBPS/chapter-01.xhtml" >"$work/chrome.log" 2>&1 &
pid=$!
for _ in $(seq 1 120); do
  grep -q "written to file" "$work/chrome.log" && { echo "wrote $out"; exit 0; }
  kill -0 "$pid" 2>/dev/null || break
  sleep 0.5
done
echo "hero.sh: Chrome did not write the screenshot" >&2
cat "$work/chrome.log" >&2
exit 1

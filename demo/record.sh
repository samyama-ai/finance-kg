#!/usr/bin/env bash
# Record the long-form demo to an animated GIF: asciinema captures the run, agg
# renders it. The pipeline and settings of
# samyama-graph/case_studies/_lib/record_gif.sh, with a longer hold at the end.
#
# Needs a server that already holds the graph:
#   python -m etl.loader --url http://127.0.0.1:8081 --graph finance
#
#   demo/record.sh [url] [graph]
set -uo pipefail

URL="${1:-http://127.0.0.1:8081}"
GRAPH="${2:-finance}"
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$HERE")"
CAST="$HERE/finance-kg.cast"
OUT="$HERE/finance-kg.gif"
PYTHON="${PYTHON:-python}"
# Seconds the finished report is held before the GIF starts again.
HOLD="${GIF_HOLD:-14}"

for tool in asciinema agg; do
  command -v "$tool" >/dev/null || { echo "[gif] '$tool' is not installed"; exit 1; }
done
cd "$ROOT" || exit 1

# Long form: a terminal tall enough for the whole report, so nothing scrolls
# off. The height is measured from an unpaced run rather than guessed, so a
# query added to the demo cannot push the first one off the top.
LINES_NEEDED=$(COLUMNS=100 "$PYTHON" -m demo.demo --long --no-pause \
  --url "$URL" --graph "$GRAPH" | wc -l | tr -d ' ')
[ "$LINES_NEEDED" -gt 10 ] || { echo "[gif] the demo printed nothing; is the server up?"; exit 1; }
ROWS="${GIF_ROWS:-$((LINES_NEEDED + 3))}"

echo "[gif] recording $ROWS rows -> $CAST"
rm -f "$CAST"
COLUMNS=100 LINES="$ROWS" TERM=xterm-256color asciinema rec --overwrite -q -i 6 \
  --headless --window-size "100x${ROWS}" \
  -c "env COLUMNS=100 LINES=$ROWS TERM=xterm-256color PYTHONUNBUFFERED=1 $PYTHON -m demo.demo --long --url $URL --graph $GRAPH" \
  "$CAST" || { echo "[gif] asciinema failed"; exit 1; }

echo "[gif] rendering -> $OUT"
# Real time, with the read pauses kept: a looping GIF cannot be paused, so the
# reading time has to be in the frames.
agg --speed 1.0 --idle-time-limit 4.0 --last-frame-duration "$HOLD" \
  --font-size 18 --theme asciinema "$CAST" "$OUT" \
  || { echo "[gif] agg failed"; exit 1; }

"$PYTHON" -m demo.demo --write-cypher >/dev/null
echo "[gif] wrote $OUT ($(du -h "$OUT" | cut -f1)), held ${HOLD}s at the end"

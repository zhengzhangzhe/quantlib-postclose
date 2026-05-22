#!/bin/bash
# Postclose review + git push — called by crontab daily after market close

set -e
cd "$(dirname "$0")/.."

# Skip weekends (A-share market closed)
DOW=$(date +%u)
if [ "$DOW" -ge 6 ]; then
    exit 0
fi

LOG="output/postclose/run.log"
mkdir -p output/postclose

echo "=== $(date) ===" >> "$LOG"

# 1. Generate review
python3 scripts/postclose_review.py >> "$LOG" 2>&1

# 2. Git auto-commit & push
git add data/ output/ >> "$LOG" 2>&1
git commit -m "auto: postclose review $(date +%Y-%m-%d)" >> "$LOG" 2>&1
git push origin master >> "$LOG" 2>&1

echo "Done: $(date)" >> "$LOG"

#!/bin/bash
# Morning briefing + WeChat push + git push — called by crontab at 9am weekdays

set -e
cd "$(dirname "$0")/.."

# Skip weekends (A-share market closed)
DOW=$(date +%u)
if [ "$DOW" -ge 6 ]; then
    exit 0
fi

LOG="output/morning/run.log"
mkdir -p output/morning

echo "=== $(date) ===" >> "$LOG"

# 1. Generate briefing
python3 scripts/morning_briefing.py >> "$LOG" 2>&1

# 2. Git auto-commit & push
git add data/ output/ >> "$LOG" 2>&1
git commit -m "auto: briefing $(date +%Y-%m-%d)" >> "$LOG" 2>&1
git push origin master >> "$LOG" 2>&1

echo "Done: $(date)" >> "$LOG"

#!/bin/bash
# Morning briefing + WeChat push + git push — called by crontab at 9am weekdays

set -e
cd "$(dirname "$0")/.."

LOG="output/morning/run.log"
mkdir -p output/morning

echo "=== $(date) ===" >> "$LOG"

# 1. Generate briefing
python3 scripts/morning_briefing.py >> "$LOG" 2>&1

# 2. Push to WeChat
DATE=$(date +%Y-%m-%d)
python3 scripts/notify.py --date "$DATE" >> "$LOG" 2>&1

# 3. Git auto-commit & push
git add data/ output/ >> "$LOG" 2>&1
git commit -m "auto: briefing $(date +%Y-%m-%d)" >> "$LOG" 2>&1
git push origin master >> "$LOG" 2>&1

echo "Done: $(date)" >> "$LOG"

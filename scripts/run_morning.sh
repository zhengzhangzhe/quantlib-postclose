#!/bin/bash
# Morning briefing + push — called by crontab at 9am weekdays
# Usage: bash /Users/zzz/quantlib-postclose/scripts/run_morning.sh

source ~/.zshrc 2>/dev/null || true
cd /Users/zzz/quantlib-postclose

LOG="output/morning/run.log"
mkdir -p output/morning

echo "=== $(date) ===" >> "$LOG"

# 1. Generate briefing
python3 scripts/morning_briefing.py >> "$LOG" 2>&1

# 2. Push to WeChat
DATE=$(date +%Y-%m-%d)
python3 scripts/notify.py --date "$DATE" >> "$LOG" 2>&1

echo "Done: $(date)" >> "$LOG"

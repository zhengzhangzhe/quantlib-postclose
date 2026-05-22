#!/bin/bash
# Postclose review + git push — called by crontab daily after market close
# Usage: bash /Users/zzz/quantlib-postclose/scripts/run_postclose.sh

source ~/.zshrc 2>/dev/null || true
cd /Users/zzz/quantlib-postclose

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

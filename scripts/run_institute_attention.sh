#!/bin/bash
# Institute research attention weekly report
# Run Friday after market close (与复盘同时), 为下周一盘前简报提供机构热度数据

set -e
cd "$(dirname "$0")/.."

# Only run on Friday
DOW=$(date +%u)
if [ "$DOW" -ne 5 ]; then
    exit 0
fi

LOG="output/institute_attention/run.log"
mkdir -p output/institute_attention

echo "=== $(date) ===" >> "$LOG"

# 1. Generate weekly report
python3 scripts/institute_attention.py >> "$LOG" 2>&1

# 2. Git auto-commit & push
git add data/institute_attention/ output/institute_attention/ >> "$LOG" 2>&1
git commit -m "auto: institute attention weekly $(date +%Y-%m-%d)" >> "$LOG" 2>&1
git push origin master >> "$LOG" 2>&1

echo "Done: $(date)" >> "$LOG"

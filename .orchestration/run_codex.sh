#!/usr/bin/env bash
# Usage: run_codex.sh <label> <prompt_file>
# Runs codex non-interactively on the project, logging full output + last message.
set -uo pipefail

PROJ="/Users/wangsiyuan/Documents/研究生/课程/军用情报大数据/情报工作台"
LABEL="$1"
PROMPT_FILE="$2"
LOG_DIR="$PROJ/.orchestration/logs"
LOG="$LOG_DIR/${LABEL}.log"
LAST="$LOG_DIR/${LABEL}.last.txt"
mkdir -p "$LOG_DIR"

echo "=== codex run [$LABEL] start ===" | tee "$LOG"
codex exec \
  --dangerously-bypass-approvals-and-sandbox \
  --skip-git-repo-check \
  -C "$PROJ" \
  -o "$LAST" \
  < "$PROMPT_FILE" 2>&1 | tee -a "$LOG"
CODE=${PIPESTATUS[0]}
echo "" | tee -a "$LOG"
echo "=== codex run [$LABEL] exit code: $CODE ===" | tee -a "$LOG"
exit $CODE

#!/usr/bin/env bash
# 全量回归测试（mock 数据源，无需网络）
set -e
cd "$(dirname "$0")/.."
# Existing integration fixtures intentionally exercise the trusted local disk mode.
export AGENT_LOCAL_PERSISTENCE=1
PASS=0; FAIL=0
for t in tests/test_*.py; do
  echo "=== $t ==="
  LOG_FILE="$(mktemp)"
  if python3 "$t" >"$LOG_FILE" 2>&1; then
    echo "PASS"
    PASS=$((PASS+1))
  else
    echo "FAIL"
    cat "$LOG_FILE"
    FAIL=$((FAIL+1))
  fi
  rm -f "$LOG_FILE"
done
echo
echo "通过 $PASS 组，失败 $FAIL 组"
[ "$FAIL" -eq 0 ]

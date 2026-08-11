#!/usr/bin/env bash
# 全量回归测试（mock 数据源，无需网络）
set -e
cd "$(dirname "$0")/.."
PASS=0; FAIL=0
for t in tests/test_*.py; do
  echo "=== $t ==="
  if python3 "$t" >/dev/null 2>&1; then
    echo "PASS"
    PASS=$((PASS+1))
  else
    echo "FAIL"
    FAIL=$((FAIL+1))
  fi
done
echo
echo "通过 $PASS 组，失败 $FAIL 组"
[ "$FAIL" -eq 0 ]

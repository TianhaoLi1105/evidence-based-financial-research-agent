"""Evaluation dataset and metric regression."""
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.getcwd())
from scripts.evaluate_agent import load_cases, summarize

cases = load_cases("evals/tool_routing_cases.jsonl")
assert len(cases) == 54
assert len({c["id"] for c in cases}) == 54
counts = Counter(t for c in cases for t in c["expected_tools"])
assert set(counts.values()) == {6}
assert len(counts) == 9
assert {c["lang"] for c in cases} == {"zh", "en"}

rows = [
    {"routing_ok": True, "end_to_end_ok": True, "latency_seconds": 1.0,
     "calls": [{"success": True}]},
    {"routing_ok": False, "end_to_end_ok": False, "latency_seconds": 2.0,
     "calls": [{"success": True}, {"success": False}]},
]
summary = summarize(rows)
assert summary["tool_routing_accuracy"] == 0.5
assert summary["tool_execution_success_rate"] == 2 / 3
assert summary["end_to_end_completion_rate"] == 0.5
assert summary["total_latency_seconds"] == 3.0

print("PASS evaluation dataset and metrics")

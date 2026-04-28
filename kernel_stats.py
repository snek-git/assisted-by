#!/usr/bin/env python3
"""Compute kernel-wide insertion/deletion totals since 2026-01-01.

Slow (walks every commit). Output is cached in kernel_stats.json so the page
build does not pay the cost on every run.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = sys.argv[1] if len(sys.argv) > 1 else "linux-full.git"
OUT = sys.argv[2] if len(sys.argv) > 2 else "kernel_stats.json"
SINCE = "2026-01-01"

raw = subprocess.check_output(
    ["git", "--git-dir", REPO, "log", f"--since={SINCE}", "--no-merges",
     "--shortstat", "--pretty=format:COMMIT"],
    text=True,
)

ins_total = del_total = commits = 0
boundary_artifacts = 0
for line in raw.splitlines():
    line = line.strip()
    if line == "COMMIT":
        commits += 1
        continue
    m = re.match(r"(\d+) files? changed(?:, (\d+) insertions?\(\+\))?(?:, (\d+) deletions?\(-\))?", line)
    if m:
        files = int(m.group(1))
        # Shallow-clone boundary commits diff against missing parents and report
        # the entire kernel tree as their diff. Real kernel commits never touch
        # this many files; skip them as artifacts.
        if files > 50000:
            boundary_artifacts += 1
            continue
        ins_total += int(m.group(2) or 0)
        del_total += int(m.group(3) or 0)

out = {
    "since": SINCE,
    "commits": commits,
    "insertions": ins_total,
    "deletions": del_total,
    "boundary_artifacts_skipped": boundary_artifacts,
}
Path(OUT).write_text(json.dumps(out, indent=2))
print(json.dumps(out, indent=2))

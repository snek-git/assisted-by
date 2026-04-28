#!/usr/bin/env python3
"""Combine merged + submitted parser output into the inline JSON the page consumes."""
import json
import subprocess

merged = json.load(open("data.json"))
lore = json.load(open("lore_data.json"))
kernel_stats = {}
try:
    kernel_stats = json.load(open("kernel_stats.json"))
except FileNotFoundError:
    pass

total_commits = int(subprocess.check_output(
    ["git", "--git-dir", "linux-shallow.git", "log",
     "--since=2026-01-01", "--oneline"], text=True
).count("\n"))

def to_dict(seq): return {k: v for k, v in seq}

merged_models = to_dict(merged["model_counts"])
sub_models = to_dict(lore["model_counts"])
merged_vendors = to_dict(merged["vendor_counts"])
sub_vendors = to_dict(lore["vendor_counts"])
merged_tools = to_dict(merged["tool_counts"])
sub_tools = to_dict(lore["tool_counts"])

model_lines = merged.get("model_lines", {})
vendor_lines = merged.get("vendor_lines", {})
tool_lines = merged.get("tool_lines", {})

def lines_for(d, k):
    e = d.get(k) or {}
    return {"ins": e.get("ins", 0), "del": e.get("del", 0)}

model_compare = []
for m in set(merged_models) | set(sub_models):
    s = sub_models.get(m, 0)
    mr = merged_models.get(m, 0)
    if s == 0 and mr == 0:
        continue
    vendor, name = m.split(" — ", 1) if " — " in m else (m, m)
    L = lines_for(model_lines, m)
    model_compare.append({"vendor": vendor, "model": name, "merged": mr, "submitted": s,
                          "ins": L["ins"], "del": L["del"]})
model_compare.sort(key=lambda r: (-r["merged"], -r["submitted"]))

vendor_compare = sorted(
    [dict({"vendor": v, "merged": merged_vendors.get(v, 0), "submitted": sub_vendors.get(v, 0)},
          **{"ins": lines_for(vendor_lines, v)["ins"], "del": lines_for(vendor_lines, v)["del"]})
     for v in set(merged_vendors) | set(sub_vendors)],
    key=lambda r: (-r["merged"], -r["submitted"]),
)

tool_compare = sorted(
    [dict({"tool": t, "merged": merged_tools.get(t, 0), "submitted": sub_tools.get(t, 0)},
          **{"ins": lines_for(tool_lines, t)["ins"], "del": lines_for(tool_lines, t)["del"]})
     for t in set(merged_tools) | set(sub_tools)],
    key=lambda r: (-r["merged"], -r["submitted"]),
)

web = {
    "window": {"since": "2026-01-01"},
    "kernel_total_commits": total_commits,
    "total_commits": merged["total_commits"],
    "total_tags": merged["total_tags"],
    "total_insertions": merged.get("total_insertions", 0),
    "total_deletions": merged.get("total_deletions", 0),
    "kernel_total_insertions": kernel_stats.get("insertions"),
    "kernel_total_deletions": kernel_stats.get("deletions"),
    "top_authors": merged["top_authors"],
    "top_committers": merged["top_committers"],
    "by_date": merged["by_date"],
    "by_date_lines": merged.get("by_date_lines", {}),
    "commits": [{"sha": c["sha"][:12], "subject": c["subject"], "author": c["author"],
                 "committer": c["committer"], "date": c["commit_date"][:10], "tags": c["tags"]}
                for c in merged["commits"]],
    "submitted": {
        "patch_messages_with_tag": lore["patch_messages_with_tag"],
        "unique_patches_with_tag": lore["unique_patches_with_tag"],
        "earliest": lore["earliest"],
        "latest": lore["latest"],
    },
    "model_compare": model_compare,
    "vendor_compare": vendor_compare,
    "tool_compare": tool_compare,
    "vendor_models_merged": merged["vendor_models"],
    "model_lines": model_lines,
}
with open("web_data.min.json", "w") as f:
    json.dump(web, f, separators=(",", ":"))
print(f"merged: {merged['total_commits']} commits, {merged['total_tags']} tags")
print(f"submitted: {lore['unique_patches_with_tag']} unique patches")
print(f"share of mainline: {merged['total_commits']/total_commits*100:.2f}%")

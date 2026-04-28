#!/usr/bin/env python3
"""Parse a lei mboxrd export of Assisted-by: matches into clean submission counts.

What we count: one entry per unique *patch instance*, where:
  - replies (Re:) are dropped
  - patchwork / test robots / syzbot / 0day are dropped
  - cover letters ([PATCH 0/N]) are dropped (they are meta, not patches)
  - patch series respins (v1, v2, v3 of the same base patch) collapse to one
  - the Assisted-by line must appear in non-quoted body text

Output: same shape as parse_mbox.py so the page consumes it identically.
"""
import email
import email.policy
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import timezone

from parse_commits import normalize

MBOX = sys.argv[1] if len(sys.argv) > 1 else "/tmp/lei.mbox"
OUT = sys.argv[2] if len(sys.argv) > 2 else "lore_data.json"

BOT_FROMS = {
    "patchwork", "kernel test robot", "lkp", "syzbot", "intel-lab-lkp",
    "0-day robot", "0day", "the 0-day robot",
}

def iter_messages(path):
    with open(path, "rt", encoding="utf-8", errors="replace") as f:
        chunk = []
        for line in f:
            if line.startswith("From ") and chunk:
                yield "".join(chunk)
                chunk = [line]
            else:
                chunk.append(line)
        if chunk:
            yield "".join(chunk)

def get_body(msg) -> str:
    if msg.is_multipart():
        out = []
        for p in msg.walk():
            if p.get_content_type() == "text/plain":
                try:
                    out.append(p.get_content())
                except Exception:
                    out.append(str(p.get_payload(decode=True) or "", errors="replace"))
        return "\n".join(out)
    try:
        return msg.get_content()
    except Exception:
        return str(msg.get_payload(decode=True) or "", errors="replace")

def canonical_subject(subj: str) -> str | None:
    """Return base patch title with [PATCH ...] and version markers stripped.
    Returns None for non-patches (replies, cover letters, mail without [PATCH]).
    """
    s = subj.strip()
    # drop replies
    if re.match(r"^(Re|Aw|Antw|Sv|Vs):", s, re.I):
        return None
    # find a [PATCH ...] bracket; keep only patches
    m = re.match(r"^\s*((?:\[[^\]]+\]\s*)+)(.*)$", s)
    if not m:
        return None
    brackets, rest = m.group(1), m.group(2).strip()
    if "PATCH" not in brackets.upper() and "RFC" not in brackets.upper():
        return None
    # find N/M; if 0/M it's a cover letter, drop
    nm = re.search(r"(\d+)\s*/\s*(\d+)", brackets)
    if nm and nm.group(1) == "0":
        return None
    n_of_m = f" {nm.group(1)}/{nm.group(2)}" if nm else ""
    return (rest + n_of_m).strip().lower()

def sender_email(frm: str) -> str:
    m = re.search(r"<([^>]+)>", frm)
    addr = (m.group(1) if m else frm).strip().lower()
    return addr

vendor_counts = Counter()
model_counts = Counter()
tool_counts = Counter()
vendor_models = defaultdict(Counter)
authors = Counter()
by_date = defaultdict(int)

groups = {}  # (canonical_subject, sender_local) -> latest message info

total = 0
non_patch = 0
bot_dropped = 0
quote_only = 0
no_tag = 0
tag_in_msg = 0

for raw in iter_messages(MBOX):
    total += 1
    try:
        msg = email.message_from_string(raw, policy=email.policy.default)
    except Exception:
        continue
    subj = (msg.get("Subject") or "").strip()
    canon = canonical_subject(subj)
    if not canon:
        non_patch += 1
        continue
    frm = msg.get("From") or ""
    sender = sender_email(frm)
    sender_name = re.sub(r"\s*<.*?>", "", frm).strip().strip('"')
    if any(b in sender_name.lower() for b in BOT_FROMS):
        bot_dropped += 1
        continue
    if "patchwork" in sender or "0day" in sender or "intel-lab-lkp" in sender:
        bot_dropped += 1
        continue

    body = get_body(msg)
    nonquoted = "\n".join(l for l in body.splitlines() if not l.lstrip().startswith(">"))
    tags = re.findall(r"^\s*Assisted-by:\s*(.+?)\s*$", nonquoted, re.M | re.I)
    if not tags:
        if re.search(r"^\s*>+.*Assisted-by:", body, re.M):
            quote_only += 1
        else:
            no_tag += 1
        continue
    tag_in_msg += 1

    date_hdr = msg.get("Date") or ""
    try:
        dt = email.utils.parsedate_to_datetime(date_hdr)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        day = dt.astimezone(timezone.utc).strftime("%Y-%m-%d")
    except Exception:
        day = None
    if not day or day < "2026-01-01":
        continue

    key = (canon, sender)
    prev = groups.get(key)
    if prev is None or day > prev["day"]:
        groups[key] = {"day": day, "tags": tags, "sender_name": sender_name, "subject": subj}

# now aggregate
for (canon, sender), g in groups.items():
    by_date[g["day"]] += 1
    if g["sender_name"]:
        authors[g["sender_name"]] += 1
    seen = set()
    for tag in g["tags"]:
        n = normalize(tag)
        v, mod, tool = n["vendor"], n["model"], n["tool"]
        key = (v, mod, tool)
        if key in seen:
            continue
        seen.add(key)
        vendor_counts[v] += 1
        model_counts[f"{v} — {mod}"] += 1
        tool_counts[tool] += 1
        vendor_models[v][mod] += 1

dates = sorted(by_date.keys())
out = {
    "input_messages": total,
    "non_patch_or_reply": non_patch,
    "bot_dropped": bot_dropped,
    "quote_only_skipped": quote_only,
    "patch_messages_with_tag": tag_in_msg,
    "unique_patches_with_tag": len(groups),
    "earliest": dates[0] if dates else None,
    "latest": dates[-1] if dates else None,
    "by_date": dict(sorted(by_date.items())),
    "vendor_counts": vendor_counts.most_common(),
    "model_counts": model_counts.most_common(),
    "tool_counts": tool_counts.most_common(),
    "vendor_models": {v: dict(m.most_common()) for v, m in vendor_models.items()},
    "top_authors": authors.most_common(15),
}
open(OUT, "w").write(json.dumps(out, indent=2))
print(json.dumps({k: v for k, v in out.items()
                  if k not in ("by_date", "vendor_models", "top_authors")},
                 indent=2, ensure_ascii=False))

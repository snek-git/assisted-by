#!/usr/bin/env python3
"""Parse Assisted-by: tags from the kernel git log into structured JSON for the page."""
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path


def claude_model(raw: str) -> str:
    s = raw.lower()
    if "noreply@anthropic" in s or s in {"claude", ""}:
        return "unspecified"
    fam = None
    if "opus" in s: fam = "Opus"
    elif "sonnet" in s: fam = "Sonnet"
    elif "haiku" in s: fam = "Haiku"
    ver = re.search(r"(\d)[.\-_](\d)", s)
    if fam and ver:
        return f"{fam} {ver.group(1)}.{ver.group(2)}"
    if fam:
        return fam
    return raw.strip()


def codex_model(raw: str) -> str:
    s = raw.lower().replace(" ", "")
    m = re.search(r"gpt-?(\d)[.\-_]?(\d)?", s)
    if m:
        return f"GPT-{m.group(1)}" + (f".{m.group(2)}" if m.group(2) else "")
    return raw.strip()


def gemini_model(raw: str) -> str:
    s = raw.lower()
    m = re.search(r"(\d)[.\-_](\d)", s)
    if m:
        return f"Gemini {m.group(1)}.{m.group(2)}" + (" Pro" if "pro" in s else "")
    return raw.strip()


def deepseek_model(raw: str) -> str:
    m = re.search(r"v(\d)[.\-_]?(\d)?", raw.lower())
    if m:
        return f"DeepSeek V{m.group(1)}" + (f".{m.group(2)}" if m.group(2) else "")
    return raw.strip() or "unspecified"


def underlying_model_and_vendor(rest: str) -> tuple[str, str]:
    """Given the value after a wrapper tool like 'Cursor:', return (vendor, model)."""
    s = rest.lower()
    if "claude" in s: return ("Anthropic", claude_model(rest))
    if "gpt" in s or "codex" in s: return ("OpenAI", codex_model(rest))
    if "gemini" in s: return ("Google", gemini_model(rest))
    if "deepseek" in s: return ("DeepSeek", deepseek_model(rest))
    if "glm" in s: return ("Z.ai", glm_model(rest))
    if rest.lower().startswith("composer"): return ("Cursor (in-house)", rest.strip())
    return ("Unknown", rest.strip() or "unspecified")


def glm_model(raw: str) -> str:
    m = re.search(r"glm[-\s]?(\d)[.\-_]?(\d)?", raw.lower())
    if m:
        return f"GLM-{m.group(1)}" + (f".{m.group(2)}" if m.group(2) else "")
    return raw.strip()


def normalize(tag: str) -> dict:
    """Classify a single Assisted-by value into vendor / model / tool.

    vendor = the lab that trained the model (Anthropic, OpenAI, Google, ...)
    model  = canonical model name (Opus 4.6, GPT-5.4, Gemini 3.1 Pro, ...)
    tool   = how it was invoked (Direct, Claude Code, Cursor, Copilot, ...)
    """
    t = tag.strip()
    low = t.lower()
    if "clanker" in low or low.startswith("gkh_") or low.startswith("gregkh_"):
        return {"vendor": "Greg KH (protest)", "model": t, "tool": "Greg KH protest"}
    if low.startswith("claude code"):
        m = re.search(r":\s*(.+)", t)
        return {"vendor": "Anthropic", "model": claude_model(m.group(1) if m else ""), "tool": "Claude Code"}
    if low.startswith("claude") or low.startswith("anthropic"):
        m = re.search(r":\s*(.+)", t)
        rest = m.group(1) if m else t.split(",")[0].strip()
        return {"vendor": "Anthropic", "model": claude_model(rest), "tool": "Direct / API"}
    if low.startswith("codex") or low.startswith("openai"):
        m = re.search(r":\s*(.+)", t)
        return {"vendor": "OpenAI", "model": codex_model(m.group(1) if m else ""), "tool": "Codex"}
    if low.startswith("gemini") or low.startswith("antigravity"):
        m = re.search(r":\s*(.+)", t)
        tool = "Antigravity" if low.startswith("antigravity") else "Direct / API"
        return {"vendor": "Google", "model": gemini_model(m.group(1) if m else ""), "tool": tool}
    if (low.startswith("github copilot") or low.startswith("github-copilot")
            or low.startswith("githubcopilot") or low.startswith("copilot")):
        m = re.search(r":\s*(.+)", t)
        rest = (m.group(1).strip() if m else "")
        vendor, model = underlying_model_and_vendor(rest) if rest else ("Unknown", "unspecified")
        return {"vendor": vendor, "model": model, "tool": "GitHub Copilot"}
    if low.startswith("composer") or low.startswith("cursor"):
        m = re.search(r":\s*(.+)", t)
        rest = m.group(1).strip() if m else ""
        if not rest:
            return {"vendor": "Unknown", "model": "unspecified", "tool": "Cursor"}
        if rest.lower().startswith("composer"):
            return {"vendor": "Cursor (in-house)", "model": rest, "tool": "Cursor"}
        vendor, model = underlying_model_and_vendor(rest)
        return {"vendor": vendor, "model": model, "tool": "Cursor"}
    if "deepseek" in low:
        m = re.search(r":\s*(.+)", t)
        rest = m.group(1).strip() if m else low
        return {"vendor": "DeepSeek", "model": deepseek_model(rest), "tool": "Direct / API"}
    if low.startswith("opencode"):
        m = re.search(r":\s*(.+)", t)
        rest = m.group(1).strip() if m else ""
        if not rest:
            return {"vendor": "Unknown", "model": "unspecified", "tool": "OpenCode"}
        vendor, model = underlying_model_and_vendor(rest)
        return {"vendor": vendor, "model": model, "tool": "OpenCode"}
    if "glm-" in low or low.startswith("glm"):
        return {"vendor": "Z.ai", "model": glm_model(t), "tool": "Direct / API"}
    if low.startswith("amazon q") or low.startswith("amazonq"):
        rest = t.split(":", 1)[-1].strip() if ":" in t else "unspecified"
        return {"vendor": "Amazon", "model": rest or "unspecified", "tool": "Amazon Q"}
    if low.startswith("kiro"):
        m = re.search(r":\s*(.+)", t)
        rest = m.group(1).strip() if m else ""
        if not rest:
            return {"vendor": "Unknown", "model": "unspecified", "tool": "Kiro"}
        vendor, model = underlying_model_and_vendor(rest)
        return {"vendor": vendor, "model": model, "tool": "Kiro"}
    if low.startswith("cody"):
        m = re.search(r":\s*(.+)", t)
        rest = m.group(1).strip() if m else ""
        if not rest:
            return {"vendor": "Unknown", "model": "unspecified", "tool": "Cody"}
        vendor, model = underlying_model_and_vendor(rest)
        return {"vendor": vendor, "model": model, "tool": "Cody"}
    if low.startswith("azure"):
        m = re.search(r":\s*(.+)", t)
        return {"vendor": "OpenAI", "model": codex_model(m.group(1) if m else ""), "tool": "Azure"}
    if low.startswith("bynario"):
        return {"vendor": "Unknown", "model": "Bynario AI", "tool": "Bynario AI"}
    if low.startswith("unnamed"):
        m = re.search(r":\s*(.+)", t)
        rest = m.group(1).strip() if m else ""
        if not rest:
            return {"vendor": "Unknown", "model": "unspecified", "tool": "Unnamed"}
        vendor, model = underlying_model_and_vendor(rest)
        return {"vendor": vendor, "model": model, "tool": "Unnamed"}
    return {"vendor": "Unknown", "model": t, "tool": "Unknown"}


def main():
    repo = sys.argv[1] if len(sys.argv) > 1 else "linux-shallow.git"
    out_path = sys.argv[2] if len(sys.argv) > 2 else "data.json"
    SEP = "<<<COMMIT>>>"
    FMT = f"{SEP}%H%n%an%n%ae%n%cn%n%ce%n%aI%n%cI%n%s%n%b"
    # request --shortstat too; the diffstat line lands between the pretty body and the next commit.
    raw = subprocess.check_output(
        ["git", "--git-dir", repo, "log", "--all", "--no-merges",
         "--grep=Assisted-by:", "-i", "--shortstat", f"--pretty=format:{FMT}"],
        text=True,
    )
    commits = []
    for chunk in raw.split(SEP):
        chunk = chunk.strip("\n")
        if not chunk:
            continue
        lines = chunk.split("\n")
        sha, an, ae, cn, ce, ad, cd, subj = lines[:8]
        rest = lines[8:]
        # last non-empty line in rest is the diffstat if --shortstat is on
        ins = dele = 0
        body_lines = rest
        for i in range(len(rest) - 1, -1, -1):
            line = rest[i].strip()
            if not line:
                continue
            m = re.match(r"\d+ files? changed(?:, (\d+) insertions?\(\+\))?(?:, (\d+) deletions?\(-\))?", line)
            if m:
                ins = int(m.group(1) or 0)
                dele = int(m.group(2) or 0)
                body_lines = rest[:i]
            break
        body = "\n".join(body_lines)
        tags = re.findall(r"^\s*Assisted-by:\s*(.+?)\s*$", body, re.M | re.I)
        if not tags:
            continue
        commits.append({
            "sha": sha,
            "author": an, "author_email": ae,
            "committer": cn, "committer_email": ce,
            "author_date": ad, "commit_date": cd,
            "subject": subj,
            "tags": tags,
            "insertions": ins,
            "deletions": dele,
        })

    vendor_counts = Counter()
    model_counts = Counter()
    tool_counts = Counter()
    vendor_models = defaultdict(Counter)
    model_tools = defaultdict(Counter)
    vendor_lines = defaultdict(lambda: [0, 0])
    model_lines = defaultdict(lambda: [0, 0])
    tool_lines = defaultdict(lambda: [0, 0])
    authors = Counter()
    committers = Counter()
    by_date = defaultdict(int)
    by_date_lines = defaultdict(lambda: [0, 0])

    for c in commits:
        ins, dele = c["insertions"], c["deletions"]
        seen_v, seen_m, seen_t = set(), set(), set()
        for tag in c["tags"]:
            n = normalize(tag)
            v, mod, tool = n["vendor"], n["model"], n["tool"]
            vendor_counts[v] += 1
            model_counts[f"{v} — {mod}"] += 1
            tool_counts[tool] += 1
            vendor_models[v][mod] += 1
            model_tools[f"{v} — {mod}"][tool] += 1
            # Lines: attribute once per commit per (vendor, model, tool) bucket.
            # Multi-tag commits attribute to each disclosed bucket; cross-bucket
            # totals can exceed the global total by design.
            if v not in seen_v:
                vendor_lines[v][0] += ins; vendor_lines[v][1] += dele; seen_v.add(v)
            mkey = f"{v} — {mod}"
            if mkey not in seen_m:
                model_lines[mkey][0] += ins; model_lines[mkey][1] += dele; seen_m.add(mkey)
            if tool not in seen_t:
                tool_lines[tool][0] += ins; tool_lines[tool][1] += dele; seen_t.add(tool)
        authors[c["author"]] += 1
        committers[c["committer"]] += 1
        day = c["commit_date"][:10]
        by_date[day] += 1
        by_date_lines[day][0] += ins
        by_date_lines[day][1] += dele

    out = {
        "total_commits": len(commits),
        "total_tags": sum(vendor_counts.values()),
        "total_insertions": sum(c["insertions"] for c in commits),
        "total_deletions": sum(c["deletions"] for c in commits),
        "vendor_counts": vendor_counts.most_common(),
        "vendor_models": {v: dict(m.most_common()) for v, m in vendor_models.items()},
        "vendor_lines": {v: {"ins": l[0], "del": l[1]} for v, l in vendor_lines.items()},
        "model_counts": model_counts.most_common(),
        "model_lines": {m: {"ins": l[0], "del": l[1]} for m, l in model_lines.items()},
        "tool_counts": tool_counts.most_common(),
        "tool_lines": {t: {"ins": l[0], "del": l[1]} for t, l in tool_lines.items()},
        "model_tools": {m: dict(t.most_common()) for m, t in model_tools.items()},
        "top_authors": authors.most_common(15),
        "top_committers": committers.most_common(15),
        "by_date": dict(sorted(by_date.items())),
        "by_date_lines": {d: {"ins": l[0], "del": l[1]} for d, l in sorted(by_date_lines.items())},
        "commits": commits,
    }
    Path(out_path).write_text(json.dumps(out, indent=2))
    print(f"wrote {out_path}: {len(commits)} commits, {sum(vendor_counts.values())} tags")


if __name__ == "__main__":
    main()

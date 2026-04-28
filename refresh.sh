#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

REPO=linux-full.git

# 1. fast-forward the kernel clone
if [ ! -d "$REPO" ]; then
  git clone --bare --shallow-since="2026-01-01" --no-tags --single-branch \
    https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git "$REPO"
else
  git --git-dir="$REPO" fetch --shallow-since="2026-01-01" --no-tags origin master:master || true
fi

# 2. pull fresh submitted set from lore via lei
lei q -d mid -o - -f mboxrd 'b:"Assisted-by:" AND d:20260101..' > /tmp/lei.mbox

# 3. parse merged + submitted sides
python3 parse_commits.py "$REPO" data.json
python3 parse_lei.py /tmp/lei.mbox lore_data.json

# 4. compute kernel-wide line totals (slow; cached in kernel_stats.json)
python3 kernel_stats.py "$REPO" kernel_stats.json

# 5. assemble the web payload
python3 build_data.py

# 6. inline the JSON into index.html
python3 - <<'PY'
import re
data = open("web_data.min.json").read()
html = open("index.html").read()
new = re.sub(
    r'(<script id="data" type="application/json">)(.*?)(</script>)',
    lambda m: m.group(1) + data + m.group(3),
    html, count=1, flags=re.S,
)
open("index.html", "w").write(new)
PY
echo "refresh complete: $(date -u +%FT%TZ)"

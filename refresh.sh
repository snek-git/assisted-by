#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# 1. fast-forward the shallow clone
git --git-dir=linux-shallow.git fetch --shallow-since="2026-01-01" origin master:master

# 2. pull fresh submitted set from lore via lei
lei q -d mid -o - -f mboxrd 'b:"Assisted-by:" AND d:20260101..' > /tmp/lei.mbox

# 3. parse both sides
python3 parse_commits.py linux-shallow.git data.json
python3 parse_lei.py /tmp/lei.mbox lore_data.json

# 4. assemble the web payload
python3 build_data.py

# 5. inline the JSON into index.html
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

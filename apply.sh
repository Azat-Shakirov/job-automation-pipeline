#!/usr/bin/env bash
# apply.sh — submit jd.txt to the tailor server and print the Drive link.
# Usage:
#   1. Paste the job description into ~/job-automation/jd.txt
#   2. ./apply.sh

set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
JD_FILE="$DIR/jd.txt"
ENDPOINT="http://localhost:5001/tailor"

if [ ! -f "$JD_FILE" ]; then
    echo "ERROR: $JD_FILE not found. Create it and paste the job description in." >&2
    exit 1
fi

if [ ! -s "$JD_FILE" ]; then
    echo "ERROR: $JD_FILE is empty." >&2
    exit 1
fi

# Check server is up
if ! curl -s "$ENDPOINT/../health" | grep -q '"ok"' 2>/dev/null; then
    if ! curl -s "http://localhost:5001/health" | grep -q '"ok"' 2>/dev/null; then
        echo "ERROR: Server is not running. Start it with: ./start.sh" >&2
        exit 1
    fi
fi

export JD_FILE

echo "Submitting $(wc -c < "$JD_FILE" | tr -d ' ') bytes from jd.txt..."

# Use Python to safely encode the file as JSON and POST it.
# This handles all special characters: quotes, apostrophes, newlines, backslashes.
python3 - <<'PYEOF'
import sys, json, urllib.request, urllib.error
from pathlib import Path

import os
jd_file = Path(os.environ["JD_FILE"])

jd_text = jd_file.read_text(encoding="utf-8").strip()
if not jd_text:
    print("ERROR: jd.txt is empty.", file=sys.stderr)
    sys.exit(1)

payload = json.dumps({"jd": jd_text}).encode("utf-8")

req = urllib.request.Request(
    "http://localhost:5001/tailor",
    data=payload,
    headers={"Content-Type": "application/json"},
    method="POST",
)

try:
    with urllib.request.urlopen(req, timeout=120) as resp:
        result = json.loads(resp.read())
except urllib.error.HTTPError as e:
    body = e.read().decode()
    try:
        msg = json.loads(body).get("error", body)
    except Exception:
        msg = body
    print(f"ERROR: {e.code} {e.reason} — {msg}", file=sys.stderr)
    sys.exit(1)

company = result.get("company", "unknown")
link = result.get("drive_link", "")
print(f"Company : {company}")
print(f"Drive   : {link}")
PYEOF

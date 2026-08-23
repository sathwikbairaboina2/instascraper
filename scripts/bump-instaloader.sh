#!/usr/bin/env bash
# Upgrade the one dependency that breaks on Instagram's schedule.
#
#   scripts/bump-instaloader.sh 4.15.0     bump to a version
#   scripts/bump-instaloader.sh --check    canary only, change nothing
#
# The gate is the adapter's contract tests plus the live canary. If the canary
# cannot run (no credentials) the script says so and refuses to call the bump
# verified -- a green contract suite only proves the parsers still agree with
# the checked-in fixtures, not with Instagram.
set -euo pipefail

cd "$(dirname "$0")/.."

PY=.venv/Scripts/python.exe
[ -x "$PY" ] || PY=.venv/bin/python
[ -x "$PY" ] || { echo "No virtualenv at .venv - see README."; exit 1; }

REQ=api/requirements.txt
CONTRACT="tests/test_adapter_parse.py tests/test_ig_contract.py"

current() { grep -oE '^instaloader==[0-9.]+' "$REQ" | cut -d= -f3; }

canary() {
  local label="$1"
  if ! grep -qE '^IG_USERNAME=.+' .env 2>/dev/null; then
    echo "  canary SKIPPED ($label): IG_USERNAME not set in .env"
    return 2
  fi
  if (cd api && "../$PY" -m pytest -m live -q >/dev/null 2>&1); then
    echo "  canary PASS ($label)"
    return 0
  fi
  echo "  canary FAIL ($label)"
  return 1
}

contract() {
  local label="$1"
  if (cd api && "../$PY" -m pytest $CONTRACT -q >/dev/null 2>&1); then
    echo "  contract PASS ($label)"
    return 0
  fi
  echo "  contract FAIL ($label)"
  return 1
}

echo "instaloader currently pinned at $(current)"

if [ "${1:-}" = "--check" ] || [ $# -eq 0 ]; then
  echo "Checking the current pin only. Pass a version to bump."
  contract "current" || exit 1
  canary "current" || true
  exit 0
fi

TARGET="$1"
echo "Target: $TARGET"

echo "1/5 baseline contract tests"
contract "before" || { echo "Already failing before the bump. Fix that first."; exit 1; }

echo "2/5 rewriting the pin"
cp "$REQ" "$REQ.bak"
"$PY" - "$REQ" "$TARGET" <<'PYEOF'
import re, sys
path, target = sys.argv[1], sys.argv[2]
text = open(path, encoding="utf8").read()
new, n = re.subn(r"^instaloader==[0-9.]+$", f"instaloader=={target}", text, flags=re.M)
if n != 1:
    sys.exit(f"expected exactly one instaloader pin, found {n}")
open(path, "w", encoding="utf8").write(new)
print(f"  pinned instaloader=={target}")
PYEOF

restore() {
  echo "  restoring $REQ"
  mv "$REQ.bak" "$REQ"
  "$PY" -m pip install --quiet -r "$REQ"
}

echo "3/5 installing"
if ! "$PY" -m pip install --quiet -r "$REQ"; then
  echo "install failed"
  restore
  exit 1
fi

echo "4/5 contract tests on the new version"
if ! contract "after"; then
  echo
  echo "The adapter no longer agrees with its fixtures on $TARGET."
  echo "Look at api/app/ig/adapter.py -- classify() and post_to_igpost() first."
  restore
  exit 1
fi

echo "5/5 live canary"
set +e
canary "after"
canary_status=$?
set -e

rm -f "$REQ.bak"
echo
case $canary_status in
  0) echo "VERIFIED: contract and canary both pass on $TARGET. Commit the pin." ;;
  2) echo "PARTIAL: contract passes on $TARGET, canary not run (no credentials)."
     echo "Do not call this verified until the canary runs against real Instagram." ;;
  *) echo "CANARY FAILED on $TARGET. The pin is still changed on disk."
     echo "Either fix api/app/ig/adapter.py or: git checkout $REQ && $PY -m pip install -r $REQ"
     exit 1 ;;
esac

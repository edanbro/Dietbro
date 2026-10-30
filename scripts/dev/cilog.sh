#!/bin/sh
# The errors from every failed check run on a commit: Playwright failures, assertion and
# Python errors, without the rest of the log.
#   sh scripts/dev/cilog.sh SHA
D=$(dirname "$0")
T=$(sh "$D/token.sh")
for id in $(sh "$D/ghapi.sh" GET "/repos/edanbro/Dietbro/commits/$1/check-runs" |
  python -c "import json,sys;[print(c['id']) for c in json.load(sys.stdin)['check_runs'] if c['conclusion'] not in ('success','skipped','neutral',None)]"); do
  echo "=== job $id"
  curl -sL -m 60 -H "Authorization: Bearer $T" "https://api.github.com/repos/edanbro/Dietbro/actions/jobs/$id/logs" |
    sed 's/^[0-9TZ:.-]* //' |
    grep -E '✘|Error|error:|FAIL|failed|assert|Expected|Received|^E  ' | grep -v 'pnpm v1[01]' | head -60
done

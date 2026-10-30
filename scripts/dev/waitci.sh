#!/bin/sh
# Wait until every check run on a commit has finished, then print one name=conclusion per check.
# Exits 0 only when all of them passed (or were skipped).
#   sh scripts/dev/waitci.sh SHA
D=$(dirname "$0")
runs() { sh "$D/ghapi.sh" GET "/repos/edanbro/Dietbro/commits/$1/check-runs"; }
until runs "$1" | python -c "import json,sys;r=json.load(sys.stdin)['check_runs'];sys.exit(0 if r and all(c['status']=='completed' for c in r) else 1)"; do
  sleep 20
done
runs "$1" | python -c "import json,sys;r=json.load(sys.stdin)['check_runs'];print(' | '.join(f\"{c['name'][:24]}={c['conclusion']}\" for c in r));sys.exit(0 if all(c['conclusion'] in ('success','skipped','neutral') for c in r) else 1)"

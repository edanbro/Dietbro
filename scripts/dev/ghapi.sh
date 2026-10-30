#!/bin/sh
# GitHub REST call with git's stored credential:
#   sh scripts/dev/ghapi.sh METHOD PATH [json-file]
#   sh scripts/dev/ghapi.sh GET /repos/edanbro/Dietbro/pulls
T=$(sh "$(dirname "$0")/token.sh")
set -- "$1" "$2" "$3"
if [ -n "$3" ]; then
  curl -s -m 60 -X "$1" -H "Authorization: Bearer $T" -H "Accept: application/vnd.github+json" "https://api.github.com$2" -d @"$3"
else
  curl -s -m 60 -X "$1" -H "Authorization: Bearer $T" -H "Accept: application/vnd.github+json" "https://api.github.com$2"
fi

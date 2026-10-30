#!/bin/sh
# Print the GitHub token git already stores (credential manager), for the other scripts here to
# pass on. Never echo it to a terminal or a log.
printf 'protocol=https\nhost=github.com\n\n' |
  GIT_TERMINAL_PROMPT=0 GCM_INTERACTIVE=never timeout 30 git credential fill 2>/dev/null |
  sed -n 's/^password=//p'

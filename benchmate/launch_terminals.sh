#!/bin/bash
# Opens five macOS Terminal windows, each: cd benchmate, activate venv, source env.sh, start claude.
# Order matters: T5 first (everyone imports its telemetry), then T4, T1, T3, T2.
DIR="$(cd "$(dirname "$0")" && pwd)"
for T in 5 4 1 3 2; do
  osascript <<APPLESCRIPT
tell application "Terminal"
  activate
  do script "cd '$DIR' && source .venv/bin/activate && source env.sh && printf '\\\\033]0;BenchMate T$T\\\\007' && echo '=== T$T: paste the text of launch_T$T.txt as the first message ===' && claude"
end tell
APPLESCRIPT
  sleep 1
done

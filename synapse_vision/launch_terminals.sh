#!/bin/bash
# Opens macOS Terminal windows for Synapse Vision. Usage: ./launch_terminals.sh [T numbers...]  (default: 4 1 2 3 5)
DIR="$(cd "$(dirname "$0")" && pwd)"
for T in ${@:-4 1 2 3 5}; do
  osascript <<APPLESCRIPT
tell application "Terminal"
  activate
  do script "cd '$DIR' && source .venv/bin/activate && source env.sh && printf '\\\\033]0;Synapse T$T\\\\007' && echo '=== T$T: paste launch_T$T.txt as the first message ===' && claude"
end tell
APPLESCRIPT
  sleep 1
done

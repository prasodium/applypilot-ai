#!/usr/bin/env bash
# Deletes the local database, uploaded files and temporary files in backend/data. Asks for confirmation. Touches nothing else.
set -euo pipefail
cd "$(dirname "$0")/.."
DIR="$(pwd)/backend/data"
case "$DIR" in */applypilot-ai/backend/data) ;; *) echo "Refusing: unexpected path $DIR"; exit 1 ;; esac
[ -d "$DIR" ] || { echo "Nothing to reset ($DIR does not exist)."; exit 0; }
echo "This permanently deletes: $DIR"
read -r -p 'Type RESET to continue: ' answer
[ "$answer" = "RESET" ] || { echo "Cancelled."; exit 1; }
rm -rf "$DIR"
echo "Local data deleted. It is recreated on next start."

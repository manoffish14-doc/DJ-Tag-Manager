#!/bin/bash
# Detached macOS updater. No Python or developer tools required.
set -euo pipefail
DEST="$1"
STAGED="$2"
PID="$3"
LOG="$4"
BACKUP="${DEST%.app}.previous.app"
TMP="${DEST%.app}.incoming.app"
exec >>"$LOG" 2>&1
printf 'Updater started: %s\n' "$(date)"
for ((i=0; i<120; i++)); do
  if ! kill -0 "$PID" 2>/dev/null; then break; fi
  sleep 0.5
done
if kill -0 "$PID" 2>/dev/null; then echo 'App did not exit; cancelling.'; exit 1; fi
if [[ ! -d "$DEST/Contents" || ! -d "$STAGED/Contents" ]]; then
  echo 'Missing source or destination bundle; cancelling.'; exit 1
fi
if [[ -e "$BACKUP" || -e "$TMP" ]]; then
  echo 'Previous backup or incomplete update exists; refusing to overwrite.'; exit 1
fi
# Copy to same directory so the final rename is atomic on the same filesystem.
/usr/bin/ditto "$STAGED" "$TMP"
if [[ ! -f "$TMP/Contents/Info.plist" ]]; then
  echo 'Staged app failed validation.'; rm -rf "$TMP"; exit 1
fi
mv "$DEST" "$BACKUP"
if ! mv "$TMP" "$DEST"; then
  echo 'Install move failed; restoring backup.'
  if [[ ! -e "$DEST" ]]; then mv "$BACKUP" "$DEST"; fi
  exit 1
fi
if ! /usr/bin/open "$DEST"; then
  echo 'Launch failed; restoring backup.'
  mv "$DEST" "${DEST%.app}.failed.app"
  mv "$BACKUP" "$DEST"
  /usr/bin/open "$DEST" || true
  exit 1
fi
echo 'Update installed; previous app retained at:' "$BACKUP"

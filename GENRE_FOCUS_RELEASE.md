# Genre Cleanup focused workspace

- Hides library-only import/lookup toolbar, drop hint, and raw JSON metadata panel while Genre Cleanup is open.
- Restores those widgets when returning to Library.
- Collapses the existing waveform player in Genre Cleanup; click the Music Player strip to expand it. Playback is not restarted.
- Genre columns expand vertically with the viewport and are sized for approximately four visible families; scroll horizontally for more.
- Genre selection, immediate Save Changes, Composer overwrite, backup and history behavior remain unchanged.

This change has automated test coverage for existing logic but requires a macOS UI smoke test.

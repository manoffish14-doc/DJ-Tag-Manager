# Phase 3 cleanup extension (development)

Added:
- Similar-title duplicate review, separate from exact duplicate review, with same-artist and clean/explicit/unknown separation. Similar matches require an additional confirmation before archiving; similarity is not proof that two audio recordings are identical. No files are deleted.
- Name Cleanup external-folder scan with optional recursion, incremental file size/mtime cache, forced rescan, proposal preview, and explicit import of selected tracks. Scanning does not change music files.
- Genre organizational group renaming and drag-to-group assignment, in addition to existing multi-select grouping and safe-write rename/history.
- Six regression tests for the new cleanup engine functionality.

Limitations and verification:
- Genre drag-to-group is a Tkinter interaction and has not been verified on macOS. The Organize Labels button is a fallback.
- Similarity uses normalized titles, not acoustic fingerprints; manually audition every candidate before archiving.
- External scan caches successful file signatures. If you dismiss the scan without importing, unchanged files will be skipped on the next scan unless Force rescan is checked.
- External-folder scanning runs on the GUI thread, so a very large library can temporarily block the window. A later queue integration should make this asynchronous.
- Native macOS app and live provider integrations remain untested here.
- Serato write interoperability remains deferred.

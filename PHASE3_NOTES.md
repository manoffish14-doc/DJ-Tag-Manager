# Phase 3 — Cleanup integration (development build)

This package extends the actual Phase 2 application, not a standalone mockup.

## Integrated in this checkpoint

- Duplicate Finder: sortable full-width table; exact normalized artist/title grouping; separate clean, explicit, and unknown versions; bitrate/play-count/size Keep recommendation; persistent Keep and Reviewed decisions; archive only after review and at least one Keep; explicit archive-folder choice, collision rejection, manifest and restore. **No deletion.**
- Genre Cleanup: group assignments (including user-entered new group names) saved in settings without modifying files; known spelling aliases grouped; batch genre changes with preview confirmation and optional original genre into Composer; safe_write recovery copies and history restore.
- Name Cleanup: conservative whitespace and featured-artist formatting, existing title/artist suggestions, search, field filters, sorting, confidence, dismiss, proposal edits, stage selected or all visible. Staged edits require Save Changes to write.
- New pure cleanup engine and seven regression tests, alongside the original sixteen tests.

## Known gaps / important limitations

- **Not the full original 15-feature release.** Genre groups are still presented using a list and side controls, not the fully specified drag-and-drop visual grouping canvas. Duplicate similar/fuzzy matches are not implemented; current grouping is exact normalized artist/title with version separation. Name Cleanup does not yet offer a full recursive external-folder import and incremental scan workflow.
- Archive restore uses a manifest and collision protection, but library reimport depends on the existing import code.
- No Serato proprietary metadata writes; Serato interoperability remains deferred.
- Only Linux-side Python tests have run. macOS UI, audio metadata formats, and real-world music libraries require Mac testing with copied files.
- Do not use this development build on your only copies of tracks.

## Test

`python -m unittest discover -s tests -v`

GitHub Actions contains the macOS application packaging workflow.

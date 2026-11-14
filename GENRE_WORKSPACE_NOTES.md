# Genre Cleanup workspace pass

- Uses the latest automatic-genre-lookup source as its base; v2 is untouched.
- Genre Cleanup now replaces the library table inside the main window; Back to Library restores it.
- Search, group counts, genre counts, multi-select and affected-track previews.
- Built-in and custom groups; add organizational genre labels, rename custom groups, move labels, and drag selected labels onto a group.
- Grouping is stored in application preferences, not the audio file's Label field.
- Rename/merge requires a confirmation preview. Writes use existing metadata_recovery and genre_cleanup_written history; Composer preservation is optional and explicitly warns before overwrite.
- History / Restore uses the existing history dialog.
- Known limits: native macOS visual QA and full GUI automation have not been run; drag-and-drop requires validation on macOS. Genre history remains a separate dialog.

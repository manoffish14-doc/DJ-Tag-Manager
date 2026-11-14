> **Phase 4 checkpoint:** See [PHASE4_NOTES.md](PHASE4_NOTES.md) for implementation and known limitations.

> Phase 3 cleanup integration: see [PHASE3_NOTES.md](PHASE3_NOTES.md) for implemented behavior and limitations.

# DJ Tag Manager v3.1 — Integrated Development Build

This is a **GitHub-ready experimental source build**, not a completed or Serato-certified production release. It builds a separate `DJ Tag Manager v3 Combined Dev.app` with its own macOS bundle ID and **separate Application Support directory**, leaving v2 installed and its preferences intact. **Use copied audio files only.**

## Added in this iteration

- **RGB audio waveform**: cached three-band spectral waveform (bass red, mid green, treble blue), compact player display, expandable zoomable waveform, time counter, click-to-seek on supported macOS `afplay` versions, volume control applied on playback start, and app-local cue markers. Audio analysis runs off the Tk UI thread. `afplay` seek support is checked at runtime; seek is disabled when unavailable. No claim of Serato cue compatibility.
- **Persistent background task queue**: SQLite-backed sequential metadata lookup and BPM analysis jobs; pause/resume, cancel, move waiting tasks up/down, per-file checkpointing, missing-file skip, failures, 30-day job history, and recovery of unfinished tasks after restart. Queued lookup/analysis produces staged metadata and does not write audio files. Tasks running on close stop after the current file and resume from their last checkpoint.
- **Advanced Settings**: categories for General, Library, Metadata, Audio, Appearance, Backups, Updates, Keyboard Shortcuts and Serato. Automatic daily backups while the app runs (14 newest plus up to four additional weekly backups), custom backup folder with local fallback, manual Backup Now, backup restore with confirmation. Music files are not backed up. Shortcut remapping and automated update installation are not implemented.
- **Smart filter builder**: AND/OR conditions across selected columns, saved in application preferences. Existing saved-view and header-filter behavior is retained.
- **Genre cleanup**: organizational grouping without tag writes; explicit rename with count and confirmation; optional original Genre→Composer, and persistent restore of original Genre/Composer via cleanup history. No music is modified by organizational grouping alone.
- **Name cleanup**: searchable and sortable suggested fixes with confidence color coding, edit, persistent dismiss, stage selected for explicit Save Changes. Does not auto-write.
- **More tests** for durable job queue, including restart and waiting-task reordering.

## Carried forward from prior combined development source

- Recursive manual import and library scan, missing-file detection and relocation, multi-format tag reading.
- Basic metadata editing, lookup providers, BPM and key analysis, column search, saved views, undo for staged edits.
- Duplicate Finder with explicit reviewed/keep selections, archive manifests and restore.
- Eight persistent app-local hot cues; no proprietary Serato data writing.
- Separate v3 app name, bundle identifier and build workflow.

## Known limitations / not yet complete

The full 15-feature design **is not fully implemented**. In particular:

- Full Serato interoperability is intentionally deferred. The Serato options are informational/read-only where proprietary writing is concerned.
- Waveform playback uses `afplay`, not a sample-accurate DJ engine. Pause is stop/resume from estimated position; seek and volume adjustments depend on platform capabilities. Waveform is a spectral energy visualization, not a full beatgrid-aware waveform.
- Automatic combined lookup+BPM+Camelot-key writing, always-prompt overwrite semantics, confidence-scored per-field write decisions, and artwork enrichment are not complete. Lookup still stages proposed tags for explicit Save.
- No full virtualized table, drag-resizable sidebar, native integrated title bar, custom rounded menus, or complete editable keyboard shortcut mapping.
- Task queue currently supports lookup and BPM analysis, not all possible batch actions; completed tasks are retained up to 30 days.
- Genre cleanup uses a searchable list and group selector, not the full requested multi-column draggable Lexicon-style layout.
- Duplicate Finder lacks some requested persistent review-progress and configurable selection features.
- Full file-change conflict handling, Serato metadata preservation tests, and format-by-format safe write validation have not been completed.
- Mac UI and GitHub build have not been executed in this Linux environment.

## GitHub / macOS build

1. Unzip the project and upload the **contents** of `DJTagManager_v3_combined/` to the `v3-development` branch, preserving `.github/workflows/build-mac.yml`.
2. Open GitHub → Actions → **Build Mac App (v3.1 Combined Development)** → Run workflow.
3. Download the artifact containing `DJ-Tag-Manager-v3-Combined-Dev-Mac.zip` and checksum.
4. Unzip and launch `DJ Tag Manager v3 Combined Dev.app` on Apple Silicon macOS. Test with copied music only.
5. Verify waveform display, seek availability, task queue pause/restart, backups, genre restore, and Name Cleanup before any use on a live library.

Run tests locally with `python -m unittest discover -s tests -v`. Python 3.11 is the workflow target.

## Additional changes in this candidate

- Persist table column widths in the existing column-layout JSON. The table uses 36px rows.
- Added editable keyboard mappings in Advanced Settings for Import Files, Find Column, Duplicate Review, Name Cleanup, and Task Queue. Duplicate mappings are rejected; mappings are disabled when typing in a text field.

### Important incomplete requirements

This candidate **still does not implement every approved feature**. In particular, the full rounded/resizable interface and inline header search, complete metadata lookup+audio analysis+automatic guarded writing, persistent duplicate review state and advanced configurable recommendations, and fully integrated Serato support are not complete. The existing name/genre cleanup tools are functional but not the complete Lexicon-style design. Mac GUI and packaged app have not been tested here. Do not treat this as a production-ready or fully complete v3.1.0 release. Use copies of audio only.

## 2026-11-14 integration pass (not a complete feature release)

- Added header-local live search entry rather than a separate search dialog. Shift-click a header to cycle sort ascending/descending/original; sorting is restricted to the current library rows. Header drag-reordering remains supported.
- Duplicate Finder review and per-file Keep selections are now persisted in the app SQLite preferences store, keyed by duplicate group membership; changing a Keep selection clears Reviewed. The actual archive still requires explicit confirmation and never deletes files.
- These changes have only passed source-level compilation and existing automated tests in Linux. Native Tk rendering, sorting under active filters, and Serato compatibility require testing on macOS.

**NOT COMPLETE:** Full 15-feature specification remains unimplemented. In particular the combined lookup+BPM+key guarded auto-write workflow, all metadata-format preservation cases, full Lexicon-style drag/drop genre UI, virtualized table, custom rounded macOS dialogs, advanced artwork integration, and robust task-queue file-write transaction recovery are not complete. Do not deploy to your working music library.

## Metadata safety milestone (November 2026)

- `metadata_safety.py` provides same-directory temporary-copy edits, verified recovery copies, external-change fingerprint checks, result validation, SQLite write history, and conflict-checked full-file restoration.
- The main **Save Changes** action and Genre Cleanup writes use the safety layer. After successful saves, staged undo/redo is reset. **Metadata Write History** is accessible from the sidebar.
- Recovery copies are stored under the application's `metadata_recovery` directory. They contain complete audio files and therefore can consume substantial disk space. Do not delete that directory if you may need to restore changes.
- Safety is intentionally conservative: unsupported formats/fields fail rather than silently dropping metadata. These checks do **not** yet prove full preservation of every proprietary tag on every format; test copies before using a real library.
- Automatic lookup-to-file writing, combined BPM/key analysis, provider overwrite prompts, artwork retrieval, and full metadata confidence workflows are **not completed in this milestone**.
- Native macOS GUI and PyInstaller builds are **not tested in this Linux environment**.

Run tests with `python -m unittest discover -s tests -v`.


## Phase 3 cleanup extension
See `PHASE3_EXTENSION_NOTES.md` for similar-title duplicate review, incremental external Name Cleanup scans, and genre-group organization improvements.

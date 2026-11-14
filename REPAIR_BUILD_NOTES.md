# Build #36 repair candidate — first implementation pass

This source is derived from `DJTagManager_v3_1_mac_feedback_fix1.zip` and does not replace v2.

## Implemented in this pass
- Player reorganized into two rows, with RGB waveform above track title and controls.
- Spacebar wired to Play/Pause outside text-entry controls.
- Double-click remains the playback action; removed the click-on-selected-cell inline-editor trigger. Edit Metadata remains available via context menu and dedicated button.
- Metadata editor: renamed Stage Changes to Save Changes; invokes existing backed-up write workflow and confirmation, rather than leaving edits staged; wheel scrolling attached to form widgets.
- Name Cleanup added to library tools sidebar.
- Deferred Serato Integration removed from Settings menu and Serato Settings from sidebar.
- Fixed a background queue pause/reorder race observed in the unit tests.

## Not yet fixed or verified
- Playback audio on macOS: requires a real Mac and real MP3s to verify; waveform rendering alone does not prove playback.
- Camelot key normalization; provider fallback configuration and 503 retries; genre candidate matching.
- In-app workspace migration for Genre Cleanup, Duplicates, Smart Filters, Name Cleanup.
- Custom genre creation/group management, all visual polishing, column sorting/header drag interactions, complete task-status redesign.
- UI automation tests and macOS packaged app verification.

## Test results
`python -m unittest discover -s tests -q`: 35 tests pass on Linux; Tk/macOS playback not tested.

Use only on copied test tracks. Build the macOS app from this source using the existing GitHub Actions workflow. Do not overwrite the v2 application.

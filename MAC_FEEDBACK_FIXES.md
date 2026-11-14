# macOS feedback repair pass 1

This update is based on the Phase 4 source and retains previous modules and the GitHub Actions workflow.

## Implemented
- Title and Artist always restored to the library table so songs remain identifiable.
- Right-click or Control-click a track opens a track-specific action menu, without confusing header right-clicks.
- Column visibility picker uses a yellow marker based on actual visible columns. Title and Artist cannot be hidden in this repair build. Other column changes persist.
- Header search editor closes on loss of focus, Return, Escape, or clicking elsewhere. Applied filters remain active.
- Find Tags & Art / Analyze BPM immediately acknowledges queued work and shows a visible task status/progress strip with access to Task Details, Pause and Cancel.
- Help button uses an explicit dark background and yellow foreground to address the white-box issue.

## Still pending
- Full rounded/pill visual redesign of the toolbar, sidebar, metadata editor, and Genre Cleanup.
- Genre Cleanup complete drag/drop UX and organizational workflow validation.
- End-to-end metadata provider diagnosis for tracks returning blank Genre.
- Confirming auto-write and recovery workflows on macOS using **copies** of tracks.
- Real Mac GUI testing of these repairs; Linux tests do not exercise Aqua/Tk rendering.

## Safe test order
1. Build on `v3-development` and launch the separate development app.
2. Confirm Title and Artist appear and right-click a song.
3. Test column picker and inline header search dismissal.
4. Select **one copied song**, click Find Tags & Art, and check task progress / errors.
5. Do not write to your original library.

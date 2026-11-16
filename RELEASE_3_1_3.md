# DJ Tag Manager 3.1.3 — Genre Cleanup iteration

- Genre Cleanup uses at most three responsive columns (two or one on narrower windows).
- Main genre headings display distinct track totals across their subgenres.
- Empty main genres can be selected and deselected.
- Clicking outside genre cards clears selected genres, while genre controls retain their own selection handling.
- The New Genre text field is moved to a separate full-width footer row so it stays visible when the window narrows.
- Updater recognizes older published 3.x releases as older, rather than calling them invalid v3 updates.

## Build and release

Upload all project files to the `v3-development` branch, preserving `.github/workflows/build-mac.yml`. Wait for the Actions build to finish. Download the Mac build artifact and test locally before creating the public `v3.1.3` release. The updater requires a release with the correct Mac ZIP and SHA-256 checksum assets; don't assume an Actions artifact is itself a valid updater asset.

## Validation

Python compileall and unit tests run on Linux; native macOS Tkinter behavior and the end-to-end update installer have not been verified here.

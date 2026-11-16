# DJ Tag Manager 3.1.2 — source revision

- Fixed updater version, asset names, app name, and bundle identifier to match `.github/workflows/build-mac.yml`.
- Fixed an exception-callback scoping error that could display `Could not check updates: None` instead of the actual error.
- The updater checks for missing release assets only when a newer release is available.
- Genre Cleanup: Show All Genres displays empty main families but not unused subgenres. When off, families without active tracks are hidden. Searching can find empty suggested subgenres.
- Removed Back to Library button; All Tracks navigation remains the route back.
- Reduced header padding, adjusted column widths, accelerated wheel scrolling, and added empty-area selection clearing above and below the grid.

## Important
This source has passed Python syntax compilation, but macOS graphical behavior and in-app installation are not verified in this environment. Test with copies of MP3s before saving tags. Existing user settings are preserved. Publish only after a successful Actions build and local smoke test. Do not modify v2.

## Upload and build
Extract this ZIP. Upload its contents (including `.github`) to the root of `v3-development`, replacing corresponding source files. Commit; the branch push creates an Actions artifact. Test that artifact. To publish a release, create the `v3.1.2` tag pointing to the tested commit; the tag workflow publishes the GitHub Release with `DJ-Tag-Manager-Mac.zip` and `.sha256`. Do not manually upload the Actions artifact as a source ZIP.

# DJ Tag Manager 3.1.6 — Genre Cleanup improvements

- Responsive main genre columns update as the window is resized (no 100ms debounce; existing cards expand continuously, columns reflow at breakpoints).
- Selecting a main genre also selects all its subgenres, including groups without tracks; clicking again deselects.
- Save Changes includes selected families and their subgenres; successful writes with a new target genre add it to the main-genre organization and refresh the cards.
- Preserve bidirectional drag-and-drop of subgenres and main-genre reorder controls; Other remains the final genre.
- Existing background-click selection clearing, updater, and manual GitHub release workflow remain unchanged.

## Release instructions
1. Extract this ZIP and upload its *contents* to the existing `v3-development` branch, replacing matching files. Do not upload the ZIP as a single repository file.
2. Wait for the Actions branch build to succeed.
3. Create/push tag `v3.1.6` **from the new `v3-development` commit**. GitHub Actions automatically publishes the tagged release with `DJ-Tag-Manager-Mac.zip` and checksum. If you manually create a release, set tag `v3.1.6`, target `v3-development`, and do not publish it before the macOS ZIP asset is attached.
4. In installed 3.1.5, use Check for Updates > Install Update. Verify it relaunches as 3.1.6.
5. Test genre selection, resize while dragging, cross-family drag in both directions, Other-last, and save using a backed-up test track.

NOTE: Tk GUI behavior cannot be verified on this Linux build environment. Python tests passed; Mac interactive verification is still required.

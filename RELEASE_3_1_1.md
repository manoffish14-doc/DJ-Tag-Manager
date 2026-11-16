# DJ Tag Manager v3.1.1 — release and testing

This ZIP contains **source code**, not a compiled macOS application. Keep v2 untouched.

## Upload the source
1. Open your public GitHub repository `manoffish14-doc/DJ-Tag-Manager`.
2. Switch to branch `v3-development`.
3. Extract this source ZIP and upload the **contents of the `project` folder** into the repository root (including `.github/workflows/build-mac.yml`). Do not upload the ZIP itself as the source, and do not nest `project/` in the repo.
4. Commit to `v3-development`. In Actions, verify the `Build DJ Tag Manager v3.1.1 (macOS)` workflow succeeds. This push creates an Actions artifact, **not** a GitHub Release.
5. In GitHub, create a tag **`v3.1.1`** pointing to the exact tested `v3-development` commit, then push the tag. For the GitHub website: Releases → Draft a new release → Choose a tag → Create new tag `v3.1.1` targeting `v3-development` → **do not publish a release manually yet**. Instead, use GitHub's tag creation UI if available or use `git tag v3.1.1 && git push origin v3.1.1` locally. The tag push runs the workflow and automatically creates the release with the ZIP and checksum.
6. Confirm GitHub Releases contains `v3.1.1` and assets `DJ-Tag-Manager-v3-Mac.zip` and `.sha256`. Download/install the release asset to test.

**Important:** The updater is included in 3.1.1, but 3.1.1 is its own initial release. To test in-app upgrading, publish a later version (for example `v3.1.2`) using the same release pipeline. The update checker only offers newer stable releases.

## macOS caveats
- The updater expects `DJ Tag Manager v3.app` with bundle ID `com.djtagmanager.v3development`, matching the build workflow.
- In-app updates are experimental until tested on macOS. The helper keeps a `.previous.app` copy for recovery; it will refuse to overwrite an existing backup. Move or archive an old backup before another update.
- Unsigned/unnotarized macOS builds can trigger Gatekeeper warnings. The updater is not a substitute for signing/notarization.
- Library and settings live in Application Support and are not packaged inside the app bundle.
- Don't install over or rename the existing v2 app.

## Focused tests
- Genre grid starts at the top; no blank top offset; columns wrap to up to four per row.
- Show All Genres OFF hides zero-track subgenres, not just families.
- R&B appears in only one family. Old duplicated names are normalized in the view.
- Scroll with a Mac trackpad over cards, then drag a subgenre between families.
- Click empty space to clear selection.
- Click All Tracks in the sidebar or Back to Library to return to the library.
- Open Settings → Check for Updates; when only 3.1.1 is published it should report no newer update.

Use **copied MP3s** to test Save Changes; it writes tags immediately and overwrites Composer.

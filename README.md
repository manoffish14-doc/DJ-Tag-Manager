# DJ Tag Manager — Mac app build kit

This kit builds a standalone macOS `.app` **in GitHub Actions on a Mac runner**. You do **not** need Python installed on your own Mac.

## Build it without installing Python

1. Sign in to GitHub and create a **private** repository.
2. Upload `app.py`, `requirements.txt`, and `.github/workflows/build-mac.yml` to the repository, preserving the `.github/workflows` path. GitHub's browser uploader can upload the extracted folder contents; alternatively use GitHub Desktop.
3. In the repository, open **Actions → Build Mac App → Run workflow**. A push to `main` also starts a build.
4. After the run succeeds, open the run and download the `DJ-Tag-Manager-macOS` artifact.
5. Unzip the artifact and then unzip `DJ-Tag-Manager-macOS.zip` if needed. Drag `DJ Tag Manager.app` to **Applications**.

This app is **unsigned and unnotarized**. macOS Gatekeeper may block it. If macOS says the developer cannot be verified, use **System Settings → Privacy & Security → Open Anyway** only if you trust the app you built from this source. Do not bypass warnings for unfamiliar files.

## What it does

- Imports MP3s and folders
- Looks up approximate original year and available genre via MusicBrainz (internet needed)
- Writes reviewed year and genre ID3 tags
- Estimates BPM and suggests cue times, exportable to JSON

## Not yet supported

- Writing Serato hot cues, audio fingerprint recognition, verified song section identification
- Signed Apple installer or notarization

## Important

This build recipe is provided but **has not been run or verified on a macOS runner**. PyInstaller and audio dependencies may need adjustments. Always test with duplicate MP3s, and back up your library first. For best compatibility, build on a Mac runner matching your Mac architecture. This workflow targets the GitHub-hosted macos-15-arm64 runner for Apple Silicon. Runner availability and build success depend on GitHub account/repository settings; the workflow has not been executed here.

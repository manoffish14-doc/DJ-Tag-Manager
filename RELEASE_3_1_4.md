# DJ Tag Manager 3.1.4

Changes:
- Genre Cleanup uses up to three responsive, independently stacked columns.
- Subgenres are compact, wrapping chips with selection and drag/drop bindings.
- Repeated Add Subgenre controls removed.
- Existing subgenres such as House can be promoted into main genres after confirmation.
- Empty main genres remain selectable.
- Main genre track totals include direct genre tracks and child subgenre tracks.
- Version updated to 3.1.4 for GitHub Release updater verification.

Release procedure:
1. Upload project contents to v3-development (not the containing directory).
2. Wait for the successful GitHub Actions build on v3-development.
3. Create and push tag v3.1.4 pointing to that commit. The tag-triggered workflow automatically publishes the public GitHub Release with the Mac ZIP and checksum.
4. Keep the installed 3.1.3 app open, use Check for Updates, verify it offers 3.1.4, then install and restart.
5. Check the running version, genre layout, House promotion, chips, and saved library.

Do not manually upload the source ZIP as the updater asset. The updater requires the two exact generated files DJ-Tag-Manager-Mac.zip and DJ-Tag-Manager-Mac.zip.sha256.

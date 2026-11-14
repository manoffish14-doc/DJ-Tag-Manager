# DJ Tag Manager v0.3 — Apple Silicon Mac

Adds drag-and-drop import of MP3s and folders, and reviewable artist/title splitting for common YouTube titles (e.g. `Artist - Title`).

## Update your GitHub repository

Replace `app.py`, `requirements.txt`, and `.github/workflows/build-mac.yml` in the repository with the files in this ZIP. Keep the same relative paths. Commit to `main`; the Actions workflow will rebuild the application. Download the successful Actions artifact, unzip it, unzip the inner Mac ZIP, and drag `DJ Tag Manager.app` into Applications, replacing the old copy after quitting it.

## How to use

Drag MP3s or folders onto the drop zone or track list. Select a track and click **Suggest Artist / Title**. The editable suggestion boxes let you correct the split; click **Apply to selected row**. MusicBrainz lookup uses suggestions automatically. Check **Also write artist/title to MP3** if you want them saved, then use **Write Selected Tags**. The original MP3 is updated in place, with no automatic backup or duplicate file. The filename and location remain unchanged.

Caution: The split is heuristic and requires review; it does not guarantee correct matches. Cue analysis is only suggested timestamps; no Serato cue data is written. Because writes have no automatic undo, test on a manually copied song before editing your main Serato library.

# Phase 2 — Metadata automation development milestone

This is a development candidate, **not a fully validated production release**.

## Integrated behavior
- **Find Tags & Art** enqueues a combined provider lookup and BPM/Camelot-key analysis for selected tracks. Lookup and audio analysis share one background task and return a combined proposal.
- MusicBrainz is available without credentials; Last.fm, Discogs and Spotify are optional and require API credentials. Network access and provider availability are required. No fabricated provider matches are used.
- **Settings → Metadata Automation** selects fields and whether to propose overwriting already-filled values. By default, existing tags are preserved; Artist/Title are never automatically overwritten. Composer/subgenre mapping is **off by default** because Composer has a different meaning from Subgenre.
- The GUI prompts **for every track with eligible proposed changes**. Declining leaves the audio file untouched. Accepting uses the Phase 1 verified temporary-file write, recovery copy, external-change check, and history.
- Per-field confidence is an **estimate**; it is not a calibrated probability. Lower-confidence proposals can be marked for later review.
- **Settings → Find Cover Art for Selected MP3** searches MusicBrainz/Cover Art Archive, then asks before writing a front cover to a single MP3 through the safe-write journal. Existing non-front-cover APIC frames are retained.
- Existing lookup settings, manual edit workflows, waveform, task queue and backup modules remain in the project.

## Known limitations / testing still required
- Artwork lookup is a separate explicit action, not a fully unified one-click album-art + metadata operation. It supports embedded MP3 artwork only.
- MusicBrainz earliest recording/release year is a heuristic for original year; remixes may need human review.
- Audio key analysis is approximate and can misclassify keys. BPM can be detected at half/double time.
- Some non-MP3 formats do not support all fields; unsupported writes are rejected and do not replace the original.
- No audio-fingerprint identification is implemented yet.
- A restart after a completed provider lookup but before GUI confirmation can lose that **proposal** (the job cursor persists); no audio file is modified without confirmation.
- Network/API integration, macOS Tk UI, packaged application and live audio processing have not been tested in this Linux environment. Run on copied audio files only.

## Tests
`python -m unittest discover -s tests -v`

## Build
GitHub Actions workflow: `.github/workflows/build-mac.yml`. Preserve your v2 installation and run the development build separately.

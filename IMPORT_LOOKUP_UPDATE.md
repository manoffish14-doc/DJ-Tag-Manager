# Import & Find Tags & Art options — targeted development update

- Settings > Import & Automation: optional automatic BPM/key analysis and metadata lookup for newly imported files, both off by default. Persisted in existing v3 preferences. Imported files are read, indexed, and duplicate paths skipped regardless of options.
- Find Tags & Art now opens a pre-search modal with supported fields (release year, genre, subgenre, BPM, Camelot key, artwork), search scope (missing / review / compare), Cancel and Start Lookup. Last choices persist.
- Lookup uses the existing durable queue and safe-write confirmation. Requested fields control which metadata proposals can be written. Album art is searched asynchronously when a MusicBrainz recording ID is available and requires its own confirmation before embedding.
- Title, artist, album, ISRC, publisher and copyright are intentionally **not offered**: existing provider pipeline does not reliably supply those fields, so showing working checkboxes would be misleading. These can be added when matching and write support are implemented.
- Existing import metadata suggestions remain non-destructive. Automatic BPM-only import continues to use the existing analysis queue and stages values rather than writing files.
- Mac UI and online providers were not tested in this Linux environment; verify on macOS with copies of audio files.

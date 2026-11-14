# Lookup Repair — development build

- Normalizes search-only artist/title from YouTube-style filenames and strips featured-artist/video suffixes. Source MP3 tags are not modified by this normalization.
- Uses bounded GET retries for transient HTTP 429/5xx responses, with a named User-Agent and request timeouts. Repeated 503s may still occur and are not guaranteed to resolve.
- Reports provider failure distinctly from a successful search with no matching records.
- Existing Last.fm and Discogs fallback integrations are retained; no new credentials are needed if already configured.
- This build does NOT repair queue cancellation or the UI overhaul, and has NOT been tested on macOS or against live metadata services.

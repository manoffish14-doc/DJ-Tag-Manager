# Genre auto-save update

- Song-specific database genre updates the MP3 even if a genre is already populated.
- When providers return no usable genre, populated genre is preserved.
- When the genre is blank and no database genre exists, a recognized artist baseline is used (small editable built-in mapping in `genre_fallback.py`).
- If neither is available, the genre remains blank.
- Genre writes use the existing transactional backup and write-history system, with no confidence threshold or approval prompt.
- Other metadata writes continue to require confirmation.
- Artist baseline is a heuristic, not verified song metadata. A failed provider request can still trigger the baseline for blank genres.
- v2 is not modified.

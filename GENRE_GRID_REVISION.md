Genre Cleanup grid revision
===========================
- Four fixed-width genre families per row at most; additional families wrap below.
- Other remains the final family.
- Show All Genres toggle hides empty families when disabled.
- One vertical shared canvas; no nested horizontal scrollbar.
- Wheel/trackpad input accumulates smaller deltas for smoother scrolling.
- Clicking empty canvas clears selected subgenres; clicking selected item toggles it.
- Optional New Genre field next to Save Changes overrides the parent for selected subgenres.
- Both main genre and subgenre creation use cross-library canonical duplicate checks.
- Drag uses per-gesture root handlers without unbinding unrelated application handlers.
- Tasks and Player compact toggles remain present.

Mac-specific pointer interactions and layout must still be tested in a built app.
Always test tag writes on copied audio first.

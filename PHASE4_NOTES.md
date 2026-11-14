# Phase 4 — interface/workflow integration checkpoint

Based on the Phase 3 extended source. The ZIP includes the full project.

## Implemented in this checkpoint
- Charcoal main and panel palette updated toward the agreed v3 design.
- Sidebar defaults to 240px, can be resized with a draggable 5px grip (180–350px), and has a collapse/expand button. Width and collapsed state persist.
- Column-header filters persist across launches; invalid saved fields are ignored.
- Keyboard shortcut remapping uses dispatch rather than `unbind_all`, avoiding accidental removal of unrelated shortcuts such as Undo/Redo and cue hotkeys.
- Existing rounded ttk buttons, draggable/reorderable columns, column picker, smart filter builder, queue, settings categories and RGB waveform retained.
- Three additional regression tests, 32 total.

## Not yet verified or complete
- No native macOS GUI execution was possible in this Linux environment. In particular, the collapsed sidebar, header gestures and macOS title bar must be tested on Mac.
- Native rounded corners for every widget, integrated titlebar and full pixel-perfect Lexicon-inspired design are not complete.
- Column search currently opens a filter editor rather than always remaining embedded directly under the header.
- Shortcut manager does not yet support every app action, and some legacy hotkeys remain fixed.
- Full workspace scroll/selection restoration, sidebar drag ordering, and exhaustive queue/player interaction testing remain outstanding.
- Serato write interoperability remains deferred.

## Run checks
`python -m unittest discover -s tests -v`
`python -m compileall -q .`

Keep v2 installed separately. Use only copies of music for manual tests.

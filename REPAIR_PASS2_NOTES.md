# Repair Pass 2 — Queue Stabilization (development)

This is an incremental safety repair, **not** the complete visual redesign.

- Background Operations status stays mounted to avoid jumping layout.
- Task names are human readable and idle status is explicit.
- Cancelling a running job marks it cancelled immediately; results from an in-flight request are discarded, including on the UI event path. Network calls are not forcibly interrupted and may finish before worker moves to next task.
- Duplicate active submissions with the same kind and set of paths reuse the existing job.
- Adds cancellation regression test.

Known outstanding: provider retries, provider-specific progress, query cleanup, redesigned library UI and in-app cleanup workspaces, waveform scrubbing and player styling. Do not use production library for testing. The macOS build has not been verified here.

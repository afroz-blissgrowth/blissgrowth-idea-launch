# runs/

One folder per idea run: `runs/<YYYY-MM-DD>-<idea-slug>/` (stage files plus `state.json`, so a run resumes and never re-pays).
`runs/_cache/` holds caches shared across runs (for example the company signals cache).

Everything here except this file is gitignored: run data contains lead lists and must not be committed.

# Cassettes

Recorded-shape responses for the metadata lookups in `verify_refs.py`.

**These were hand-constructed from each API's documented response shape, not
captured from live calls.** The build environment's egress proxy blocks
`api.crossref.org`, `openlibrary.org`, `eutils.ncbi.nlm.nih.gov`, and
`export.arxiv.org`, so live recording was not possible there.

They pin the *parsing and state-writing* behaviour — which field the verifier
reads to decide a lookup succeeded, and what it writes into the note's
`verification` block. They do **not** prove the live endpoints still return this
shape. Acceptance checklist item 6 therefore remains a manual step on a machine
with network access:

```sh
verify_refs.py --repo <repo> --mailto you@example.org
```

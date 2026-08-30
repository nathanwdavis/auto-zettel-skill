# Note types and the rules that bind them

## Identity: the note key

Every note is named `<title-slug>--<timestamp-id>.md`, e.g.
`atomic-notes-compound-over-time--202608301412.md`. That whole string is the
**note key**, and it is what both filenames and links use.

```yaml
id: "202608301412"      # immutable; never changes
slug: "atomic-notes-compound-over-time"
key: "atomic-notes-compound-over-time--202608301412"
aliases: ["202608301412"]
```

- The **id** is the identity. Timestamp-based, `YYYYMMDDHHMM`, never reused,
  never edited. No folgezettel.
- The **slug is frozen at creation.** Reword `title` freely; the filename does
  not follow. This is what keeps links, manifest paths, and git history stable
  across a rewrite.
- `aliases` lets a bare `[[202608301412]]` resolve in Obsidian; the lints
  resolve it through the manifest's `id_to_key` map.

`lint_links.py` fails a note whose filename stem, `key`, `slug`, and `id`
disagree — that catches a hand-rename before it breaks inbound links.

## Typed links

Relations live in frontmatter and must come from this closed set:

```
supports  contradicts  analogous  shared-concept
historical-connection  elaborates  refutes  source
```

```yaml
links:
  - target_id: "how-to-take-smart-notes--202608301000"
    relation: source
```

Anything outside the taxonomy, or a target absent from the manifest, fails
`lint_links.py`.

## The types

### permanent
One atomic idea. The title states a **claim**, not a topic. At least one
outbound typed link. Every sourced claim links to a *verified* reference note —
`lint_citations.py` looks for attribution language ("argues", "shows that",
quotation marks) and fails the note if nothing verified is linked.

A note tagged `contested` needs **three or more** distinct verified references.

> "Atomic notes compound over time" is a claim. "Notes" is not.

### literature
An own-words summary of **exactly one** source, with a locator (page, section,
timestamp). Links to exactly one reference note. Never paste source prose here —
verbatim text belongs in `raw/`.

### reference
Exactly one per source. Carries `csl_json`, the rendered `chicago_note` and
`chicago_bib`, `source_tier`, a `verification` block, and `raw_capture`.
The Chicago strings are generated — never hand-written. See
`citation-rules.md`.

### fleeting
A short-lived capture. Swept each cycle: promoted to a literature or permanent
note, or cleared. Nothing downstream should depend on one.

### moc (structure)
A map of content. `INDEX.md` links **only** to MOCs; MOCs link to notes. The
layering keeps the root readable as the graph grows, and `lint_links.py`
enforces it.

## The 1-1-1 rule

One permanent note = one atomic idea = one source-of-truth claim, with at least
one outbound typed link. Each literature note summarizes exactly one source and
links to exactly one reference note.

The point is reuse: a note confined to a single idea can be linked from
contexts its author never anticipated. A note carrying three ideas can only
ever be linked as a lump.

## Inquiry lifecycle

`inquiries/<key>.md` moves `new → in-progress → answered → archived`. An
inquiry marked `answered` must carry at least one `result_notes` backlink to
the permanent note that answered it, resolvable in the manifest.

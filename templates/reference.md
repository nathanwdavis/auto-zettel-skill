---
id: "{{ID}}"
key: "{{KEY}}"
slug: "{{SLUG}}"
aliases: ["{{ID}}"]
type: reference
title: "{{TITLE}}"
tags: []
source_tier: peer-reviewed   # peer-reviewed | primary-text | reputable-secondary | general-web
scripture: false
csl_json:
  id: "{{ID}}"
  type: article-journal
  title: "{{TITLE}}"
  author:
    - family: ""
      given: ""
  issued:
    date-parts:
      - [2026]
chicago_note: ""
chicago_bib: ""
citation_renderer: pandoc
verification:
  method: ""          # raw-capture | crossref | arxiv | pubmed | openlibrary | googlebooks
  source: ""
  verified: false
  date: ""
  # verify_refs.py may add open_access: <url> for a DOI -- the legal free
  # copy to capture (Unpaywall/OpenAlex, amendment A11)
raw_capture: ""       # repo-relative path under raw/ (fetch_source.py or ingest_drops.py write it)
links: []
created: "{{DATE}}"
updated: "{{DATE}}"
---

<!--
FR-4/FR-10: exactly ONE reference note per source -- lint_citations fails two
notes sharing a DOI/ISBN/PMID/arXiv id/URL (`duplicate-source`). `chicago_note`
and `chicago_bib` are generated from csl_json -- run verify_refs.py, never
hand-edit them. A reference is only usable once verification.verified is true,
by raw capture on disk or an authoritative metadata lookup.
Keep every field above: source_tier (one of the four values; `bad-source-tier`
otherwise), raw_capture, and all four verification keys are required
(`missing-field`).
Scripture (FR-9): set scripture: true AND source_tier: primary-text
(`scripture-tier`); cite book-chapter-verse per SBL and it is excluded from
the bibliography.
-->

Bibliographic record. Notes on provenance, edition, or access go here.

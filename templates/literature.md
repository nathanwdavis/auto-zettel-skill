---
id: "{{ID}}"
key: "{{KEY}}"
slug: "{{SLUG}}"
aliases: ["{{ID}}"]
type: literature
title: "{{TITLE}}"
tags: []
reference: "{{REFERENCE_KEY}}"
locator: ""
links:
  - target_id: "{{REFERENCE_KEY}}"
    relation: source
created: "{{DATE}}"
updated: "{{DATE}}"
---

<!--
FR-4: an own-words summary of EXACTLY ONE source, with a locator (page,
section, timestamp) -- lint_links fails an empty locator (`missing-locator`).
Links to exactly one reference note (`one-to-one`), and `reference` must name
that same note (`reference-mismatch`). Never paste source prose here -- the
verbatim capture belongs in /raw/.
-->

Summary of [[{{REFERENCE_KEY}}]] in your own words.

---
id: "{{ID}}"
key: "{{KEY}}"
slug: "{{SLUG}}"
aliases: ["{{ID}}"]
type: permanent
title: "{{TITLE}}"
tags: []
links:
  - target_id: "{{TARGET_KEY}}"
    relation: elaborates
created: "{{DATE}}"
updated: "{{DATE}}"
---

<!--
1-1-1 (FR-4): ONE atomic idea, title stated as a claim, at least one outbound
typed link. Every sourced claim must link to a verified reference note or
lint_citations will hard-fail the run.
Relations: supports contradicts analogous shared-concept historical-connection
           elaborates refutes source
-->

{{TITLE}} — state the idea in your own words, one paragraph, self-contained.

A sourced claim cites its reference note inline: [[{{TARGET_KEY}}]].

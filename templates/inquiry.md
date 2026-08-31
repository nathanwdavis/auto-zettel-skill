---
id: "{{ID}}"
key: "{{KEY}}"
slug: "{{SLUG}}"
aliases: ["{{ID}}"]
type: inquiry
question: "{{QUESTION}}"
status: new          # new | in-progress | answered | archived
priority: normal     # low | normal | high
asked_by: human
result_notes: []     # note keys that answered this; required once answered (AC-6)
created: "{{DATE}}"
updated: "{{DATE}}"
---

<!--
FR-6: an open question, tracked across runs. A maintenance run reads every
inquiry that is not archived, works the `new` ones first, and moves the status
along as it goes.

`answered` REQUIRES at least one result_notes entry resolving to a permanent
note — lint_links enforces it. An inquiry answered with nothing to point at is
not answered.
-->

{{BODY}}

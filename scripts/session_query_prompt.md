The lock is yours and you are on branch {{BRANCH}}. The gaps the query found
are already filed on this branch:

{{FILED}}

They were filed *after* the branch existed, so they land in this cycle's PR
rather than sitting in a working tree the next run would overwrite.

Each filed entry closes a numbered gap (`g1` first), and they were filed in
priority order. Now work them. Each kind asks for different work, and the entry
that was filed says which:

- **An inquiry** is a research job: the base has nothing on the topic. Work it
  as an ad-hoc question -- check coverage, capture sources, write the notes,
  then close the inquiry with the permanent notes that answered it. The full
  recipe is in the ask checklist; the commands are the same.

- **"Distil a permanent note on ..."** means the sources are already on file
  and nothing has been distilled into a claim. This is synthesis, not
  research: read the material named in the entry and write the permanent
  note. Do not fetch anything.

      {{PYTHON}} {{SCRIPTS}}/capture.py --repo {{REPO}} permanent "<claim>" --link <lit-key>:elaborates --body -

- **"Add to a map of content: ..."** means the notes exist but no MOC reaches
  them, so a reader walking down from INDEX cannot find them. This is
  structural work: add them to the right MOC with a line of context each, or
  create a MOC when a cluster of three or more has none. INDEX links only to
  MOCs.

- **"Write the literature note ... for `<key>`"** means a source is captured
  and nobody has read it. Read the capture in `raw/` and summarise it in your
  own words with a locator. Do not re-fetch it.

- **"Link `<key>` into the graph"** means nothing in the base refers to that
  claim, so it will never be met again by accident. Propose a typed relation to
  a related claim, or run `serendipity_sweep.py` and read what it offers.

- **"Work or archive the stale inquiry `<key>`"** means a question was asked
  long ago and never worked. Answer it, or archive it with a reason -- an
  inquiry nobody will ever work is noise in every future report.

- **"Find a primary or peer-reviewed source for: ..."** means a claim rests
  only on general-web sources. This is research, and the note stays as it is
  until a stronger source is on file.

Work the entries in the order they were filed; a research gap is worth more
than a mapping gap, and the filing order reflects that.

Then, as with any cycle:

    {{SCRIPTS}}/remote_cycle.sh gates --repo {{REPO}}
    {{SCRIPTS}}/remote_cycle.sh finish --repo {{REPO}} --title "Close gaps: {{QUERY}}"

If `finish` says to open the PR yourself, open it with the GitHub MCP tools
and enable auto-merge (squash).

Close each inquiry you actually answered, and leave the ones you could not as
`in-progress` with a note saying why:

    {{PYTHON}} {{SCRIPTS}}/capture.py --repo {{REPO}} inquiry-update <key> --status answered --result-notes <perm-key>

Report to the user which gaps you closed and which you left, and why. Filing a
gap is cheap; closing one honestly is the work.

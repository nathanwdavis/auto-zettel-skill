The lock is yours and you are on branch {{BRANCH}}. The source is already
ingested: it is immutable evidence in `{{CAPTURE}}`, its reference note is
`{{REFERENCE}}`, and the text extraction is `{{TEXT}}`.

What remains is the part only reading can do: find what this source says that
the knowledge base does not already know, and write that down.

1. **Read the extraction, by page.** It carries `--- page N ---` markers, so
   every passage you use has a locator without reopening the PDF.

2. **See where the source lands against what the base already has**, for its
   main terms:

       {{PYTHON}} {{SCRIPTS}}/query.py --repo {{REPO}} "<a central term from the source>"

   You are looking for three things, and they lead to different work:
   passages that **support a claim the base already makes** (a link, and
   possibly a stronger source for an existing note); passages that
   **contradict one** (a `contradicts` link, and a note that says so); and
   passages the base has **nothing on** (a new claim worth distilling).

3. **Write one literature note, in your own words**, with a locator naming the
   page you drew it from. Never paste source prose into a note -- verbatim
   text lives only in the capture:

       {{PYTHON}} {{SCRIPTS}}/capture.py --repo {{REPO}} literature "<title>" --reference {{REFERENCE}} --locator "p. N" --body -

4. **Distil permanent notes**, one atomic claim each, title stated as a claim.
   Every sourced claim links to the verified reference note:

       {{PYTHON}} {{SCRIPTS}}/capture.py --repo {{REPO}} permanent "<claim as a sentence>" --link <lit-key>:elaborates --link {{REFERENCE}}:source --body -

   A short direct quotation belongs **here**, in a permanent note, alongside
   the link to the reference it came from -- the citation lint reads quotation
   marks as a sourced claim and will fail a note that quotes without one.
   Prefer your own words; quote only when the exact phrasing is the point.

5. **Link the new claims into a map of content**, so a reader walking down
   from INDEX reaches them.

6. **Run the gates and fix what they find:**

       {{SCRIPTS}}/remote_cycle.sh gates --repo {{REPO}}

   Never make a gate pass by weakening it. Never edit anything under `raw/`:
   the capture is the evidence the citation rests on.

7. **Hand off:**

       {{SCRIPTS}}/remote_cycle.sh finish --repo {{REPO}} --title "Ingest: {{TITLE}}"

   If it says to open the PR yourself, open it with the GitHub MCP tools and
   enable auto-merge (squash).

Tell the user what the source added: which claims are new, which existing
notes it supports or contradicts, and anything it says that you deliberately
did not file. A source that produced no new claim is a finding worth
reporting, not a failure to hide.

The lock is yours and you are on branch {{BRANCH}}. The question is filed as
{{INQUIRY}}, so it survives even if this session is interrupted.

Work it in this order. Every command is given in full: run them, do not
reconstruct them from memory.

1. **See what the base already has before researching anything.**

       {{PYTHON}} {{SCRIPTS}}/query.py --repo {{REPO}} {{QUESTION_Q}}

   If the base already answers the question, say so and cite the note keys.
   Re-researching what is already on file is the most expensive mistake here.
   The report ends with named gaps; those are what your research should close.

2. **Mark the question as being worked**, so a later reader can tell a
   question in progress from one nobody has touched:

       {{PYTHON}} {{SCRIPTS}}/capture.py --repo {{REPO}} inquiry-update {{INQUIRY_KEY}} --status in-progress

3. **Per source, in this order.** Never hand-write a note file: the gates
   demand exact frontmatter and a generator produces it by construction.

       {{PYTHON}} {{SCRIPTS}}/capture.py --repo {{REPO}} reference --doi <doi>
       {{PYTHON}} {{SCRIPTS}}/fetch_source.py --repo {{REPO}} --ref <ref-key> --url <url>
       {{PYTHON}} {{SCRIPTS}}/capture.py --repo {{REPO}} literature "<title>" --reference <ref-key> --locator "p. N" --body -
       {{PYTHON}} {{SCRIPTS}}/capture.py --repo {{REPO}} permanent "<claim as a sentence>" --link <lit-key>:elaborates --link <ref-key>:source --body -

   `reference` verifies through the registries when it can. If it reports
   UNVERIFIED, capture the source with `fetch_source.py` and re-run
   `verify_refs.py` -- never edit the verification block by hand. A source you
   cannot reach at all is an INBOX entry, not a note written from memory:

       {{PYTHON}} {{SCRIPTS}}/capture.py --repo {{REPO}} inbox "Source needed: <title or DOI>" --body "<why it could not be fetched>"

4. **Link the new claims into a map of content** so a reader walking down from
   INDEX can find them. INDEX links only to MOCs; MOCs link to notes.

5. **Run the gates and fix what they find**, re-running until clean:

       {{SCRIPTS}}/remote_cycle.sh gates --repo {{REPO}}

   Never make a gate pass by weakening it, deleting the offending note, or
   back-filling a citation you did not verify. Fix the note or capture the
   source.

6. **Close the inquiry honestly.** `answered` requires the permanent notes
   that answered it:

       {{PYTHON}} {{SCRIPTS}}/capture.py --repo {{REPO}} inquiry-update {{INQUIRY_KEY}} --status answered --result-notes <perm-key>

   If you could not resolve it, leave it `in-progress` and say why -- that
   record is worth more than a tidy queue:

       {{PYTHON}} {{SCRIPTS}}/capture.py --repo {{REPO}} inquiry-update {{INQUIRY_KEY}} --note "<what is still missing>"

7. **Hand off.** `finish` re-runs the gates itself and refuses to push a red
   branch:

       {{SCRIPTS}}/remote_cycle.sh finish --repo {{REPO}} --title "Research: {{QUESTION}}"

   If it says to open the PR yourself, open it with the GitHub MCP tools and
   enable auto-merge (squash) so it lands exactly when the required check
   passes.

**Answer the user in chat**, with the sources you verified. They asked a
question; the notes are the durable record, not the reply. File what is worth
citing again and nothing else -- padding the base is a cost, not a deliverable.

You never push to main and never merge. The required check decides.

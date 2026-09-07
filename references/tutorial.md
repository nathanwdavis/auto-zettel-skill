# Tutorial: from nothing to a knowledge base that grows itself

One topic, followed end to end. Every command here was run against a throwaway
repository before this page was written, and the output shown is what it
actually printed.

You will end with a real content repo containing a verified source, a literature
note, an atomic claim, a map of content, all gates passing, and a schedule that
keeps it growing. Budget about thirty minutes.

Set `SCRIPTS` first, so every command below works as written:

```sh
SCRIPTS=<the plugin's scripts directory>     # see "Install" in the README
```

---

## 1. Prerequisites

```sh
gh auth login                        # a PAT or SSH key with `repo` scope
pip install -r requirements.txt
```

**Install the dependencies into the interpreter you will actually use.** If you
put them in a virtualenv and later schedule a run under cron, that job must
invoke the same interpreter — otherwise the run fails several steps in, where it
looks like something else entirely. If in doubt, use absolute paths:

```sh
PYTHON=/full/path/to/.venv/bin/python
```

## 2. Genesis — create the content repo

The script asks for nothing it can infer, and refuses to clobber an existing
GitHub repo or a non-empty directory.

```sh
"$SCRIPTS/init_content_repo.sh" \
  --name my-kb \
  --visibility private \
  --owner <your-github-username> \
  --topics "retrieval practice, spaced repetition" \
  --cadence weekly \
  --budget 5
```

Add `--no-remote` to scaffold and commit locally without creating anything on
GitHub — useful for a first run-through. `--dir <path>` puts it somewhere other
than `./my-kb`, and `--max-turns` caps turns per scheduled run.

It creates eleven directories and commits them, along with `config.yml`,
`INDEX.md`, `INBOX.md`, `log.md`, `skill-impact.md`, a `drop/README.md`
explaining the drop box, a generated `README.md`, `.gitignore`, `manifest.json`,
and — importantly — `.github/workflows/gates.yml`, the CI workflow that will
gate everything from here on.

## 3. The three GitHub settings

**Do this now.** The workflow existing does not make it authoritative, and
without the first setting the entire gate architecture is decorative.

On your content repo:

1. **Settings → Rules → Rulesets**: make the **`gates` status check required**
   on `main`. Without it, a red pull request still merges on a click.
2. **Settings → General → Pull Requests**: enable **Allow auto-merge**, so a
   green run lands without you.
3. Same page: enable **Automatically delete head branches**. Sessions cannot
   delete remote branches, so `zettel/run-*` accumulates forever otherwise.

Skipped genesis's GitHub creation with `--no-remote`? Push when ready:

```sh
gh repo create <you>/my-kb --private --source=. --remote=origin --push
```

## 4. Your first source

Two routes in, depending on what you have.

### You have an identifier

```sh
"$SCRIPTS/capture.py" --repo my-kb reference --doi 10.1126/science.1199327
```

Crossref fills in the authors, journal, volume and pages, pandoc renders the
Chicago strings, and the note is verified before it is written. But it will tell
you something important:

```
warning: verified via crossref, but nothing is captured in raw/ yet. The merge
gate re-verifies OFFLINE, so this note will not pass it until the source itself
is in the repository -- capture it with fetch_source.py from the open access
copy at http://...
```

That is not a bug. The merge gate re-runs verification with the network turned
off, deliberately, so that no gate can ever pass because of a lucky live lookup.
A bibliographic record is not evidence; the source is. Fetch it:

```sh
"$SCRIPTS/fetch_source.py" --repo my-kb --ref <the-key-it-printed> --url <the open-access url>
```

If that fails — paywalls, dead hosts, JavaScript-only pages — it files an INBOX
entry saying a source is needed rather than inventing anything, and you fall
back to the route below. **This is the honest outcome, not a failure.**

### You have the file

The drop box takes anything you obtained yourself. Make a text file of your
reading notes on a paper — this is what the rest of the tutorial uses:

```sh
cat > ~/karpicke-blunt-2011.txt <<'EOF'
Karpicke, J. D., & Blunt, J. R. (2011). Retrieval Practice Produces More
Learning than Elaborative Studying with Concept Mapping. Science, 331(6018),
772-775. Reading notes taken from the published article.

Students studied science texts and were assigned to one of four conditions:
a single study session, repeated study, elaborative study by building a concept
map, or retrieval practice in which they wrote down what they could recall. One
week later every group took the same test.

Retrieval practice produced the best performance on both verbatim and inference
questions. It beat concept mapping even when the final test was itself a
concept-mapping task, which rules out the explanation that the advantage comes
from matching the format of study to the format of test.

The students predicted the opposite ordering. Learners who built concept maps
judged that they had learned more than the retrieval-practice group did, so
their own sense of how well they had learned ran against the measured result.
EOF

"$SCRIPTS/ingest_drops.py" --repo my-kb --file ~/karpicke-blunt-2011.txt \
  --title "Karpicke and Blunt, Retrieval Practice Produces More Learning" \
  --author "Karpicke, Jeffrey D." --author "Blunt, Janell R." \
  --year 2011 --source-tier peer-reviewed --offline
```

```
ingested	drop/karpicke-blunt-2011.txt	karpicke-and-blunt-retrieval-practice-produces-more-learning--202609070306	raw/202609070306-karpicke-and-blunt-retrieval-practice-produces-more-learning.txt
```

Three things happened: the file moved into `raw/` as immutable evidence, a
gate-clean reference note was written for it, and an INBOX entry now asks the
next run to write the notes. **Nothing in `raw/` is ever edited or deleted** —
it is what your citations rest on.

(Dropping a PDF instead gets you a page-marked text extraction, so notes can
cite `p. N`. A `.txt` has no pages, so locators are paragraph ordinals.)

You can also just `cp` files into `<repo>/drop/` and commit them; the next
scheduled cycle ingests whatever is waiting. GitHub's "Upload files" button
works too.

## 5. The literature note — the source, in your own words

```sh
"$SCRIPTS/capture.py" --repo my-kb literature \
  "Karpicke and Blunt on retrieval versus concept mapping" \
  --reference karpicke-and-blunt-retrieval-practice-produces-more-learning--202609070306 \
  --locator "para. 3" \
  --body "Retrieval practice outperformed concept mapping a week later on both verbatim and inference questions, and the advantage held when the final test was itself a concept map -- so it is not a study-test format match."
```

One source per literature note, always with a locator, always in your own words.
Verbatim text lives only in `raw/`. `--body -` reads stdin, so this composes
with anything.

## 6. The permanent note — one atomic claim

```sh
"$SCRIPTS/capture.py" --repo my-kb permanent \
  "Learners' confidence ranks study methods in the wrong order" \
  --link karpicke-and-blunt-on-retrieval-versus-concept-mapping--202609070307:elaborates \
  --link karpicke-and-blunt-retrieval-practice-produces-more-learning--202609070306:source \
  --body "Students who built concept maps judged they had learned more than students who practised retrieval, while testing showed the reverse. A learner's sense of how well a method is working is therefore not usable as a signal for choosing between methods."
```

The title states a **claim**, not a topic — "Learners' confidence ranks study
methods in the wrong order", never "Metacognition". A claim can be agreed with,
contradicted, or refined by a later note; a topic can only accumulate. That is
the whole bet of the method.

At least one outbound typed link is required, from a closed set of eight:
`supports`, `contradicts`, `analogous`, `shared-concept`,
`historical-connection`, `elaborates`, `refutes`, `source`.

## 7. The map of content

```sh
"$SCRIPTS/capture.py" --repo my-kb moc "Retrieval practice" \
  --note learners-confidence-ranks-study-methods-in-the-wrong-order--202609070308
```

Then link it from `INDEX.md` by hand — `INDEX.md` is prose, not a note, so
editing it directly is fine:

```markdown
## Maps of Content

- [[retrieval-practice--202609070309]]
```

`INDEX.md` links only to MOCs; MOCs link to notes. That layering is what lets a
reader — or a remote session with no clone — walk down from the front page and
reach everything.

## 8. Run the gates

```sh
"$SCRIPTS/remote_cycle.sh" gates --repo my-kb
```

```
reference/karpicke-and-blunt-...--202609070306.md	verified via raw-capture
verify_refs: 1/1 reference(s) verified
build_manifest: manifest.json and .bib/refs.json up to date
lint_citations: clean
lint_links: clean
lint_skills: clean
gates: PASS
```

That is the same sequence the required status check runs, in the same order.

Now break something on purpose, so you know what failure looks like:

```sh
sed -i.bak 's/^  verified: true/  verified: false/' my-kb/reference/*.md
"$SCRIPTS/lint_citations.py" --repo my-kb
```

```
reference/karpicke-...--202609070306.md	unverified-reference	verification.verified is not true; run verify_refs.py or capture the source into raw/
```

`FILE⇥RULE⇥REASON`, exit 1. Now fix it with the tool rather than by hand — the
source is in `raw/`, so an offline re-verify re-establishes the record from the
evidence:

```sh
"$SCRIPTS/verify_refs.py" --repo my-kb --offline
"$SCRIPTS/lint_citations.py" --repo my-kb        # clean again
```

```
reference/karpicke-...--202609070306.md	verified via raw-capture
verify_refs: 1/1 reference(s) verified
```

That is the shape of every gate failure: the tool that owns the state is the
tool that repairs it. Editing a `verification` block by hand would have produced
the same green lint and destroyed the thing it was checking.

**Never make a gate pass by weakening it**, deleting the offending note, or
back-filling a citation you did not verify. Fix the note, or capture the source.
That rule is the product.

## 9. Ask what it knows

```sh
"$SCRIPTS/query.py" --repo my-kb "retrieval practice"
```

```
# What the base knows about: "retrieval practice"

Matched 4 of 4 notes (permanent 1, literature 1, reference 1, moc 1); 0 inquiry(ies) touch it.
Configured topic(s) touched: retrieval practice.

## Claims the base makes (permanent notes)
- **Learners' confidence ranks study methods in the wrong order** -- `learners-confidence...--202609070308`
  sources: karpicke-and-blunt-retrieval-practice-produces-more-learning--202609070306
...
## Gaps
- g1: 2 matched note(s) sit in no map of content, so a reader walking down from
  INDEX cannot find them: `karpicke-and-blunt-...--202609070306`, `karpicke-and-blunt-on-...--202609070307`
```

It found a real gap: the reference and literature notes are not in any map. File
it for the next run, by id:

```sh
"$SCRIPTS/query.py" --repo my-kb "retrieval practice" --file-gaps g1
```

Add `--mermaid` to get a diagram of the links between everything it matched.

## 10. Mine the source for what you have not written yet

```sh
"$SCRIPTS/query.py" --repo my-kb --from-file my-kb/raw/202609070306-*.txt
```

```
4 passage(s) scored against 2 claim-bearing note(s); 0 too short to score.
Source on file as `karpicke-and-blunt-retrieval-practice-produces-more-learning--202609070306`.
No page markers in this extraction, so locators are paragraph ordinals rather than pages.

## Candidate claims (nothing in the base is close) -- 0
## Touches a note (related, but not the same claim) -- 2
## Already stated (the base makes this claim) -- 2
```

Every paragraph of the source, scored against what you have already written.
Candidates come back as ready-to-run `capture.py literature` commands with the
locator filled in — so reading a long source becomes "here are the eleven
passages nobody has written down" rather than "here are ninety pages".

**On a base this small the bands are noise.** Scores are cosines against your
whole corpus, so with four notes almost everything looks related. Passage mode
earns its keep at a few hundred notes; the numbers behind the thresholds are in
[`query.md`](query.md).

## 11. Put it on a schedule

Commit and push what you have, then choose how it grows.

### Laptop cron

```cron
0 6 * * 0  cd $HOME/my-kb && $HOME/auto-zettel-skill/scripts/maintenance_run.sh --repo "$PWD" --mailto you@example.org >> $HOME/.zettel-cron.log 2>&1
```

Cron's `PATH` is minimal — set `PATH=` at the top of your crontab, or export
`CLAUDE_BIN` and `PYTHON` as absolute paths. Test it first with `--dry-run`,
which does everything except push.

### launchd (macOS)

cron is deprecated on macOS; this is the reliable equivalent. Save as
`~/Library/LaunchAgents/org.zettel.maintenance.plist` and
`launchctl load` it:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>org.zettel.maintenance</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/you/auto-zettel-skill/scripts/maintenance_run.sh</string>
    <string>--repo</string><string>/Users/you/my-kb</string>
    <string>--mailto</string><string>you@example.org</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>/usr/local/bin:/usr/bin:/bin</string>
    <key>PYTHON</key><string>/Users/you/auto-zettel-skill/.venv/bin/python</string>
  </dict>
  <key>StartCalendarInterval</key>
  <dict><key>Weekday</key><integer>0</integer><key>Hour</key><integer>6</integer></dict>
  <key>StandardOutPath</key><string>/Users/you/Library/Logs/zettel.log</string>
  <key>StandardErrorPath</key><string>/Users/you/Library/Logs/zettel.log</string>
</dict>
</plist>
```

```sh
launchctl load ~/Library/LaunchAgents/org.zettel.maintenance.plist
launchctl start org.zettel.maintenance     # run it once now, to check
```

### Cloud Routine — the only path that runs with your laptop closed

1. At claude.ai/code, create a **cloud environment** with **Network access:
   Full**. An allowlist breaks source discovery, and makes "unreachable"
   indistinguishable from "does not exist".
2. Paste [`ci/setup-environment.sh`](../ci/setup-environment.sh) into the
   environment's **Setup script** field. It installs the skill, links all four
   skills and all eight agents, and installs the Python dependencies.
3. Create a **Routine** on your cadence, **bound to your content repo as its
   source** — push credentials exist only for a session's source repos, so a
   Routine created without one cannot push.
4. For its prompt, use
   [`scripts/remote_maintenance_prompt.md`](../scripts/remote_maintenance_prompt.md)
   with three substitutions:

   | Placeholder | Replace with |
   |---|---|
   | `{{REPO}}` | the path the content repo is checked out at in the session |
   | `{{SCRIPTS}}` | `/opt/zettel-skill/scripts` |
   | `{{PYTHON}}` | `python3` |

**A Routine's prompt freezes at creation time.** Editing the file later changes
nothing for Routines that already exist — they keep sending the text they were
created with. If you change the prompt, update or recreate the Routine.

## 12. Reading the first run

A cycle appends to `log.md`, one line per step, and that ledger is append-only.
After the first scheduled run:

```sh
git -C my-kb pull
tail -20 my-kb/log.md
```

Look for the `skill-rev=` on the `start` line — absent or old means the install
is stale and everything downstream is suspect. A cycle that appears to have done
nothing has usually **stood down on the lock**, which is a success, not a crash;
the release reason is on the `zettel/lock` branch.

From here the base grows on its own: it works the inquiries you filed, ingests
what you drop, proposes cross-cluster links for review, and — monthly — may
propose a child skill of its own for you to promote or reject.

---

**Next:** [`note-types.md`](note-types.md) for the rules every note obeys ·
[`quality-gates.md`](quality-gates.md) for what each gate rejects ·
[`commands.md`](commands.md) for every flag.

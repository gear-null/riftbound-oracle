# Changelog

Notable changes to the Riftbound skills — `rules-report`, which answers rules questions
with verified citations, and `deck-lab`, which builds and plays out decks.

Entries are drafted with `npm run oracle changelog` — which reads the git history *and* diffs
the corpus — then edited for readability. The **Corpus** section is usually what matters most:
a release exists because Riot changed the rules, not because the code moved.

This project follows [Semantic Versioning](https://semver.org/) and
[Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added

- **Primers — a second kind of report, for questions that aren't rulings.** Ask *"explain
  the HOT FEPR loop"* and the old format fought you: it wanted one holding sentence for a
  five-step state machine, one crux among five equally load-bearing steps, and an opposing
  reading for a phase order nobody disputes. A primer is numbered steps with the
  transitions out of each one, and no verdict. Rulings are unchanged — an answer file
  with no `kind` field is still a ruling, verified and rendered byte-for-byte as before.
- **A transition is a claim, and it must cite the rule that says so.** Prose is where a
  model's fluency does the most damage, so a primer is deliberately *stricter* than a
  ruling in the place a reader acts on: an exit's default basis is `grounded`, so an
  uncited "this sends you to step 4" fails verification instead of rendering as confident
  prose. Declaring it `structural` is allowed and costs what it should — the document's
  confidence drops and the arrow is drawn dashed.
- **A diagram of the procedure, derived rather than drawn.** The map at the top of a
  primer is computed from those cited transitions and from nothing else, so every arrow
  is one of them and every one of them is an arrow — numbered to match the prose beneath.
  There is no field an author can draw an edge in. Recorded as invariant 12 and pinned by
  nine checks, each proven by a mutant.
- **`rules_cli.py graph`** exports the derived graph for surfaces the report does not
  reach. The default is [Fireworks Tech Graph](https://github.com/yizhiyanhua-ai/fireworks-tech-graph)
  IR — a structured document of nodes and arrows, never a prompt, so the diagram stays
  derived — which Fireworks renders as a standalone SVG. `--format=mermaid` still emits
  Mermaid for GitHub markdown. Both refuse on an unverified primer, and the exported
  picture carries its own corpus version and an "unofficial" mark, because it travels
  away from the citations that back it.
- **Three shipped primers**: HOT FEPR (CR 332–340), Showdowns (CR 341–348) and Combat
  (CR 459–466) — 110 citations between them, every one verbatim.
- **Invariant 12** — *a diagram draws exactly the transitions the document declares,
  no more and no fewer*. An arrow is absorbed at a glance and audited by nobody, so
  the map is computed from the declared transitions and shows which kind of claim
  each one rests on: solid for stated outright, dashed for inferred or unsettled, and
  a heavy inverted arrow for one whose citation failed, so a `--force` page has no
  element left claiming everything is fine.
- A shipped HOT FEPR primer (CR 332–340, 33 citations, 12 transitions) as the worked
  example. Run `python3 scripts/check-invariants.py` for the live check and mutant
  counts — a total written into prose here only goes stale.
- **`deck-lab` — a second skill, for building decks and playing them out.** Deck design
  needs games, and games were the expensive part: an agent asked to imagine a shuffle
  imagines a convenient one. So the skill simulates the *table*, not the player — it
  deals, tracks the board, enforces the rules and refuses illegal actions, and leaves
  every decision to whoever is playing. It carries a gauntlet of real tournament lists
  to test against, imported from decklist text because four of the six sites that
  publish them block scripts. See [ADR 0007](docs/adr/0007-the-table-not-the-player.md).
- **The table refuses rather than assumes.** It never interprets card text — it prints
  it verbatim and stops. A table that quietly applies an effect it half-understands
  turns every card it does not handle into a confident wrong game, which is worse than
  no table at all. Rules it *does* enforce are cited in the code and pinned by a
  mutation battery, on the same terms as the rules-report skill.

### Fixed

- **Packaging checked the first skill and reported on all of them.** Five places made
  that assumption, and none of them could have failed while only one skill existed —
  these are defects the second skill *revealed*, not ones it caused. CI ran
  `unzip -q dist/*.zip`, which takes the first archive and reads the rest as member
  names *inside* it, so the job that proves an install works was one glob-ordering away
  from passing while installing nothing. The reproducibility check compared only the
  first checksum; the stale-manifest check named `rules-report` outright; the licence
  test asserted `rules-report/LICENSE` by name; and the "records nothing
  self-referential" invariant, which exists so a release rebuilds from its own tag,
  called one of the two manifest producers — a commit hash in the other passed the
  entire suite. All five now iterate the skill registry, and CI runs the verify command
  each skill's manifest names, which meant shipping `verify` into `SKILL-VERSION.json`
  so an archive knows how to check itself.
- **Running the tests no longer edits tracked files.** Packaging rewrote each skill's
  committed `SKILL-VERSION.json` unconditionally, which is right for
  `npm run oracle package` and a trap from a test: the licence test packages at a
  throwaway version, so merely running the suite rewrote a manifest to a version that
  does not exist — `rules-report`'s as readily as `deck-lab`'s — and a `git add -A`
  then committed it. `SKILL-VERSION.json` is the file a consumer reads to know what
  they have. The source-tree write is now opt-in and `oracle package` is the only
  caller that asks for it, so forgetting the flag is safe rather than damaging; the
  archive's manifest is written separately, and states the version it was actually
  built at either way.
- **A deck name claimed by two files is refused instead of silently picked.** `resolve()`
  promised "gauntlet first, then decks/" and delivered the reverse — `available()` sorts
  full paths and `decks` sorts before `gauntlet` — so a personal draft answered to a
  tournament list's name and every number downstream described the wrong deck. Neither
  order is right: whichever directory loses, a real deck is discarded without a word.
  It now names both files and asks which you meant.
- **A missing licence now stops the build** instead of being skipped by an `existsSync`.
  A renamed or moved `LICENSE` silently restored the unlicensed archive that work existed
  to prevent, which is worse than never having fixed it: the fix is what stops anyone
  looking again.
- **Permanents left in another player's base are recalled at cleanup (CR 323.7)**, along
  with unattached Gear left at a battlefield. A unit walked into the enemy base used to
  stay there for the rest of the game, reading on the board as a presence it does not
  have. The rule had no implementation at all, so no guard sweep could have found it —
  it turned up by constructing board states no fixture builds.

## [1.2.1] — 2026-08-20

### Fixed

- **Questions that are not yes/no questions no longer get a yes/no verdict.**
  The disposition vocabulary offered `YES | NO | DEPENDS | UNSETTLED` and nothing
  else, so a shipped example answered *"How much energy does Vi - Hotheaded
  cost?"* with **YES**. `ANSWER` is the open-question case: the report prints no
  verdict word and leads with the holding sentence, which is the answer. The
  other four are unchanged and now appear only where a one-word answer is real,
  which is what makes them worth reading at a glance.
- **The disposition is validated.** It is rendered as a CSS class as well as a
  label, and any string was accepted — so a value containing spaces became
  several bogus classes (`d-IT DEPENDS ON THE ZONE`) and silently disabled the
  print sheet keyed on that name. It is now a closed set, refused at
  verification.

The citation gate is untouched: an open question whose citation fails is still
forced to `UNSETTLED`, and a check asserts it so a new disposition cannot route
around the gate.


## [1.2.0] — 2026-08-20

### Corpus

- **52 cards corrected from Riot errata, up from 28.** An entire Riot article was
  being skipped (its headings use a different depth), and the corrections that
  did parse were matched to cards by exact name — so `Jax, Unmatched` never met
  `Jax - Unmatched`. Six cards had been serving text Riot retracted, with no
  banner: Tianna Crownguard said "opponents can't score points" where Riot now
  says "can't gain points", and CR 471 splits those.
- **Riot's illustrations are no longer normative text.** Six rules had absorbed a
  plural `Examples:` list into their own wording, where a quote of an
  illustration verified as a quote of the rule. 262 → 286 examples.
- **The corpus version is read from each document** rather than stamped from one
  hardcoded literal, so CR and TR can differ — which the provenance check
  assumed and could never actually detect.

### Added

- **The report and rulebook, rebuilt in the Runeterra visual language** (#6):
  blue-black ground, aged-gold hairlines, a sticky claim rail that tracks the
  claim you are reading, and a rulebook overlay that keeps your place. Printing
  inverts the whole system to a light sheet, because judges print these.
- **A mutation battery** — `rules_cli.py mutants`. It reintroduces 113 known
  defects and requires the named check to fail. Two review rounds were spent
  discovering that checks can pass while the defect they are named for is live;
  this is what makes that visible.
- **`docs/invariants.md`** — the eleven statements that must never be false, each
  pinned by a check that has been observed to fail, enforced in CI by
  `scripts/check-invariants.py`. It replaces "review until nothing is found",
  which does not terminate.
- **`docs/known-issues.md`** — what was found, reproduced, and deliberately not
  fixed.

### Fixed

- **A quote welded across a block boundary passed the verbatim gate** — a string
  appearing nowhere in Riot's rules, stamped verified. Blocks are now matched
  separately and never joined.
- **A missing answer file was answered with a shipped sample**, printing
  "8/8 verified verbatim" and exiting 0 for a question nobody asked.
- **`grep` displayed the opposite of a rule.** Text was clipped at 110 characters
  with no marker, and 142 rules hide a "not" or "unless" past the cut. It also
  reported "no matches" for terms that exist, because FTS5 rejected the syntax
  and the rejection was reported as absence.
- **`rule <id>` dead-ended on 80 topic headings**, 37 of which are
  cross-reference targets — indistinguishable from "the rules are silent".
- Citations are attributed to the rule whose own text carries the quote, ties are
  reported rather than guessed, and a whitespace-only quote no longer verifies.

### CI

- The mutation battery and the invariant gate both run on every push.
- don't schedule the watcher — hosted CI cannot reach either upstream (89c9f98)
- watch upstream daily, propose a regeneration, never publish one (134e0bf)
- guard main, because main is what `npx skills add` installs (05eeade)


### Added

- **`npm run oracle watch`** — checks Riftcodex for a new set or changed card counts in a
  single request and reports what moved. A workflow does the full detect → regenerate → open-a-PR
  flow on manual dispatch, never publishing and never pushing to `main`. It is not scheduled:
  both upstreams block hosted CI at the IP level, so checking upstream is a local task.
- **CI on every push and pull request.** `main` is a live distribution channel — `npx skills
  add` installs from it — so the corpus checks now run automatically rather than when someone
  remembers. Three jobs: the skill exactly as a registry install receives it (Python 3.9 and
  3.13, no build step), the pipeline (typecheck, tests, build), and archive reproducibility.

## [1.1.0] — 2026-08-13

### Added

- **Install with `npx skills add gear-null/riftbound-oracle`.** The repo was already
  installable through Vercel's skills CLI — verified: it resolves the skill, installs 3.8MB
  including the corpus, and passes all 98 checks across 17+ terminal agents. This is now the
  primary instruction.
- **One-line installer.** `curl -fsSL .../install.sh | sh` resolves the latest release,
  verifies its published checksum, installs to `.claude/skills/` and runs the selftest to
  prove the corpus is intact. `--dir` puts it wherever another agent looks for skills.
  The old instructions hardcoded a version that went stale on every release and never
  checked the checksum we were already publishing. It remains the path for machines without
  Node.

### Changed

- README rewritten for people deciding whether to install, rather than people maintaining it.
  Design rationale and build instructions moved to `docs/`.

### Fixed

- **Release archives now reproduce from their own tag.** The version manifest recorded the
  commit it was built from — but the manifest is itself committed, so that hash could never
  settle: build at A, commit, and the next build says B. A published archive could not be
  rebuilt from the tag that shipped it, which is the entire point of a reproducible build.
  The field is gone; the version names the release and the tag names the commit.
- **`SKILL-VERSION.json` is committed, not injected at package time.** A registry install
  clones from git and never sees the archive, so its provenance file did not exist — a user
  had no way to tell which corpus they had. Every channel now carries it.

## [1.0.1] — 2026-08-12

### Corpus

- **All 27 equipment cards now carry the effect they grant once attached.** Riftcodex serves
  only the `[Equip]` clause for these; the granted ability and its `+N Might` badge are
  printed in a band at the foot of the card and reach no API field. All 27 are now
  transcribed from the artwork into `manifests/card-overlays.yaml`, with the source image
  recorded for each.
- No cards remain flagged as incomplete.

### Fixed

- An untranscribed equipment card now **fails** the selftest rather than emitting a note. The
  previous release shipped 25 of them: their text was accurate and carried a visible "printed
  text incomplete" warning, but a reader asking what Boneshiver grants got a caveat instead of
  an answer.

[1.1.0]: https://github.com/gear-null/riftbound-oracle/releases/tag/v1.1.0
[1.0.1]: https://github.com/gear-null/riftbound-oracle/releases/tag/v1.0.1

## [1.0.0] — 2026-08-12

First packaged release. The skill installs by unzipping one folder — no Node, no build step,
no network, no API key.

### Corpus

- Rules **2026-07-16** — 3,316 addressable rules across the Core and Tournament documents.
- 954 cards, including the Vendetta set.
- **28 cards corrected from Riot's published errata.** The upstream card database lags Riot by
  months; where the two disagree, Riot wins and the card records provenance.
- 25 equipment cards still awaiting transcription — the effect they grant once attached is
  printed only on the artwork and reaches no API field. They are flagged in-product rather
  than shown as complete.

### Added

- **Citation verification.** Every cited rule must exist and every quote must appear verbatim,
  checked by code before a report renders. A failure forces the verdict to `UNSETTLED`.
- **Anchored rulebook.** All 3,316 rules rendered with stable anchors, opened in an overlay
  over the report so following a citation costs you nothing.
- **Card panels** with artwork, structured stats and links to the glossary sections a card's
  keywords map onto.
- **Symbol legend** derived from the rules themselves (CR 134.2, 135.2.e, 429.5), covering only
  the shorthand on that page.
- **Numbered claims** with superscripts, a stated crux, and confidence reported as the weakest
  link rather than an average.
- `oracle package` — a byte-reproducible archive plus checksum, carrying `SKILL-VERSION.json`
  so a downloaded copy can be dated against a later rules update.
- `oracle gear-gaps` — collects artwork and a pre-filled stub for cards the API cannot supply.

### Notes

- Requires Python 3.9+ and nothing else.
- Card artwork loads from Riot's CDN at view time. Viewers that block remote images show a
  placeholder; set `RIFTBOUND_EMBED_ART=1` to inline it instead.
- No card artwork is redistributed in the archive.

[1.0.0]: https://github.com/gear-null/riftbound-oracle/releases/tag/v1.0.0

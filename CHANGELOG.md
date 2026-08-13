# Changelog

Notable changes to the Riftbound rules-report skill.

Entries are drafted with `npm run oracle changelog` — which reads the git history *and* diffs
the corpus — then edited for readability. The **Corpus** section is usually what matters most:
a release exists because Riot changed the rules, not because the code moved.

This project follows [Semantic Versioning](https://semver.org/) and
[Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

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

<p align="center">
  <img src="riftbound-oracle.png" alt="Riftbound Oracle" width="100%" />
</p>

# Riftbound Oracle

**Riftbound rules answers you can actually check.**

Ask your AI agent a rules question. Get back a verdict, the reasoning split into
individually-graded claims, and every citation one click away from the rule it rests on.

Ask a chatbot the same question and it will cite `471.1.b.1` with total confidence whether or
not that rule exists. Across 7,774 community-written answers to real Riftbound questions,
**29% of rule citations point at an ID that doesn't exist at all.**

This one can't do that. Before a report is rendered, a verifier proves every cited rule exists
and every quote appears verbatim. A citation that fails doesn't get softened — it forces the
whole answer to `UNSETTLED`.

![A Riftbound Oracle report: a hard two-card ruling, with the verdict decomposed into graded claims](docs/images/report.png)

---

## Install

```bash
npx skills add gear-null/riftbound-oracle
```

Claude Code, Cursor, Codex, Gemini CLI, GitHub Copilot and a dozen more. **Python 3.9+** is
the only requirement — the one macOS already ships. No build, no API key, no account.

Then just ask:

```
Does a countered Flow spell still get banished?
```

```
Unchecked Power deals 12 damage to all units at battlefields. Player 2 has
Viktor, Leader and two Vanguard Sergeants. How many Recruits do they play?
```

Your agent looks up the cards, walks the rulebook, writes the answer, verifies it, and opens
the report. You never run a command.

<details>
<summary>Claude Desktop, mobile, and installing without Node</summary>

**Desktop and mobile apps** take a file instead. Download the `.zip` from
[Releases](https://github.com/gear-null/riftbound-oracle/releases/latest) and upload it as a
skill. Those apps block remote images, so set `RIFTBOUND_EMBED_ART=1` to inline the card
artwork.

**No Node?** Same release, verified against its published checksum:

```bash
curl -fsSL https://raw.githubusercontent.com/gear-null/riftbound-oracle/main/install.sh | sh
```

**Anywhere else.** It's a plain folder of Python and data — no runtime, no daemon, no install
hooks. Drop it where your agent keeps skills and point it at `SKILL.md`.

Text-only skill surfaces (Gemini Spark, for one) can't run it. The answers come from executing
a verifier against a corpus, not from prose an agent reads.

**Check it's healthy** any time with `python3 rules_cli.py selftest` from the skill's `lib/`.

</details>

---

## What makes it worth installing

**Every citation is followable.** Click a rule and the full rulebook opens over the report,
scrolled to the exact clause with its cross-references live — without losing your place in the
argument.

![The anchored rulebook, opened over the report on the exact clause a claim rests on](docs/images/rulebook-overlay.png)

**It tells you when it doesn't know.** When the rules genuinely don't settle something, you get
`UNSETTLED` and a list of what was searched — not a confident guess. Refusal is a rare quality
in a language model.

**You always know the weakest step.** Confidence is the floor, never the average: nine solid
claims and one inference make an *inferred* answer, and the report names which claim is the
soft one.

**Cards show up, and they're right.** Artwork, stats and printed text for everything the answer
touches — with Riot's published errata applied. The card database the rest of the ecosystem
reads is months behind; 28 cards here say what Riot actually ruled.

**It works on a plane.** Rules, cards and rulebook all ship with the skill, so answering needs
no network at all — only the card artwork loads remotely, when you open a report.

---

## Documentation

| | |
|---|---|
| [Reading a report](docs/report-anatomy.md) | What the grades, superscripts and symbol legend mean |
| [Changelog](CHANGELOG.md) | What changed, and which rules version each release ships |
| [Contributing & design notes](docs/README.md) | How it's built, and what was measured to decide that |

Riftbound is a trademark of Riot Games. This project is **unofficial and not endorsed by Riot**.
No card artwork is redistributed — reports load it from Riot's CDN.

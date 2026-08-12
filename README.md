<p align="center">
  <img src="riftbound-oracle.png" alt="Riftbound Oracle" width="100%" />
</p>

# Riftbound Oracle

**An agent skill that answers Riftbound TCG rules questions with citations you can
actually check.**

Ask your AI agent a rules question. Get back an interactive report: a one-line verdict,
the reasoning broken into individually-graded claims, and every citation expandable to
the real rule text — with a link straight into the rulebook.

Before the report is written, a deterministic verifier proves that every cited rule
exists and that every quote appears verbatim. **A citation that fails cannot reach you.**

Runs entirely on your machine, on whatever agent you already use. Install by copying one
folder — no build step, no API key, and no network needed to install or to answer. (Card
artwork in a report loads from Riot's CDN; offline it shows a placeholder and everything
else still works.)

![A Riftbound Oracle report: a hard two-card ruling, with the verdict decomposed into graded claims](docs/images/report.png)

---

## Install

Download the latest release and unzip it into your project:

```bash
mkdir -p .claude/skills
curl -L -o skill.zip https://github.com/gear-null/riftbound-oracle/releases/latest/download/riftbound-rules-report-v1.0.0.zip
unzip skill.zip -d .claude/skills/ && rm skill.zip
```

Or grab the zip from [Releases](https://github.com/gear-null/riftbound-oracle/releases/latest)
and upload it wherever your agent takes skills.

**Requires Python 3.9+** — the interpreter macOS already ships. No Node, no build step, no
network, no API key. Check it works:

```bash
cd .claude/skills/rules-report/lib && python3 rules_cli.py selftest
```

It should end `all N checks passed`. If it doesn't, the corpus is not trustworthy yet — say
so rather than asking questions against it.

<details>
<summary>Verifying the download</summary>

Each release ships a `.sha256` beside the archive, and the build is byte-reproducible — the
same corpus always produces the same checksum.

```bash
shasum -a 256 -c riftbound-rules-report-v1.0.0.zip.sha256
```

`SKILL-VERSION.json` inside the archive records the rules version and card counts it was built
from, so you can tell whether your copy predates a Riot update.
</details>

## Ask it something

In Claude Code the skill is picked up automatically — just ask:

```
Does a countered Flow spell still get banished?
```

```
Unchecked Power deals 12 damage to all units at battlefields. Player 2 has
Viktor, Leader and two Vanguard Sergeants. How many Recruits do they play?
```

The agent looks up any named cards exactly, navigates the rulebook, writes a structured
answer, verifies it, and opens the report. **You never run a command yourself.**

---

## Why it's different

**It cites rules, not vibes.** Every Riftbound rule has a canonical address like
`471.1.b.1`, so the system cites addresses and then checks them mechanically. For
comparison, in 7,774 community-written answers to real questions, **29% of rule
citations point at an ID that doesn't exist.**

**It refuses.** When the rules don't settle something, it says `UNSETTLED` and names the
gap rather than reaching for a plausible answer. Abstention is held to the same standard
as assertion: a claim that the rules are silent has to show what it searched.

**Confidence is a floor, not an average.** Nine solid claims plus one inference makes an
inferred answer, and the report says so. You always know the weakest step.

**You can follow every citation.** Clicking a rule opens the full anchored rulebook over
the report — scrolled to the exact clause, with its own cross-references live, without
losing your place.

![The anchored rulebook, opened over the report on the exact clause a claim rests on](docs/images/rulebook-overlay.png)

---

## Using a different agent

Nothing here is Claude-specific. `SKILL.md` is plain markdown describing a procedure,
and the tools are ordinary CLI programs. Give your agent `SKILL.md` as instructions and
shell access to `lib/`.

The parts that must not be improvised — does this rule exist, does it say this verbatim,
which rule is the tightest one that says it — are enforced by code, not by the model's
good intentions. If an agent produces an answer whose citations fail, the report refuses
to render. That is the intended behaviour.

## Documentation

| | |
|---|---|
| [How to read a report](docs/report-anatomy.md) | What the grades, superscripts and legend mean |
| [Decision records](docs/README.md#decision-records) | Why it's built this way, and what was measured |
| [Content and licensing](docs/content-and-licensing.md) | What's committed, and what is deliberately not |
| [Changelog](CHANGELOG.md) | What changed in each release |

**Maintaining or contributing?** Everything about building the corpus, cutting a release and
the invariants to preserve lives in [`docs/`](docs/README.md) — none of it is needed to use
the skill.

Riftbound is a trademark of Riot Games. This project is **unofficial and not endorsed by
Riot**. No card artwork ships in the corpus — reports load it from Riot's CDN.

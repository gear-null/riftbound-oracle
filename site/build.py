#!/usr/bin/env python3
"""Regenerate the parts of site/ that are derived from the skill.

This is a MAINTENANCE tool, not a build step. Everything it writes is committed
static HTML; GitHub Pages serves site/ as-is and nothing here runs at request
time. Run it after a rules update, or after a primer is re-verified:

    python3 site/build.py

What it derives, and from where — all of it read-only, nothing outside site/ is
written:

  .claude/skills/rules-report/lib/<topic>-primer.json  -> site/<topic>.html
  .claude/skills/rules-report/data/diagrams/*.svg      -> site/diagrams/*.svg
  .claude/skills/rules-report/data/rules.html          -> site/rulebook.html
  .claude/skills/rules-report/reports/*.html           -> site/reports/*.html
  docs/images/*.png, riftbound-oracle.png              -> site/img/*.png

The explainer pages are generated rather than written by hand for the same
reason the diagrams are: their prose, their citations and their transition
numbering all belong to the verified primer document, and a hand-kept copy
drifts. Transition numbers here are computed exactly as flowgraph.py computes
them — global, in document order, every exit consuming a number including the
ones that leave the procedure — so arrow 7 on the map is item 7 in the prose.

Every cited rule ID is checked against the anchors in the generated rulebook
before a page is written. A citation that cannot resolve is a hard failure, not
a dead link.
"""

from __future__ import annotations

import html
import json
import re
import shutil
import sys
from pathlib import Path

SITE = Path(__file__).resolve().parent
REPO = SITE.parent
SKILL = REPO / ".claude" / "skills" / "rules-report"

TOPICS = [
    # slug, primer json, nav label, page title
    ("hot-fepr", "hot-fepr-primer.json", "HOT&nbsp;FEPR", "HOT FEPR"),
    ("combat", "combat-primer.json", "Combat", "Combat"),
    ("showdowns", "showdowns-primer.json", "Showdowns", "Showdowns"),
]

REPORTS = [
    ("flow-counter.html", "ruling-flow-counter.html"),
    ("hot-fepr-primer.html", "primer-hot-fepr.html"),
]

IMAGES = [
    (REPO / "docs" / "images" / "report.png", "report.png"),
    (REPO / "docs" / "images" / "primer.png", "primer.png"),
    (REPO / "docs" / "images" / "rulebook-overlay.png", "rulebook-overlay.png"),
    (REPO / "riftbound-oracle.png", "banner.png"),
]

MARK = (
    '<svg class="mark" viewBox="0 0 96 96" role="img" aria-label="Riftbound Oracle">'
    '<path d="M22 10 L74 10 L86 22 L86 74 L74 86 L22 86 L10 74 L10 22 Z" fill="none"'
    ' stroke="#c8aa6e" stroke-width="2.5"/>'
    '<circle cx="48" cy="48" r="25" fill="none" stroke="#c8aa6e" stroke-width="3"/>'
    '<path d="M30.61 43.34 A18 18 0 0 1 43.34 30.61" fill="none" stroke="#e4f1f5"'
    ' stroke-width="3" stroke-linecap="round"/>'
    '<path d="M48 37 L50.4 45.6 L59 48 L50.4 50.4 L48 59 L45.6 50.4 L37 48 L45.6 45.6 Z"'
    ' fill="#3c8fe0"/></svg>'
)

FAVICON = (
    "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 96 96'>"
    "<path d='M22 10 L74 10 L86 22 L86 74 L74 86 L22 86 L10 74 L10 22 Z' fill='none'"
    " stroke='%23c8aa6e' stroke-width='4'/>"
    "<path d='M48 30 L52.8 47.2 L70 52 L52.8 56.8 L48 74 L43.2 56.8 L26 52 L43.2 47.2 Z'"
    " fill='%233c8fe0'/></svg>"
)

NAV = [
    ("index.html", "Overview"),
    ("hot-fepr.html", "HOT&nbsp;FEPR"),
    ("combat.html", "Combat"),
    ("showdowns.html", "Showdowns"),
    ("rulebook.html", "Rulebook"),
    ("samples.html", "Sample reports"),
]

# The basis vocabulary, printed the same way a report prints it: glyph AND word,
# so it is never carried by colour alone.
BASIS = {
    "grounded": ("●", "Grounded", "on"),
    "structural": ("▲", "Structural", "blue"),
    "gap": ("○", "Gap", ""),
}

FOOTER = """<footer data-od-id="site-footer">
  <div class="wrap">
    <div class="cols three">
      <div>
        <h4>Riftbound Oracle</h4>
        <p>An unofficial rules companion for Riftbound, the League of Legends Trading Card
        Game. Rules answers with citations a machine has already checked.</p>
      </div>
      <div>
        <h4>On this site</h4>
        <ul>
          <li><a href="hot-fepr.html">HOT FEPR primer</a></li>
          <li><a href="combat.html">Combat primer</a></li>
          <li><a href="showdowns.html">Showdowns primer</a></li>
          <li><a href="rulebook.html">Anchored rulebook</a></li>
          <li><a href="samples.html">Sample reports</a></li>
        </ul>
      </div>
      <div>
        <h4>Project</h4>
        <ul>
          <li><a href="https://github.com/gear-null/riftbound-oracle">Source on GitHub</a></li>
          <li><a href="https://github.com/gear-null/riftbound-oracle/blob/main/docs/report-anatomy.md">How to read a report</a></li>
          <li><a href="https://github.com/gear-null/riftbound-oracle/blob/main/CHANGELOG.md">Changelog</a></li>
          <li><a href="https://github.com/gear-null/riftbound-oracle/blob/main/LICENSE">Licence (MIT)</a></li>
        </ul>
      </div>
    </div>
    <div class="disclaim">
      <p style="max-width:78ch">Riftbound is a trademark of Riot Games. This project is
      <b>unofficial and not endorsed by, affiliated with, or sponsored by Riot Games</b>. The
      code is MIT. The Riftbound rules text and card text are Riot Games' copyright, included
      so a citation can be checked verbatim against the document it quotes, and used under
      Riot's policy for community projects &mdash; they travel under Riot's terms, not MIT. No
      card artwork is redistributed: reports reference Riot's CDN by URL, and a reader with no
      network sees a labelled placeholder. Riot's Beaufort and TT Norms are proprietary and are
      not redistributed either; this site loads no fonts and renders in the open fallbacks the
      reports declare.</p>
    </div>
  </div>
</footer>
</body>
</html>
"""


def e(text: str) -> str:
    return html.escape(str(text), quote=True)


def head(title: str, description: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark">
<title>{e(title)}</title>
<meta name="description" content="{e(description)}">
<link rel="stylesheet" href="assets/site.css">
<link rel="icon" href="{FAVICON}">
</head>
<body>
<div class="grain" aria-hidden="true"></div>
<a class="skip" href="#content">Skip to content</a>
"""


def masthead(current: str) -> str:
    def link(href: str, label: str) -> str:
        mark = ' aria-current="page"' if href == current else ""
        return '      <a href="{}"{}>{}</a>\n'.format(href, mark, label)

    links = "".join(link(href, label) for href, label in NAV)
    return f"""<header class="masthead" data-od-id="site-masthead">
  <div class="wrap masthead-in">
    {MARK}
    <a class="wordmark" href="index.html"><span class="eyebrow">Riftbound</span><b>Oracle</b></a>
    <span class="unofficial">Unofficial rules companion</span>
    <nav class="nav" aria-label="Primary">
{links}    </nav>
  </div>
</header>
"""


def rule_href(rule_id: str) -> str:
    """`CR:337.2` -> `rulebook.html#CR-337.2`, the anchor render_rulebook.py emits."""
    return "rulebook.html#" + rule_id.replace(":", "-", 1)


def rule_label(rule_id: str) -> str:
    prefix, _, num = rule_id.partition(":")
    return f"{prefix} {num}"


def cite_list(cites: list[dict]) -> str:
    rows = []
    for c in cites:
        rows.append(
            f'    <li><a class="rid" href="{rule_href(c["rule"])}">{e(rule_label(c["rule"]))}</a>'
            f'<span class="quote">{e(c["quote"])}</span></li>'
        )
    return '  <ul class="cites">\n' + "\n".join(rows) + "\n  </ul>"


def number_exits(steps: list[dict]) -> list[tuple[int, int, dict]]:
    """(number, step index, exit) — flowgraph.py's global document-order numbering.

    Every exit consumes a number, including one with no `goto`. Skipping those
    would renumber the rest and break the correspondence between the arrow on
    the map and the item in the prose.
    """
    out, n = [], 0
    for i, step in enumerate(steps):
        for ex in step.get("exits") or []:
            n += 1
            out.append((n, i, ex))
    return out


def explainer(slug: str, primer: dict, anchors: set[str]) -> str:
    steps = primer["steps"]
    topic = primer["topic"]
    numbered = number_exits(steps)
    by_step: dict[int, list[tuple[int, dict]]] = {}
    for n, i, ex in numbered:
        by_step.setdefault(i, []).append((n, ex))
    order = {s["id"]: i for i, s in enumerate(steps)}
    grounded = sum(1 for s in steps if s.get("basis", "grounded") == "grounded")
    structural_exits = sum(
        1 for _, _, ex in numbered if ex.get("basis", "grounded") != "grounded"
    )
    corpus = primer.get("corpus", {})

    parts = [
        head(
            f"{topic} — Riftbound Oracle primer",
            f"{primer['in_one_line']} Every step and every transition cites the rule that says so.",
        ),
        masthead(f"{slug}.html"),
        '<main id="content">\n',
        # ── title plate ───────────────────────────────────────────────────
        f"""<section class="wrap" data-od-id="primer-head">
  <span class="crumb"><a href="index.html">Overview</a> &nbsp;/&nbsp; Diagram explainers</span>
  <div class="split wide-left">
    <div>
      <p class="eyebrow">Primer &middot; derived from verified transitions</p>
      <h1>{e(topic)}</h1>
      <p class="lede">{e(primer["in_one_line"])}</p>
      <p class="muted">This page covers {e(primer["reframe"])}</p>
    </div>
    <div class="plate rimlit">
      <div class="pad">
        <p class="eyebrow cool">The question it answers</p>
        <p class="ask">{e(primer["question"])}</p>
        <div class="metrics">
          <div class="metric"><b>Steps</b><span>{len(steps)}</span></div>
          <div class="metric"><b>Stated outright</b><span>{grounded}/{len(steps)}</span></div>
          <div class="metric"><b>Transitions</b><span>{len(numbered)}</span></div>
        </div>
        <p class="fine" style="margin:1rem 0 0">Core Rules {e(corpus.get("CR", "—"))} &middot;
        Tournament Rules {e(corpus.get("TR", "—"))} &middot; verified
        {e(corpus.get("generated", "—"))}</p>
      </div>
    </div>
  </div>
</section>
""",
        # ── the map ───────────────────────────────────────────────────────
        f"""<section class="wrap" data-od-id="primer-diagram">
  <p class="eyebrow">The map</p>
  <figure>
    <div class="plate diagram">
      <div class="diagram-scroll">
        <img src="diagrams/{slug}.svg" alt="{e(topic)}: {len(steps)} steps down the left with the {len(numbered)} transitions between them drawn as numbered arrows. Each number matches a numbered transition in the text below.">
      </div>
    </div>
    <p class="fine pan-hint">Wide diagram &mdash; drag it sideways to follow an arrow.</p>
    <figcaption>Computed from the cited transitions below and from nothing else &mdash; every
    arrow here is one of them, and every one of them is here. There is no field in which an
    author can draw an edge. A solid arrow is a move a rule states outright; a dashed one
    follows from the rules cited. The numbering is shared: arrow&nbsp;7 on the map is
    item&nbsp;7 in the prose. Rendered by
    <a href="https://github.com/yizhiyanhua-ai/fireworks-tech-graph">Fireworks Tech Graph</a> in
    its Blueprint style, and shipped exactly as generated.</figcaption>
  </figure>
</section>
""",
        '<section class="wrap" data-od-id="primer-steps">\n  <p class="eyebrow">The steps</p>\n',
    ]

    for i, step in enumerate(steps):
        glyph, word, tone = BASIS.get(step.get("basis", "grounded"), BASIS["grounded"])
        chip = f'<span class="chip {tone}">{glyph} {word}</span>' if tone else f'<span class="chip">{glyph} {word}</span>'
        parts.append(
            f"""  <article class="plate on-well step" id="{e(step["id"])}" data-od-id="step-{e(step["id"])}">
   <div class="pad">
    <div class="step-head">
      <span class="step-n">{i + 1}</span>
      <h3>{e(step["heading"])}</h3>
      {chip}
    </div>
    <p>{e(step["body"])}</p>
{cite_list(step["cites"])}
"""
        )
        exits = by_step.get(i, [])
        if exits:
            parts.append('    <p class="eyebrow cool" style="margin:1.6rem 0 0">Where you go next</p>\n    <ul class="exits">\n')
            for n, ex in exits:
                dashed = ex.get("basis", "grounded") != "grounded"
                goto = ex.get("goto")
                if goto is not None and goto in order:
                    j = order[goto]
                    target = (
                        f'<span class="exit-goto">Go to step <b>{j + 1} &mdash; '
                        f'{e(steps[j]["heading"])}</b></span>'
                    )
                else:
                    target = '<span class="exit-goto">The procedure <b>ends here</b></span>'
                cites = " &middot; ".join(
                    f'<a href="{rule_href(c["rule"])}">{e(rule_label(c["rule"]))}</a>'
                    for c in ex["cites"]
                )
                basis_note = (
                    ' <span class="chip blue">▲ Structural</span>' if dashed else ""
                )
                parts.append(
                    f"""      <li>
        <span class="exit-n{' dashed' if dashed else ''}" aria-hidden="true">{n}</span>
        <div>
          <span class="exit-when">{e(ex["when"])}</span>
          {target}
          <p class="exit-cites">Because {cites}{basis_note}</p>
        </div>
      </li>
"""
                )
            parts.append("    </ul>\n")
        parts.append("   </div>\n  </article>\n")
    parts.append("</section>\n")

    # ── misconceptions ────────────────────────────────────────────────────
    if primer.get("misconceptions"):
        parts.append(
            '<section class="wrap" data-od-id="primer-misconceptions">\n'
            '  <p class="eyebrow">Commonly believed, and wrong</p>\n'
            '  <ul class="misc">\n'
        )
        for m in primer["misconceptions"]:
            cites = " &middot; ".join(
                f'<a href="{rule_href(c["rule"])}">{e(rule_label(c["rule"]))}</a>'
                for c in m["cites"]
            )
            parts.append(
                f"""    <li>
      <p class="belief">{e(m["belief"])}</p>
      <p class="why"><b>Why that's wrong</b>{e(m["why_wrong"])}</p>
      <p class="exit-cites">{cites}</p>
    </li>
"""
            )
        parts.append("  </ul>\n</section>\n")

    # ── considered and rejected ───────────────────────────────────────────
    if primer.get("considered_rejected"):
        rows = "".join(
            f'      <tr><td><a class="rid" href="{rule_href(r["rule"])}">'
            f'{e(rule_label(r["rule"]))}</a></td><td>{e(r["why"])}</td></tr>\n'
            for r in primer["considered_rejected"]
        )
        parts.append(
            f"""<section class="wrap" data-od-id="primer-rejected">
  <p class="eyebrow">Read and left out</p>
  <p>Rules that came up while this was written and were deliberately not made steps. Saying
  which near-misses were rejected, and why, is cheaper for a reader to audit than a silent
  omission.</p>
  <table>
    <thead><tr><th scope="col">Rule</th><th scope="col">Why it is not a step here</th></tr></thead>
    <tbody>
{rows}    </tbody>
  </table>
</section>
"""
        )

    parts.append(
        f"""<section class="wrap tight" data-od-id="primer-provenance">
  <div class="plate on-well">
    <div class="pad">
      <p class="eyebrow cool">Provenance</p>
      <p class="fine" style="max-width:74ch">Every quote on this page was checked against the
      rule it names before the page was written: the rule has to exist in the corpus, and the
      quoted span has to appear verbatim inside it. Each rule ID links into
      <a href="rulebook.html">the anchored rulebook</a> at the exact clause.
      {("Of the " + str(len(numbered)) + " transitions, " + str(structural_exits) +
        " is declared structural &mdash; it follows from the rules cited rather than being stated outright &mdash; and is drawn dashed."
        ) if structural_exits == 1 else
       (("Of the " + str(len(numbered)) + " transitions, " + str(structural_exits) +
         " are declared structural and drawn dashed.") if structural_exits else
        "All " + str(len(numbered)) + " transitions are stated outright by a rule.")}
      This page is generated from the same primer document the diagram is
      &mdash; see <code>site/build.py</code>.</p>
    </div>
  </div>
</section>
"""
    )

    parts.append("</main>\n")
    parts.append(FOOTER)
    body = "".join(parts)

    # Every rule ID on the page must resolve to an anchor in the rulebook.
    missing = sorted(
        {
            m
            for m in re.findall(r'rulebook\.html#([A-Za-z]+-[0-9A-Za-z.]+)', body)
            if m not in anchors
        }
    )
    if missing:
        raise SystemExit(f"{slug}: cited rule IDs with no anchor in the rulebook: {missing}")
    return body


BACK_BAR = """<style>
.site-back{background:#0a1428;border-bottom:1px solid #1e3a52;position:relative;z-index:60}
.site-back div{max-width:70rem;margin:0 auto;padding:.7rem 1.5rem;display:flex;gap:1.2rem;
 align-items:center;flex-wrap:wrap}
.site-back a{font:600 .68rem/1 "Barlow Semi Condensed",Inter,system-ui,sans-serif;
 letter-spacing:.15em;text-transform:uppercase;color:#7a96a8;text-decoration:none;
 border-bottom:1px solid transparent;padding:.3rem 0}
.site-back a:hover{color:#e4f1f5;border-bottom-color:#c8aa6e}
.site-back a:focus-visible{outline:2px solid #c8aa6e;outline-offset:3px}
.site-back b{font:600 .68rem/1 "Barlow Semi Condensed",Inter,system-ui,sans-serif;
 letter-spacing:.15em;text-transform:uppercase;color:#c8aa6e}
@media print{.site-back{display:none}}
</style>
</head>"""

BACK_NAV = """<nav class="site-back" aria-label="Site">
<div>
  <a href="index.html">&larr; Riftbound Oracle</a>
  <b>Anchored rulebook</b>
  <a href="hot-fepr.html">HOT FEPR</a>
  <a href="combat.html">Combat</a>
  <a href="showdowns.html">Showdowns</a>
  <a href="samples.html">Sample reports</a>
</div>
</nav>
"""


def rulebook(src: str) -> str:
    """The generated rulebook, verbatim, plus a way back to the rest of the site.

    Nothing in the document itself is touched: the styles and the bar are
    inserted at the seams (before </head>, after the grain div) so every rule,
    every anchor and every cross-reference is the bytes render_rulebook.py
    emitted.
    """
    if "</head>" not in src:
        raise SystemExit("rulebook: no </head> to insert the site bar before")
    out = src.replace("</head>", BACK_BAR, 1)
    marker = '<div class="grain" aria-hidden="true"></div>\n'
    if marker not in out:
        raise SystemExit("rulebook: could not find the insertion point for the site bar")
    return out.replace(marker, marker + BACK_NAV, 1)


def check_page_declares_no_extra_transitions(slug: str, primer: dict, page: str) -> None:
    """Invariant 12, restated for the website.

    A diagram draws exactly the transitions the document declares — no more, no
    fewer — and that is the only reason a picture is publishable in this
    project at all. The website is where that guarantee is easiest to lose: a
    page is prose around an image, and prose is free to describe an arrow that
    is not there, or to omit one that is.

    So the numbers rendered on the page are compared against the numbers the
    primer declares. Not a spot check — the exact set, both directions.
    """
    declared = sum(len(step.get("exits") or []) for step in primer["steps"])
    expected = set(range(1, declared + 1))
    # `exit-n dashed` for a structural transition — matching the class
    # attribute exactly missed every one of them, and this check's first run
    # reported combat.html as missing transition 4 when the page was correct.
    # A verifier that cannot see a legitimate variant fails honest pages and
    # trains whoever hits it to stop believing the check.
    shown = {int(n) for n in re.findall(r'class="exit-n[^"]*"[^>]*>(\d+)<', page)}
    if shown != expected:
        raise SystemExit(
            f"{slug}.html shows transitions {sorted(shown)} but the primer "
            f"declares {sorted(expected)} — the page and the document it is "
            "derived from disagree, which is invariant 12"
        )


def check_handwritten_corpus_claims() -> None:
    """The hand-written pages state a rule count. Prove it is still true.

    `index.html` and `samples.html` are prose, so this build does not generate
    them — which makes them the one place on this site that can drift from the
    corpus with nothing noticing. A stale "3,316 rules" is a small lie of
    exactly the kind this project exists to refuse: a confident number, on the
    page selling verification, that nobody checked.

    Cheap to state and cheap to check, so it runs on every build. When a rules
    update moves the count this fails and names both numbers, instead of
    letting the page quietly describe last month's corpus.
    """
    raw = json.loads((SKILL / "data" / "rules.json").read_text(encoding="utf-8"))
    actual = len(raw if isinstance(raw, list) else raw.get("rules", raw))
    for page in ("index.html", "samples.html"):
        text = (SITE / page).read_text(encoding="utf-8")
        for claimed in re.findall(r"([0-9,]+) rules\b", text):
            if int(claimed.replace(",", "")) != actual:
                raise SystemExit(
                    f"{page} claims {claimed} rules; the corpus has {actual:,}. "
                    "A rules update moved it — update the page in the same commit."
                )
    print(f"checked hand-written pages against the corpus ({actual:,} rules)")


def main() -> None:
    (SITE / "diagrams").mkdir(exist_ok=True)
    (SITE / "img").mkdir(exist_ok=True)
    (SITE / "reports").mkdir(exist_ok=True)

    rules_src = (SKILL / "data" / "rules.html").read_text(encoding="utf-8")
    anchors = set(re.findall(r'id="([A-Za-z]+-[0-9A-Za-z.]+)"', rules_src))
    print(f"rulebook: {len(anchors)} anchors")

    (SITE / "rulebook.html").write_text(rulebook(rules_src), encoding="utf-8")
    print("wrote  rulebook.html")

    # The sample reports are shipped byte-for-byte as the skill wrote them, and
    # they resolve their rulebook overlay at `../data/rules.html`. So the corpus
    # goes there too, verbatim — rewriting a href inside a report would make the
    # "untouched output" claim on samples.html false, which is a worse trade
    # than one duplicated file.
    (SITE / "data").mkdir(exist_ok=True)
    (SITE / "data" / "rules.html").write_text(rules_src, encoding="utf-8")
    print("wrote  data/rules.html (verbatim, for the reports' overlay)")

    for slug, filename, _label, _title in TOPICS:
        primer = json.loads((SKILL / "lib" / filename).read_text(encoding="utf-8"))
        shutil.copyfile(
            SKILL / "data" / "diagrams" / f"{slug}.svg", SITE / "diagrams" / f"{slug}.svg"
        )
        page = explainer(slug, primer, anchors)
        check_page_declares_no_extra_transitions(slug, primer, page)
        (SITE / f"{slug}.html").write_text(page, encoding="utf-8")
        print(f"wrote  {slug}.html  ({len(primer['steps'])} steps, "
              f"{sum(len(s.get('exits') or []) for s in primer['steps'])} transitions)")

    # The samples are COMMITTED, and refreshed only when the source report is
    # present. `reports/` is a working directory the skill writes into and git
    # does not track, so a clean clone has no `reports/` at all — a build that
    # required one could not rebuild this site, which is the whole property
    # being claimed. So: refresh when the source is there, keep the committed
    # copy when it is not, and refuse when there is neither.
    for src, dst in REPORTS:
        source = SKILL / "reports" / src
        committed = SITE / "reports" / dst
        if source.exists():
            shutil.copyfile(source, committed)
            print(f"copied reports/{dst}  (refreshed from the skill)")
        elif committed.exists():
            print(f"kept   reports/{dst}  (committed sample; no local source)")
        else:
            raise SystemExit(
                f"reports/{dst} is missing and {source} does not exist — "
                f"generate the report, or restore the committed sample."
            )

    for src, dst in IMAGES:
        shutil.copyfile(src, SITE / "img" / dst)
        print(f"copied img/{dst}")

    check_handwritten_corpus_claims()
    print("\nindex.html and samples.html are written by hand — not touched.")


if __name__ == "__main__":
    sys.exit(main())

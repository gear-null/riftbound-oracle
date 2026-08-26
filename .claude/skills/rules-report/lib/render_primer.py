"""Render a verified primer.json into a self-contained interactive HTML page.

A primer is the second document kind this skill produces. A ruling defends one
contested proposition — "does X still happen if Y" — and its whole shape exists
to make that defensible: one holding line typed into spans, exactly one crux
saying what breaks if it is wrong, the opposing reading confronted by name.

A primer answers a different question: "how does this actually work". There is
no proposition to defend, so none of that machinery applies. Ask for the HOT
FEPR loop and the honest answer is five steps and nine transitions between them,
four of which send you backwards — a shape a single holding sentence cannot
hold, and a crux cannot rank.

What does NOT change is the standard of proof. Every quote goes through the same
verbatim gate, every rule id must exist at this corpus version, every abstention
must show what it searched, and confidence is still min() over the whole chain.
Prose is where a model's fluency does the most damage, so the primer is
deliberately the stricter document in one respect:

  **A transition is a claim.** `exits[]` is not decoration for the diagram — it
  is the assertion "the rules send you from here to there when this holds", and
  it must cite the rule that says so. The default basis is `grounded`, so an
  uncited edge fails verification rather than rendering as confident prose. That
  is the primer's equivalent of the ruling's typed holding spans: the part a
  reader most relies on is the part code refuses to take on trust.

The diagram is derived from those same verified transitions (see flowgraph.py),
so the picture cannot say something the citations do not.
"""
import json
import os
import re
import sys

import flowgraph
from render_report import (BASIS, FAVICON, LEGEND_MARKER, MARK, RAILSYM_MARKER,
                           RULEBOOK,
                           RANK, _CSS, _JS, _check, basis_key_html, cards_html,
                           check_card_sections, check_considered_rejected,
                           check_corpus_stamp, check_required_keys,
                           check_rules_checked, check_unique_ids, cite_html,
                           clip, esc, legend_html)
from verify_citations import RuleIndex

# An exit with no basis is asserting that a rule sends you there. Spelling the
# default out here rather than at each use site is what makes "uncited grounded
# edge" a single check instead of three that can disagree.
DEFAULT_EXIT_BASIS = "grounded"


def _cite_carriers(ans):
    """Everything in a primer that carries citations, in document order."""
    for step in ans.get("steps", []):
        yield step
        for ex in step.get("exits", []) or []:
            yield ex
    for m in ans.get("misconceptions", []) or []:
        yield m


def all_cites(ans):
    """Every citation the verifier checked — steps', transitions' and misconceptions'.

    One definition, for the same reason `render_report.all_cites` is one: the
    console summary and the page headline counting different things is how the
    ruling path once reported "9/9 verified" in the terminal and "12/12" in the
    report it had just written.
    """
    return [c for src in _cite_carriers(ans) for c in src.get("cites", []) or []]


def verify_primer(ans, idx):
    """Verify every citation, grade every step and transition, refuse on anything false.

    Returns the answer annotated with `_problems`, `_weakest`, `_strength` and
    `_unverified`. A non-empty `_problems` means the document does not render:
    unlike a ruling there is no disposition to downgrade to UNSETTLED, so the
    only honest response to a broken citation is to not publish the page.
    """
    problems = []
    steps = ans.get("steps")
    if not isinstance(steps, list) or not steps:
        problems.append("a primer needs at least one step in `steps`")
        steps = ans["steps"] = []

    # Untrusted model JSON, and the shape is assumed everywhere below. A list of
    # bare strings raised AttributeError on the ruling path once and the crash
    # hid every problem found after it — including a hallucinated quote. The
    # malformed entries are DROPPED after being reported, so verification
    # continues and the author sees the whole list rather than the first item.
    kept = []
    for i, item in enumerate(steps, 1):
        if not isinstance(item, dict):
            problems.append(f"step {i}: expected an object with `id`, `heading` "
                            f"and `body`, got {type(item).__name__}")
            continue
        # `id` is the addressing scheme — the page anchor, the goto target, the
        # key every later pass subscripts. A step without one crashed
        # verification outright, so the author got a traceback instead of the
        # problem list, and a crash means no report at all. Reported and given a
        # placeholder, so the rest of the document is still checked and --force
        # still produces a page saying what is wrong with it.
        if not str(item.get("id") or "").strip():
            problems.append(f"step {i}: no `id` — it is the page anchor and the "
                            "name every transition points at")
            item["id"] = f"_unnamed{i}"
        exits = item.get("exits")
        if exits is not None and (not isinstance(exits, list)
                                  or any(not isinstance(x, dict) for x in exits)):
            problems.append(f'{item["id"]}: `exits` must be a list '
                            "of objects, each with `when` and a `goto`")
            item["exits"] = []
        kept.append(item)
    steps = ans["steps"] = kept

    # Coerced BEFORE anything reads it, the same way note bases are: a step
    # missing the key would otherwise raise KeyError mid-verification, and a
    # crash means no report at all.
    for s in steps:
        if s.get("basis") not in RANK:
            problems.append(f'{s.get("id", "?")}: unknown basis {s.get("basis")!r}')
            s["basis"] = "gap"
        for ex in s.get("exits", []) or []:
            if ex.get("basis") is None:
                ex["basis"] = DEFAULT_EXIT_BASIS
            elif ex["basis"] not in RANK:
                problems.append(
                    f'{s.get("id", "?")} transition to {ex.get("goto") or "the end"}: '
                    f'unknown basis {ex.get("basis")!r}')
                ex["basis"] = "gap"

    check_unique_ids(steps, "step", problems)
    known = {s.get("id") for s in steps}

    for s in steps:
        sid = s.get("id", "?")
        if not s.get("heading"):
            problems.append(f"{sid}: no heading")
        if not s.get("body"):
            problems.append(f"{sid}: no body — a step with a heading and nothing "
                            "under it explains nothing")
        step_ok = all(_check(c, idx, sid, problems) for c in (s.get("cites") or []))
        # Scoped to `grounded` for the same reason it is on a ruling's notes:
        # `structural` legitimately rests on the rules its neighbours cite, and
        # `gap` pays for its abstention with rules_checked below. Grounded is
        # the claim that a rule says it, so it must show the rule.
        if s["basis"] == "grounded" and not s.get("cites"):
            problems.append(f"{sid}: basis 'grounded' asserts a rule states this, "
                            "but cites none")
            step_ok = False
        if s["basis"] == "gap" and not s.get("rules_checked"):
            problems.append(f"{sid}: gap step must list rules_checked")
        s["verified"] = step_ok

        for i, ex in enumerate(s.get("exits", []) or [], 1):
            where = f"{sid} transition {i}"
            if not ex.get("when"):
                problems.append(f"{where}: no `when` — a transition with no "
                                "condition is an arrow a reader cannot follow")
            goto = ex.get("goto")
            if goto is not None and goto not in known:
                problems.append(
                    f"{where}: goto names {goto!r}, which is not a step in this "
                    "primer — the diagram is drawn from these, so it would point "
                    "at nothing")
            ex_ok = all(_check(c, idx, where, problems) for c in (ex.get("cites") or []))
            # The strict default, and the whole reason this document kind is
            # safe to write as prose. An edge is the load-bearing part of a
            # procedure — it is what a reader will act on at the table — so it
            # may not be asserted more cheaply than a sentence in a ruling.
            if ex["basis"] == "grounded" and not ex.get("cites"):
                problems.append(
                    f"{where}: a transition asserting the rules send you to "
                    f'{goto or "the end"} must cite the rule that says so — or '
                    "declare basis 'structural' and say what it follows from")
                ex_ok = False
            if ex["basis"] == "gap" and not ex.get("rules_checked"):
                problems.append(f"{where}: gap transition must list rules_checked")
            ex["verified"] = ex_ok

    check_rules_checked(steps, idx, problems)
    for s in steps:
        check_rules_checked(s.get("exits", []) or [], idx, problems)

    for i, m in enumerate(ans.get("misconceptions", []) or [], 1):
        if not isinstance(m, dict):
            problems.append(f"misconception {i}: expected an object with `belief` "
                            f"and `why_wrong`, got {type(m).__name__}")
            continue
        for key in ("belief", "why_wrong"):
            if not m.get(key):
                problems.append(f"misconception {i}: no {key}")
        # Held to the same standard as a ruling's counterargument: this is the
        # text a reader who believes the wrong thing will go check first.
        m["verified"] = all(_check(c, idx, f"misconception {i}", problems)
                            for c in (m.get("cites") or []))

    check_corpus_stamp(ans, idx, problems)
    check_considered_rejected(ans, idx, problems)
    check_card_sections(ans, idx, problems)
    check_required_keys(ans, ("question", "topic", "in_one_line", "corpus"), problems)

    problems += _check_shape(steps)

    # min() over steps AND transitions. A primer whose steps are all grounded
    # but whose transitions are guesses is a guess about the procedure, which is
    # the only thing anyone reads a procedure primer for.
    graded = [(s["id"], s["basis"]) for s in steps]
    graded += [(s["id"], ex["basis"]) for s in steps for ex in (s.get("exits") or [])]
    if graded:
        wid, wbasis = min(graded, key=lambda g: RANK[g[1]])
        ans["_weakest"], ans["_strength"] = wid, wbasis
    else:
        ans["_weakest"], ans["_strength"] = "-", "gap"

    # ANY problem, not only a failed quote. `--force` exists to inspect a broken
    # primer, and the banner is the only thing stopping the resulting page from
    # being mistaken for a verified one — so scoping it to citations meant an
    # uncited grounded step, a bad goto or a missing heading produced a forced
    # page with no banner at all.
    ans["_unverified"] = bool(problems)
    ans["_problems"] = problems
    return ans


def _check_shape(steps):
    """Shape checks that only mean anything once the primer is a procedure.

    A primer with no transitions anywhere is a linear explainer — "the parts of
    a card", "what the zones are" — and none of this applies to it. As soon as
    one step declares an exit the document is claiming to describe a procedure,
    and a procedure with an orphaned step or no way out is a wrong description,
    not a stylistic choice. Both would be visible on the diagram as a box
    nothing reaches, or a loop with no arrow leaving it.
    """
    problems = []
    if not any(s.get("exits") for s in steps):
        return problems

    reached = {g for s in steps for ex in (s.get("exits") or [])
               if (g := ex.get("goto")) is not None}
    for s in steps[1:]:
        if s.get("id") not in reached:
            problems.append(
                f'{s.get("id", "?")}: no transition names this step, so nothing '
                "reaches it — either a transition is missing or a goto is wrong")

    if not any(ex.get("goto") is None
               for s in steps for ex in (s.get("exits") or [])):
        problems.append(
            "this procedure has no way out — one transition must omit `goto` to "
            "say where the procedure ends")
    return problems


# ── the page ────────────────────────────────────────────────────────────

# Only what the ruling sheet does not already carry. Everything structural — the
# plates, the chamfers, the citation blocks, the rail, the whole print
# inversion — is shared, because a reader who has read one of these documents
# should not have to learn the other.
_PRIMER_CSS = """
/* ── the summary plate ──────────────────────────────────────────────── */
.summary{--ch:14px;margin:1.9rem 0 0;padding:1.5rem 1.6rem 1.35rem;
 background:linear-gradient(148deg,var(--gold-500) 0%,var(--gold-700) 42%,var(--gold-700) 100%)}
.topic{font:700 clamp(1.3rem,3.6vw,1.85rem)/1.1 var(--display);letter-spacing:.09em;
 text-transform:uppercase;color:var(--fg)}
.lede{margin:1rem 0 0;font-size:clamp(1.14rem,2.4vw,1.36rem);line-height:1.5;
 max-width:66ch;text-wrap:pretty}

/* ── the map ────────────────────────────────────────────────────────── */
/* The diagram is wider than the column on a narrow screen. It scrolls in its
   own well rather than widening the page, because a body that scrolls
   sideways loses the prose too. */
.map{--ch:10px;padding:1.15rem 1.2rem;overflow-x:auto}
.flowgraph{display:block;max-width:100%;height:auto;min-width:22rem}
.fg-step{font:500 .82rem/1 var(--body);fill:var(--fg)}
.fg-idx{font:600 .8rem/1 var(--plate);font-variant-numeric:tabular-nums}
.fg-num{font:600 .68rem/1 var(--plate);font-variant-numeric:tabular-nums}
.fg-out{font:600 .64rem/1 var(--plate);letter-spacing:.11em;text-transform:uppercase}
.map-note{margin:.85rem 0 0;font-size:.85rem;line-height:1.55;color:var(--muted);max-width:68ch}

/* ── steps ──────────────────────────────────────────────────────────── */
/* Deliberately the note plate's geometry. A step and a claim are different
   things, but they are read the same way — number, heading, basis, evidence —
   and giving them two visual languages would only make the pair harder. */
.step{--ch:9px;display:grid;grid-template-columns:2.9rem minmax(0,1fr);margin:.85rem 0;
 scroll-margin-top:1.5rem}
.step:target{background:linear-gradient(148deg,var(--gold-500) 0%,var(--gold-700) 45%,var(--gold-700) 100%)}
.step-n{display:flex;justify-content:center;padding:1.05rem .4rem;
 border-right:1px solid var(--rule);font:600 .95rem/1 var(--plate);
 font-variant-numeric:tabular-nums;color:var(--slate-300)}
.b-grounded .step-n{color:var(--gold-500)}
.b-structural .step-n,.b-inferred .step-n{color:var(--blue)}
.b-gap .step-n{color:var(--slate-300)}
.step-body{padding:1rem 1.15rem 1.1rem;min-width:0}
.step-head{display:flex;gap:.8rem;align-items:flex-start;flex-wrap:wrap}
.step-head h3{flex:1 1 15rem;margin:0;font:600 1.02rem/1.45 var(--body);max-width:68ch}
.step-text{margin:.8rem 0 0;font-size:.97rem;max-width:68ch;color:var(--fg)}

/* ── transitions ────────────────────────────────────────────────────── */
/* The numbered edge on the map, written out. The number is the join between
   the two, so it is the one element that never wraps or clips. */
.exits{margin:1rem 0 0;padding-top:.85rem;border-top:1px solid var(--rule)}
.exits > .label{margin-bottom:.6rem}
.exit{display:grid;grid-template-columns:1.7rem minmax(0,1fr);gap:.1rem .6rem;
 padding:.55rem 0;border-bottom:1px solid var(--rule)}
.exit:last-child{border-bottom:0;padding-bottom:0}
.exit-n{grid-row:span 2;align-self:start;justify-self:center;margin-top:.1rem;
 min-width:1.35rem;padding:.2em 0;text-align:center;border:1px solid var(--rule);
 font:600 .68rem/1.4 var(--plate);font-variant-numeric:tabular-nums;color:var(--muted)}
.e-grounded .exit-n{color:var(--gold-500);border-color:var(--line)}
.e-structural .exit-n,.e-inferred .exit-n{color:var(--blue);
 border-color:color-mix(in oklch,var(--blue) 42%,transparent)}
.exit-when{font-size:.93rem;line-height:1.55;max-width:64ch}
.exit-goto{display:block;margin-top:.2rem;font:600 .66rem/1.5 var(--plate);
 letter-spacing:.1em;text-transform:uppercase;color:var(--slate-300)}
.exit-goto a{color:var(--blue);text-decoration:none;border-bottom:1px dotted var(--blue)}
.exit-goto a:hover{color:var(--fg);border-bottom-color:var(--fg)}
.exit .cites{grid-column:2;margin-top:.5rem}

/* ── misconceptions ─────────────────────────────────────────────────── */
.misc{--ch:9px;margin:.85rem 0;padding:1.1rem 1.2rem;background:var(--rule)}
.misc::after{background:var(--well)}
.misc h3{margin:.45rem 0 1rem;font:500 1.05rem/1.55 var(--body);color:var(--fg);max-width:68ch}
.misc .why{margin:.45rem 0 0;font-size:.95rem;color:var(--muted);max-width:68ch}
.misc .cites{margin-top:1rem}

@media(max-width:720px){
 .step{grid-template-columns:minmax(0,1fr)}
 .step-n{justify-content:flex-start;padding:.65rem .9rem;border-right:0;
  border-bottom:1px solid var(--rule)}
}
@media print{
 .summary,.step:target{background:transparent}
 .topic{color:var(--fg)}
 .map{overflow-x:visible}
 .flowgraph{min-width:0}
 .fg-step{fill:var(--fg)}
 .step,.misc,.map{break-inside:avoid}
}
"""


def _exit_html(ex, steps_by_id, idx, corpus, n):
    """One numbered transition: the condition, where it sends you, its evidence.

    A step's number is its POSITION, never digits scraped out of its id. Those
    agree for `s1`..`s5` and part company the moment an author writes `s0` or
    `handle` — and then the plate at the top of a step says 1 while every
    transition pointing at it says 0, or "step handle". Position is also what
    the diagram numbers its boxes by, so this is the same number in all three
    places by construction.
    """
    goto = ex.get("goto")
    if goto is None:
        dest = "the procedure ends"
    else:
        number, heading = steps_by_id.get(goto, ("?", goto))
        dest = (f'<a href="#{esc(goto)}">step {esc(number)} · '
                f'{esc(clip(heading, 42))}</a>')
    cites = "".join(cite_html(c, idx, corpus) for c in ex.get("cites") or [])
    return (
        f'<div class="exit e-{esc(ex["basis"])}">'
        f'<span class="exit-n">{n}</span>'
        f'<div><span class="exit-when">{esc(ex.get("when", ""))}</span>'
        f'<span class="exit-goto">&rarr; {dest}</span></div>'
        + (f'<div class="cites">{cites}</div>' if cites else "")
        + "</div>")


def render(ans, idx):
    corpus = ans["corpus"]
    steps = ans["steps"]
    steps_by_id = {s["id"]: (i + 1, s.get("heading", s["id"]))
                   for i, s in enumerate(steps)}
    weakest_n = steps_by_id.get(ans["_weakest"], ("?", ""))[0]

    # Transition numbering comes from flowgraph, not from a second count here.
    # The map and the prose disagreeing about which edge is number 4 would make
    # both useless, and two independent counters is how that happens.
    _nodes, edges = flowgraph.build(steps)
    edge_n = {}
    for e in edges:
        edge_n.setdefault(e["from"], []).append(e["n"])

    blocks = []
    for i, s in enumerate(steps):
        glyph, why = BASIS[s["basis"]]
        checked = (f'<div class="checked"><b>Rules searched</b>'
                   f'{esc(" · ".join(s["rules_checked"]))}</div>'
                   if s.get("rules_checked") else "")
        cites = "".join(cite_html(c, idx, corpus) for c in s.get("cites") or [])
        numbers = edge_n.get(i, [])
        exits = "".join(
            _exit_html(ex, steps_by_id, idx, corpus,
                       numbers[j] if j < len(numbers) else "")
            for j, ex in enumerate(s.get("exits") or []))
        blocks.append(f'''<section class="step plate b-{esc(s["basis"])}"
    id="{esc(s["id"])}" data-od-id="step-{esc(s["id"])}">
  <div class="step-n" aria-hidden="true">{i + 1}</div>
  <div class="step-body">
    <div class="step-head">
      <h3>{esc(s["heading"])}</h3>
      <span class="note-tags"><span class="basis-chip" title="{esc(why)}">{glyph} {esc(s["basis"])}</span></span>
    </div>
    <p class="step-text">{esc(s["body"])}</p>
    {checked}
    {f'<div class="cites">{cites}</div>' if cites else ""}
    {f'<div class="exits"><span class="label">Where you go next</span>{exits}</div>' if exits else ""}
  </div>
</section>''')

    misc = "".join(f'''<section class="misc plate" data-od-id="misconception-{i}">
  <span class="label">Commonly believed</span>
  <h3>“{esc(m["belief"])}”</h3>
  <span class="label">What the rules actually say</span>
  <p class="why">{esc(m["why_wrong"])}</p>
  {f'<div class="cites">{"".join(cite_html(x, idx, corpus) for x in m.get("cites") or [])}</div>'
   if m.get("cites") else ""}
</section>''' for i, m in enumerate(ans.get("misconceptions") or [], 1))

    rejected = "".join(f'<li><code>{esc(r["rule"])}</code> — {esc(r["why"])}</li>'
                       for r in ans.get("considered_rejected") or [])
    openq = "".join(f"<li>{esc(q)}</li>" for q in ans.get("open_questions") or [])
    problems = "".join(f"<li>{esc(p)}</li>" for p in ans.get("_problems") or [])

    reframe = re.sub(r"^\s*as the rules see it\s*:\s*", "",
                     ans.get("reframe", ""), flags=re.I)

    _cites = all_cites(ans)
    ncites, nverified = len(_cites), sum(1 for c in _cites if c["verified"])
    ngrounded = sum(1 for s in steps if s["basis"] == "grounded")
    # One flex item, not two. `.metric` sets a gap, so a bare text node after
    # the <b> put half a rem in front of the comma — "5 , 5 stated outright".
    steps_metric = (f"<b>{len(steps)}</b>, all stated outright in the rules"
                    if ngrounded == len(steps) and steps else
                    f"<b>{len(steps)}</b>, {ngrounded} stated outright in the rules")

    diagram = flowgraph.svg(steps, ans.get("topic") or "Procedure")
    map_block = (
        '<h2 id="map" data-od-id="sec-map">The shape of it</h2>'
        f'<div class="map plate" data-od-id="flowgraph">{diagram}</div>'
        '<p class="map-note">Drawn from the transitions below — every arrow is one '
        'of them, numbered to match. A solid arrow is a move a rule states '
        'outright; a dashed one follows from the rules cited rather than being '
        'written in one place.</p>') if diagram else ""

    cards_block = cards_html(ans)
    key = basis_key_html(steps + [ex for s in steps for ex in (s.get("exits") or [])])
    rail = _rail_html(ans, steps, weakest_n, [
        (href, label) for href, label, present in (
            ("#map", "The shape of it", map_block),
            ("#cards", "Cards referenced", cards_block),
            ("#misconceptions", "Commonly got wrong", misc),
            ("#rejected", "Considered and rejected", rejected),
            ("#unsettled", "The rules do not settle", openq),
            ("#problems", "Verification problems", problems),
        ) if present])

    unverified = (
        '<div class="forced">Failed verification — written with --force and must '
        'not be relied on. What went wrong is listed under Verification '
        'problems</div>' if ans.get("_unverified") else "")

    page = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark">
<title>Primer — {esc(str(ans.get("topic", ""))[:60])}</title>
<link rel="icon" href="{FAVICON}">
<style>{_CSS}{_PRIMER_CSS}</style></head>
<body>
<div class="grain" aria-hidden="true"></div>
<a class="skip" href="#summary">Skip to the summary</a>

<header class="masthead" data-od-id="masthead">
  <div class="wrap masthead-in">
    {MARK}
    <span class="wordmark"><span class="eyebrow">Riftbound</span><b>Oracle</b></span>
    <span class="unofficial">Unofficial rules companion</span>
    <span class="corpus">CR <b>{esc(corpus["CR"])}</b> &middot; TR <b>{esc(corpus["TR"])}</b><br>
      corpus built {esc(corpus["generated"])} &middot; offline</span>
  </div>
</header>

<div class="wrap layout">
<main data-od-id="report">

<section class="ask" data-od-id="question">
  <span class="label">The question</span>
  <h1>{esc(ans.get("question", ""))}</h1>
  {f'<p class="reframe"><span class="label">As the rules see it</span>{esc(reframe)}</p>'
   if reframe else ""}
</section>

<section class="summary plate" id="summary" data-od-id="summary">
  <div class="verdict-head">
    <span class="topic">{esc(ans.get("topic", ""))}</span>
    <span class="hairline" aria-hidden="true"></span>
    <span class="tally"><b>{nverified}/{ncites}</b> citations verified verbatim</span>
  </div>
  <p class="lede">{esc(ans.get("in_one_line", ""))}</p>
  <div class="strength">
    <span class="metric"><span class="label">Steps</span>
      <span>{steps_metric}</span></span>
    <span class="metric"><span class="label">Weakest step</span>
      <a class="weakref" href="#{esc(ans["_weakest"])}">step
      {esc(weakest_n)}</a> <b>{esc(ans["_strength"])}</b></span>
    <span class="metric"><span class="label">Confidence</span>the lowest link, never an average</span>
    {unverified}
  </div>
</section>

{key}

{map_block}

{cards_block}

<h2 id="walkthrough" data-od-id="sec-walkthrough">Step by step</h2>
{"".join(blocks)}

{f'<h2 id="misconceptions" data-od-id="sec-misconceptions">Commonly got wrong</h2>{misc}' if misc else ""}
{f'<h2 id="rejected" data-od-id="sec-rejected">Considered and rejected</h2><ul class="plain">{rejected}</ul>' if rejected else ""}
{f'<h2 id="unsettled" data-od-id="sec-unsettled">The rules do not settle</h2><ul class="plain">{openq}</ul>' if openq else ""}
{f'<h2 id="problems" data-od-id="sec-problems">Verification problems</h2><ul class="plain">{problems}</ul>' if problems else ""}
<!--LEGEND-->

<footer class="foot" data-od-id="footer">
  Riftbound Oracle is an unofficial fan project, not endorsed by, affiliated with or
  sponsored by Riot Games. Rule text is quoted from Riot&rsquo;s Comprehensive Rules and
  Tournament Rules; card artwork is loaded from Riot&rsquo;s CDN and is not redistributed
  here.
</footer>

</main>
{rail}
</div>

<div id="rb-overlay" class="rb-overlay" hidden>
  <div class="rb-panel plate" role="dialog" aria-modal="true" aria-label="Rulebook">
    <div class="rb-bar">
      <span class="rb-title" id="rb-title">Rulebook</span>
      <a class="rb-pop" id="rb-pop" href="{RULEBOOK}" target="_blank" rel="noopener">Open full page &#8599;</a>
      <button class="rb-close" id="rb-close" aria-label="Close">&times;</button>
    </div>
    <iframe class="rb-frame" id="rb-frame" title="Rulebook"></iframe>
  </div>
</div>

<script>{_JS}</script></body></html>'''

    legend = legend_html(page, idx)
    railsym = ('<a class="rail-jump" href="#symbols">Symbols used here</a>'
               if legend else "")
    return page.replace(LEGEND_MARKER, legend).replace(RAILSYM_MARKER, railsym)


def _rail_html(ans, steps, weakest_n, jumps):
    """The sticky index. Same furniture as a ruling's, indexing steps not claims."""
    rows = "".join(
        f'<a class="rail-note" href="#{esc(s["id"])}" title="{esc(s["heading"])}">'
        f'<span class="n">{i + 1}</span>'
        f'<span class="t">{esc(clip(s["heading"]))}</span></a>'
        for i, s in enumerate(steps))
    jump_html = "".join(f'<a class="rail-jump" href="{href}">{esc(label)}</a>'
                        for href, label in jumps)
    return f'''<aside class="rail" data-od-id="rail" aria-label="Primer contents">
  <div class="rail-plate plate">
    <h4>The primer</h4>
    <span class="rail-disp is-lead">{esc(clip(ans.get("topic", ""), 64))}</span>
    <p class="rail-meta">Weakest step <a class="weakref" href="#{esc(ans["_weakest"])}">step
      {esc(weakest_n)}</a> · {esc(ans["_strength"])}</p>
  </div>
  <nav class="rail-nav">
    <h4>The steps</h4>
    {rows}
  </nav>
  <nav class="rail-nav">{jump_html}{RAILSYM_MARKER}</nav>
</aside>'''


def main():
    pos = [a for a in sys.argv[1:] if not a.startswith("--")]
    src = pos[0] if pos else "primer.json"
    out = pos[1] if len(pos) > 1 else "primer.html"
    ans = verify_primer(json.load(open(src, encoding="utf-8")), RuleIndex())
    # The gate lives here as well as in `rules_cli.py report`, for the same
    # reason it does on the ruling path: a sibling caller that skipped it
    # produced an artifact indistinguishable from a verified one.
    if ans["_problems"] and "--force" not in sys.argv:
        print("VERIFICATION FAILED — refusing to render:", file=sys.stderr)
        for pb in ans["_problems"]:
            print(f"  ! {pb}", file=sys.stderr)
        sys.exit(1)
    # Render first, then write: `open(out,"w")` truncates on open, so a crash
    # inside render() would otherwise destroy the previous good page at that path.
    html_out = render(ans, RuleIndex())
    tmp = out + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(html_out)
        os.replace(tmp, out)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    _cites = all_cites(ans)
    print(f"wrote {out}")
    print(f"  topic       : {ans.get('topic', '')}")
    print(f"  steps       : {len(ans['steps'])}")
    print(f"  citations   : {sum(1 for c in _cites if c['verified'])}/{len(_cites)} verified")
    print(f"  weakest step: {ans['_weakest']} ({ans['_strength']})")
    for p in ans["_problems"]:
        print(f"  ! {p}")


if __name__ == "__main__":
    main()

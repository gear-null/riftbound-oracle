"""Render a verified answer.json into a self-contained interactive HTML report.

Design: "Marginalia" — the report IS the rulebook page. Official rule text is the
primary content in document order; the model is demoted to margin notes tethered
to the exact spans it relies on. Verification is not a step the reader performs,
it is the layout.

Grafted in after judging:
  - typed holding line   : the one-line answer decomposes into grounded/inferred
                           spans, each an exact substring, each linking to its note
  - crux + if_false      : exactly one note is load-bearing and says what happens
                           if it is wrong, collapsing the audit from N notes to 1
  - weakest link         : confidence is min() over notes, not an average — a chain
                           is as strong as its weakest step
  - counterargument      : the opposing reading stated at full strength, by rule,
                           then rejected. A reader who has read the contrary rule
                           will not believe the holding until it is confronted.
  - verdict downgrade    : if any note the holding depends on fails verification,
                           the disposition is forced to UNSETTLED. The model must
                           not be able to outrun its own verifier.

file:// constraints respected: no network, no clipboard API (execCommand fallback),
localStorage guarded, print handler opens <details>, dark mode via prefers-color-scheme.
"""
import html, json, sys
from verify_citations import RuleIndex, verify_citation

BASIS = {
    "grounded":   ("●", "A rule states this in so many words"),
    "structural": ("▲", "No single rule says this; it follows from the rules below"),
    "gap":        ("○", "The rules are silent on this"),
    # Holding spans say "inferred" where notes say "structural" — accept both.
    "inferred":   ("▲", "No single rule says this; it follows from the rules below"),
}
RANK = {"grounded": 3, "structural": 2, "inferred": 2, "gap": 1}


def esc(s):
    return html.escape(s or "", quote=True)


def _check(c, idx, where, problems):
    rid = c["rule"].split(":", 1)[-1]
    doc = c["rule"].split(":", 1)[0] if ":" in c["rule"] else None
    res = verify_citation(idx, rid, c.get("quote"), doc=doc)
    # `checked`, not `ok`: a cite with no quote passes `ok` vacuously.
    c["verified"] = res.checked
    if res.ok and not res.checked:
        problems.append(f"{where}: citation {rid} has no quote — the verbatim check never ran")
    c["cite_as"] = f'{doc or "CR"}:{res.cite_as}'
    c["narrowed"] = res.narrowed_to
    c["problems"] = res.problems
    if not res.ok:
        problems.append(f'{where}: {"; ".join(res.problems)}')
    return res.ok


def _check_holding(ans, idx):
    """Enforce the holding line's invariants.

    Evaluation showed error concentrating here: answers with a correct body and
    a loose one-line summary. The holding line is the part most people read, so
    it gets checked hardest. Previously a span that wasn't a substring was
    silently skipped at render time — a wrong claim rendered as plain prose.
    """
    problems = []
    h = ans.get("holding", {})
    line = h.get("line", "")
    spans = h.get("spans", [])
    by_id = {n["id"]: n for n in ans["notes"]}

    if not line:
        return ["holding.line is empty"]
    if not spans:
        return ["holding.line has no typed spans — the summary is unaccountable prose"]

    covered = 0
    for sp in spans:
        text = sp.get("text", "")
        if text not in line:
            problems.append(f'holding span "{text[:40]}" is not a substring of holding.line')
            continue
        covered += len(text)

        note = by_id.get(sp.get("note"))
        if not note:
            problems.append(f'holding span "{text[:30]}" points at unknown note {sp.get("note")}')
            continue
        # A span may not claim more support than the note it rests on.
        if sp.get("basis") == "grounded":
            if note["basis"] != "grounded":
                problems.append(
                    f'holding span "{text[:30]}" claims grounded but {note["id"]} is {note["basis"]}')
            elif not note.get("verified", True):
                problems.append(
                    f'holding span "{text[:30]}" claims grounded but {note["id"]} has a failed citation')

    # Substantive uncovered text is where loose summaries hide.
    words = len([w for w in line.split() if len(w) > 3])
    if words and covered / max(len(line), 1) < 0.30:
        problems.append(
            f"holding.line is only {covered * 100 // max(len(line), 1)}% covered by typed spans — "
            "decompose the claim rather than asserting it as prose")
    return problems


def verify_answer(ans, idx):
    """Verify EVERY citation in the document, narrow vague ones, grade each note.

    Counterargument citations get the same treatment as supporting ones — an
    unverified contrary rule is at least as dangerous, since it is the text a
    skeptical reader will go check first.
    """
    problems = []
    for note in ans["notes"]:
        note_ok = True
        for c in note.get("cites", []):
            if not _check(c, idx, note["id"], problems):
                note_ok = False
        note["verified"] = note_ok
        # Abstention is held to the same standard as assertion: a note claiming
        # the rules are silent must show what it searched.
        if note["basis"] == "gap" and not note.get("rules_checked"):
            problems.append(f'{note["id"]}: gap note must list rules_checked')
        if note.get("crux") and not note.get("if_false"):
            problems.append(f'{note["id"]}: crux note must state if_false')

    # A fabricated counterargument citation is at least as dangerous as a
    # fabricated supporting one — it is the text a sceptical reader checks
    # first. Previously its result was computed and then discarded.
    ca_failed = False
    for i, ca in enumerate(ans.get("counterargument", []), 1):
        for c in ca.get("cites", []):
            if not _check(c, idx, f"counterargument {i}", problems):
                ca_failed = True

    cruxes = [n["id"] for n in ans["notes"] if n.get("crux")]
    if len(cruxes) != 1:
        problems.append(f"exactly one note must be crux, found {len(cruxes)}: {cruxes or 'none'}")

    problems += _check_holding(ans, idx)

    notes = ans["notes"]
    # The answer is model-generated JSON, i.e. untrusted input. An unknown
    # basis used to raise KeyError here; a crash means no report, and anyone
    # who later wraps this in try/except turns the verifier into a no-op.
    for n in notes:
        if n.get("basis") not in RANK:
            problems.append(f'{n.get("id", "?")}: unknown basis {n.get("basis")!r}')
            n["basis"] = "gap"
    if not notes:
        problems.append("answer has no notes")
        ans["_weakest"], ans["_strength"] = "-", "gap"
        ans["_problems"] = problems
        ans["holding"]["_forced"] = ans["holding"].get("disposition")
        ans["holding"]["disposition"] = "UNSETTLED"
        return ans
    graded = [n for n in notes if n["basis"] != "gap"] or notes
    weakest = min(graded, key=lambda n: RANK[n["basis"]])
    ans["_weakest"] = weakest["id"]
    ans["_strength"] = weakest["basis"]

    # The model must not outrun its verifier.
    load_bearing_failed = any(not n["verified"] for n in notes) or ca_failed
    if load_bearing_failed and ans["holding"]["disposition"] != "UNSETTLED":
        ans["holding"]["_forced"] = ans["holding"]["disposition"]
        ans["holding"]["disposition"] = "UNSETTLED"
    ans["_problems"] = problems
    return ans


def holding_html(h, notes_by_id):
    """Type the holding line: every span must be an exact substring of the line."""
    line, spans = h["line"], h.get("spans", [])
    out, cur = [], 0
    for sp in spans:
        i = line.find(sp["text"], cur)
        if i < 0:
            continue  # invariant violated; fall through to plain text
        out.append(esc(line[cur:i]))
        cls = "sp-grounded" if sp["basis"] == "grounded" else "sp-inferred"
        glyph = "" if sp["basis"] == "grounded" else "<sup>⌁</sup>"
        out.append(
            f'<a class="{cls}" href="#{esc(sp["note"])}" '
            f'title="{esc(BASIS[sp["basis"]][1])}">{esc(sp["text"])}{glyph}</a>'
        )
        cur = i + len(sp["text"])
    out.append(esc(line[cur:]))
    return "".join(out)


def cite_html(c, idx):
    rid = c["cite_as"].split(":", 1)[-1]
    doc = c["cite_as"].split(":", 1)[0]
    chain = idx.ancestry(rid, doc)
    rows = "".join(
        f'<li class="{"anc-target" if r["id"] == rid else ""}" style="--d:{r["depth"]}">'
        f'<code>{esc(r["id"])}</code> <span>{esc(r["text"])}</span></li>'
        for r in chain
    )
    stamp = ("verified" if c["verified"] else "UNVERIFIED")
    scls = "ok" if c["verified"] else "bad"
    narrow = (f'<div class="narrowed">narrowed from {esc(c["narrowed"])} — '
              f'now cites the tightest rule that says it</div>' if c.get("narrowed") else "")
    probs = "".join(f'<div class="prob">{esc(p)}</div>' for p in c.get("problems", [])
                    if not p.startswith("cite narrowed"))
    full = f'{doc} {rid} ({"Core Rules" if doc == "CR" else "Tournament Rules"}, 2026-07-16): "{c.get("quote","")}"'
    return f'''<details class="cite">
<summary><code>{esc(doc)} {esc(rid)}</code> <span class="stamp {scls}">{stamp}</span></summary>
<div class="cite-body">
{narrow}{probs}
<ol class="ancestry">{rows}</ol>
<button class="copy" data-cite="{esc(full)}">copy cite</button>
</div></details>'''


def cards_html(ans):
    """Card artwork alongside printed text.

    Images come from output/card-index.json (`npm run oracle card-index`). That
    index is optional and network-dependent, so a missing image degrades to a
    labelled placeholder rather than a broken <img>. Remote URLs are fine here —
    these reports are local files, not sandboxed artifacts.
    """
    cards = ans.get("cards") or []
    if not cards:
        return ""
    out = []
    for c in cards:
        img = c.get("image")
        if img:
            art = (
                f'<img class="card-art" src="{esc(img)}" alt="{esc(c["name"])} card artwork"'
                ' loading="lazy" referrerpolicy="no-referrer">'
            )
        else:
            art = (
                '<div class="card-art card-art--none">no artwork'
                '<span>run <code>oracle card-index</code></span></div>'
            )
        out.append(
            '<figure class="card">' + art + '<figcaption><b>'
            + esc(c["name"]) + '</b><span class="card-text">'
            + esc(c.get("text", "")) + '</span></figcaption></figure>'
        )
    return '<h2>Cards referenced</h2><div class="cards">' + "".join(out) + "</div>"


def render(ans, idx):
    notes_by_id = {n["id"]: n for n in ans["notes"]}
    h = ans["holding"]
    disp = h["disposition"]
    forced = h.get("_forced")

    note_blocks = []
    for n in ans["notes"]:
        glyph, why = BASIS[n["basis"]]
        crux = '<span class="crux">CRUX</span>' if n.get("crux") else ""
        iff = (f'<div class="iffalse"><b>If this is wrong:</b> {esc(n["if_false"])}</div>'
               if n.get("if_false") else "")
        checked = (f'<div class="checked">searched: {esc(", ".join(n["rules_checked"]))}</div>'
                   if n.get("rules_checked") else "")
        cites = "".join(cite_html(c, idx) for c in n.get("cites", []))
        note_blocks.append(f'''<section class="note b-{n["basis"]}" id="{esc(n["id"])}">
  <div class="note-head"><span class="glyph">{glyph}</span>
    <h3>{esc(n["claim"])}</h3>{crux}</div>
  <div class="basis" title="{esc(why)}">{esc(n["basis"])} — {esc(why)}</div>
  {f'<p class="detail">{esc(n["detail"])}</p>' if n.get("detail") else ""}
  {iff}{checked}{cites}
</section>''')

    counter = "".join(f'''<section class="counter">
  <h3>“{esc(c["reading"])}”</h3>
  <p>{esc(c["why_it_loses"])}</p>
  {"".join(cite_html(x, idx) for x in c.get("cites", []))}
</section>''' for c in ans.get("counterargument", []))

    rejected = "".join(
        f'<li><code>{esc(r["rule"])}</code> — {esc(r["why"])}</li>'
        for r in ans.get("considered_rejected", []))

    openq = "".join(f'<li>{esc(q)}</li>' for q in ans.get("open_questions", []))

    problems = "".join(f'<li>{esc(p)}</li>' for p in ans.get("_problems", []))
    ncites = sum(len(n.get("cites", [])) for n in ans["notes"])
    nverified = sum(1 for n in ans["notes"] for c in n.get("cites", []) if c["verified"])

    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ruling — {esc(ans["question"][:60])}</title>
<style>
:root{{--bg:#fbfaf8;--fg:#1a1a18;--dim:#6b6862;--line:#e0ddd6;--card:#fff;
 --grounded:#1f7a4d;--inferred:#9a6a12;--gap:#a33;--mark:#fff2a8;--accent:#2b5c9b}}
@media(prefers-color-scheme:dark){{:root{{--bg:#16171a;--fg:#e6e4e0;--dim:#9a978f;
 --line:#2e3034;--card:#1d1f23;--grounded:#4cc38a;--inferred:#d9a441;--gap:#f2777a;
 --mark:#5c4a12;--accent:#7aa7e0}}}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--fg);
 font:16px/1.6 ui-serif,Georgia,'Iowan Old Style',serif;padding:0 0 4rem}}
code{{font:0.85em ui-monospace,SFMono-Regular,Menlo,monospace}}
.wrap{{max-width:1180px;margin:0 auto;padding:0 1.2rem}}
header{{border-bottom:1px solid var(--line);padding:1.6rem 0 1.1rem;margin-bottom:1.4rem}}
.pin{{font:0.75rem ui-monospace,monospace;color:var(--dim);letter-spacing:.02em}}
h1{{font-size:1.15rem;font-weight:600;margin:.5rem 0 .2rem;line-height:1.35}}
.reframe{{color:var(--dim);font-size:.95rem;font-style:italic;margin:.35rem 0 0}}
.holding{{background:var(--card);border:1px solid var(--line);border-left:5px solid var(--accent);
 border-radius:6px;padding:1rem 1.1rem;margin:1.3rem 0}}
.disp{{display:inline-block;font:600 .72rem/1 ui-sans-serif,system-ui;letter-spacing:.09em;
 padding:.42em .7em;border-radius:3px;background:var(--accent);color:#fff;margin-bottom:.6rem}}
.disp.UNSETTLED{{background:var(--gap)}} .disp.DEPENDS{{background:var(--inferred)}}
.hline{{font-size:1.16rem;line-height:1.5}}
.sp-grounded{{border-bottom:2px solid var(--grounded);color:inherit;text-decoration:none}}
.sp-inferred{{border-bottom:2px dotted var(--inferred);color:inherit;text-decoration:none}}
.sp-grounded:hover,.sp-inferred:hover{{background:var(--mark)}}
.strength{{margin-top:.75rem;font-size:.82rem;color:var(--dim);
 font-family:ui-sans-serif,system-ui;border-top:1px solid var(--line);padding-top:.6rem}}
.forced{{color:var(--gap);font-weight:600}}
h2{{font:600 .78rem/1 ui-sans-serif,system-ui;letter-spacing:.1em;text-transform:uppercase;
 color:var(--dim);margin:2.4rem 0 .9rem;padding-bottom:.4rem;border-bottom:1px solid var(--line)}}
.note{{background:var(--card);border:1px solid var(--line);border-radius:6px;
 padding:.9rem 1rem;margin:.7rem 0;border-left:4px solid var(--line)}}
.note.b-grounded{{border-left-color:var(--grounded)}}
.note.b-structural{{border-left-color:var(--inferred)}}
.note.b-gap{{border-left-color:var(--gap)}}
.note-head{{display:flex;gap:.55rem;align-items:baseline}}
.note-head h3{{font-size:1rem;font-weight:600;margin:0;flex:1}}
.glyph{{color:var(--dim)}}
.crux{{font:600 .62rem/1 ui-sans-serif,system-ui;letter-spacing:.08em;background:var(--inferred);
 color:#fff;padding:.35em .55em;border-radius:3px}}
.basis{{font:.76rem ui-sans-serif,system-ui;color:var(--dim);margin:.35rem 0 .5rem}}
.detail{{margin:.5rem 0;font-size:.95rem}}
.iffalse{{background:var(--mark);border-radius:4px;padding:.55rem .7rem;margin:.55rem 0;font-size:.9rem}}
.checked{{font:.75rem ui-monospace,monospace;color:var(--dim);margin:.4rem 0}}
.cite{{margin:.45rem 0;border:1px solid var(--line);border-radius:4px;background:var(--bg)}}
.cite summary{{cursor:pointer;padding:.42rem .6rem;font-size:.85rem;list-style:none;
 display:flex;gap:.5rem;align-items:center}}
.cite summary::-webkit-details-marker{{display:none}}
.cite summary::before{{content:"▸";color:var(--dim);font-size:.8em}}
.cite[open] summary::before{{content:"▾"}}
.stamp{{font:600 .62rem/1 ui-sans-serif,system-ui;letter-spacing:.06em;padding:.3em .5em;border-radius:3px}}
.stamp.ok{{background:var(--grounded);color:#fff}} .stamp.bad{{background:var(--gap);color:#fff}}
.cite-body{{padding:.2rem .7rem .7rem;border-top:1px solid var(--line)}}
.ancestry{{list-style:none;margin:.6rem 0;padding:0}}
.ancestry li{{padding:.3rem 0 .3rem calc(var(--d) * 1.05rem);font-size:.88rem;
 border-left:2px solid var(--line);margin-left:.2rem}}
.ancestry li.anc-target{{background:var(--mark);border-radius:3px}}
.ancestry code{{color:var(--accent);margin-right:.45rem}}
.narrowed{{font-size:.8rem;color:var(--inferred);margin:.5rem 0}}
.prob{{font-size:.8rem;color:var(--gap);margin:.5rem 0}}
.copy{{font:.75rem ui-sans-serif,system-ui;padding:.35em .7em;border:1px solid var(--line);
 background:var(--bg);color:var(--fg);border-radius:3px;cursor:pointer}}
.counter{{background:var(--card);border:1px dashed var(--line);border-radius:6px;
 padding:.9rem 1rem;margin:.7rem 0}}
.counter h3{{font-size:.98rem;margin:0 0 .4rem;color:var(--gap)}}
.cards{{display:grid;grid-template-columns:repeat(auto-fill,minmax(14rem,1fr));gap:.9rem}}
.card{{margin:0;background:var(--card);border:1px solid var(--line);border-radius:6px;overflow:hidden;display:flex;flex-direction:column}}
.card-art{{width:100%;height:auto;display:block;background:var(--bg)}}
.card-art--none{{aspect-ratio:744/1039;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:.35rem;color:var(--dim);font-size:.78rem;text-align:center;border-bottom:1px solid var(--line)}}
.card-art--none span{{font-size:.7rem;opacity:.85}}
.card figcaption{{padding:.6rem .7rem;font-size:.82rem;display:flex;flex-direction:column;gap:.3rem}}
.card-text{{color:var(--dim);font-size:.76rem;line-height:1.45}}
ul.plain{{padding-left:1.2rem}} ul.plain li{{margin:.35rem 0;font-size:.93rem}}
@media(max-width:700px){{.hline{{font-size:1.05rem}}}}
@media print{{.cite{{break-inside:avoid}} .copy{{display:none}} body{{background:#fff}}}}
</style></head><body><div class="wrap">

<header>
  <div class="pin">CR {esc(ans["corpus"]["CR"])} · TR {esc(ans["corpus"]["TR"])} · generated {esc(ans["corpus"]["generated"])} · offline</div>
  <h1>{esc(ans["question"])}</h1>
  <p class="reframe">As the rules see it: {esc(ans["reframe"])}</p>
</header>

<div class="holding">
  <div class="disp {esc(disp)}">{esc(disp)}</div>
  <div class="hline">{holding_html(h, notes_by_id)}</div>
  <div class="strength">
    weakest link: <b>{esc(ans["_weakest"])}</b> ({esc(ans["_strength"])}) ·
    {nverified}/{ncites} citations verified verbatim
    {f'<div class="forced">verdict forced to UNSETTLED — a cited rule failed verification (was {esc(forced)})</div>' if forced else ""}
  </div>
</div>

<h2>Reasoning</h2>
{"".join(note_blocks)}

{f'<h2>The argument against, and why it loses</h2>{counter}' if counter else ""}
{f'<h2>Considered and rejected</h2><ul class="plain">{rejected}</ul>' if rejected else ""}
{cards_html(ans)}
{f'<h2>The rules do not settle</h2><ul class="plain">{openq}</ul>' if openq else ""}
{f'<h2>Verification problems</h2><ul class="plain">{problems}</ul>' if problems else ""}

</div><script>
// file:// has no clipboard API in Chrome — execCommand fallback is mandatory.
document.addEventListener('click', function(e){{
  var b = e.target.closest('.copy'); if(!b) return;
  var t = b.dataset.cite, done = function(){{ b.textContent='copied'; setTimeout(function(){{b.textContent='copy cite';}},1200); }};
  try {{ if(navigator.clipboard && window.isSecureContext) {{ navigator.clipboard.writeText(t).then(done); return; }} }} catch(_){{}}
  var ta=document.createElement('textarea'); ta.value=t; ta.style.position='fixed'; ta.style.opacity=0;
  document.body.appendChild(ta); ta.select();
  try {{ document.execCommand('copy'); done(); }} catch(_){{ b.textContent='copy failed'; }}
  document.body.removeChild(ta);
}});
// Jumping to a note from the holding line should open its citations.
window.addEventListener('hashchange', function(){{
  var el=document.querySelector(location.hash); if(!el) return;
  el.querySelectorAll('details').forEach(function(d){{d.open=true;}});
}});
// Judges print things; printed <details> must not hide the evidence.
window.addEventListener('beforeprint', function(){{
  document.querySelectorAll('details').forEach(function(d){{d.dataset.wasOpen=d.open?'1':'';d.open=true;}});
}});
window.addEventListener('afterprint', function(){{
  document.querySelectorAll('details').forEach(function(d){{d.open=d.dataset.wasOpen==='1';}});
}});
</script></body></html>'''


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "answer.json"
    out = sys.argv[2] if len(sys.argv) > 2 else "report.html"
    ans = json.load(open(src, encoding="utf-8"))
    idx = RuleIndex()
    ans = verify_answer(ans, idx)
    # The gate lives here, not only in `rules_cli.py report`. A sibling caller
    # that skipped it produced a byte-identical-looking artifact carrying a
    # green badge over a fabricated citation.
    if ans["_problems"] and "--force" not in sys.argv:
        print("VERIFICATION FAILED — refusing to render:", file=sys.stderr)
        for pb in ans["_problems"]:
            print(f"  ! {pb}", file=sys.stderr)
        sys.exit(1)
    open(out, "w", encoding="utf-8").write(render(ans, idx))
    ncites = sum(len(n.get("cites", [])) for n in ans["notes"])
    nver = sum(1 for n in ans["notes"] for c in n.get("cites", []) if c["verified"])
    print(f"wrote {out}")
    print(f"  disposition : {ans['holding']['disposition']}"
          + (f" (forced from {ans['holding']['_forced']})" if ans['holding'].get('_forced') else ""))
    print(f"  citations   : {nver}/{ncites} verified")
    print(f"  weakest link: {ans['_weakest']} ({ans['_strength']})")
    for p in ans["_problems"]:
        print(f"  ! {p}")


if __name__ == "__main__":
    main()

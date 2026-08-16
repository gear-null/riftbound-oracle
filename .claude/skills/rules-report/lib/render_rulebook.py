"""Render the parsed rulebook as one anchored HTML document.

Reports cite rules by id. Until now a citation could be *expanded* in place but
not *followed* — there was nowhere to go. This builds that destination: every
rule gets a stable `id`, so `rules.html#CR-471.1.b.1` lands on the exact clause,
and a report's citations become real links.

Why generate rather than convert Riot's PDF: we already hold something strictly
better. `rules.json` is the same text parsed into 3,300+ addressable rules with
parent, children, examples and cross-references. That makes two things possible
a PDF cannot do — every cross-reference in the rules becomes a working link, and
the anchor scheme matches the ids the verifier already checks citations against.
One source of truth, so a rules update can never drift the links out of sync.
"""
import html
import json
import os
import re
from collections import defaultdict

DOC_TITLE = {"CR": "Comprehensive Rules", "TR": "Tournament Rules"}
# Hoisted: the ordering below indexed into a fresh list(DOC_TITLE) per comparison.
DOC_ORDER = list(DOC_TITLE)

# Bare ids inside rule text ("see 471.1.b") become links. Requires at least one
# dot so ordinary numbers — "8 points", "2026" — are left alone.
INLINE_REF = re.compile(r"\b(\d{3}(?:\.[0-9a-z]+)+)\b")


def esc(s):
    return html.escape(str(s or ""))


def anchor(doc, rule_id):
    """The stable anchor for a rule. Must match what render_report.py links to."""
    return f"{doc}-{rule_id}"


def _linkify(text, doc, known):
    """Turn in-text rule references into same-page links.

    Only ids that actually exist in this document are linked; an unresolvable
    reference is left as plain text rather than becoming a link to nowhere.
    """
    def sub(m):
        rid = m.group(1)
        if rid not in known:
            return rid
        return f'<a class="xref" href="#{anchor(doc, rid)}">{rid}</a>'

    return INLINE_REF.sub(sub, esc(text))


def _rule_block(rule, known):
    doc, rid = rule["doc"], rule["id"]
    depth = rule.get("depth", 1)
    body = _linkify(rule["text"], doc, known)

    examples = "".join(
        f'<div class="eg">{_linkify(e, doc, known)}</div>'
        for e in rule.get("examples", [])
    )

    see = rule.get("see_also") or []
    xrefs = ""
    if see:
        links = ", ".join(
            f'<a href="#{anchor(doc, x)}">{esc(x)}</a>' if x in known else esc(x)
            for x in see
        )
        xrefs = f'<div class="see">see also {links}</div>'

    # depth 1 is a section heading; give it real heading semantics so the
    # document is navigable by screen reader and by browser find-as-you-type.
    tag = "h2" if depth == 1 else "div"
    return (
        f'<section class="r d{min(depth, 6)}" id="{esc(anchor(doc, rid))}">'
        f'<{tag} class="rt">'
        f'<a class="rid" href="#{esc(anchor(doc, rid))}" title="link to {esc(rid)}">{esc(rid)}</a>'
        f'<span class="rtext">{body}</span>'
        f"</{tag}>"
        f"{examples}{xrefs}"
        f"</section>"
    )


def _toc(rules_by_doc):
    items = []
    for doc, rules in rules_by_doc.items():
        tops = [r for r in rules if r.get("depth") == 1]
        links = "".join(
            f'<li><a href="#{esc(anchor(doc, r["id"]))}">'
            f'<span class="n">{esc(r["id"])}</span> {esc(r["text"])}</a></li>'
            for r in tops
        )
        items.append(
            f'<section class="toc-doc"><h3>{esc(DOC_TITLE.get(doc, doc))}</h3>'
            f'<ol class="toc">{links}</ol></section>'
        )
    return "".join(items)


def render_rulebook(rules, version="unknown"):
    """One self-contained HTML page holding both rule documents."""
    by_doc = defaultdict(list)
    for r in rules:
        by_doc[r["doc"]].append(r)

    # CR before TR; anything else after, alphabetically — deterministic output
    # so regenerating an unchanged corpus produces an unchanged file.
    order = sorted(by_doc, key=lambda d: (DOC_ORDER.index(d) if d in DOC_ORDER else len(DOC_ORDER), d))
    by_doc = {d: by_doc[d] for d in order}

    sections = []
    for doc, doc_rules in by_doc.items():
        known = {r["id"] for r in doc_rules}
        blocks = "".join(_rule_block(r, known) for r in doc_rules)
        sections.append(
            f'<article class="doc" id="{esc(doc)}">'
            f'<h1>{esc(DOC_TITLE.get(doc, doc))} <span class="tag">{esc(doc)}</span></h1>'
            f"{blocks}</article>"
        )

    total = sum(len(v) for v in by_doc.values())
    return _PAGE.format(
        version=esc(version),
        total=total,
        toc=_toc(by_doc),
        body="".join(sections),
        css=_CSS,
        js=_JS,
    )


# Riftbound — Runeterra Visual Language. This page is not only read on its own:
# a report opens it inside an overlay, so a light theme here would put a white
# sheet inside a dark chamfered frame. The two documents share one register.
_CSS = """
:root{
 --ink-900:#060b14; --ink-800:#0a1428; --ink-700:#0f1e33; --ink-500:#1e3a52;
 --mist-100:#e4f1f5; --slate-300:#7a96a8; --slate-400:#4a6a80;
 --gold-700:#785a28; --gold-500:#c8aa6e; --blue:#3c8fe0;
 --bg:var(--ink-900); --fg:var(--mist-100); --dim:var(--slate-300);
 --line:var(--ink-500); --card:var(--ink-800); --accent:var(--blue);
 --display:"Beaufort for LOL",Cinzel,Georgia,"Times New Roman",serif;
 --body:"TT Norms Pro Compact",Barlow,system-ui,-apple-system,"Segoe UI","Helvetica Neue",Arial,sans-serif;
 --plate:"Barlow Semi Condensed",Inter,system-ui,-apple-system,"Segoe UI",sans-serif;
 --wash:color-mix(in oklch,var(--gold-500) 12%,transparent);
 --lift:color-mix(in oklch,var(--ink-700) 88%,var(--mist-100));
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:400 15px/1.65 var(--body)}
::selection{background:var(--gold-700);color:var(--mist-100)}
.grain{position:fixed;inset:0;z-index:50;pointer-events:none;opacity:.035;mix-blend-mode:overlay;
 background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='160' height='160'><filter id='g'><feTurbulence type='fractalNoise' baseFrequency='0.8' numOctaves='4' stitchTiles='stitch'/></filter><rect width='160' height='160' filter='url(%23g)'/></svg>")}
.wrap{max-width:54rem;margin:0 auto;padding:2rem 1.4rem 6rem}
header{border-bottom:1px solid var(--line);padding-bottom:1.2rem;margin-bottom:1.6rem}
header h1{margin:0;font:600 1.15rem/1 var(--display);letter-spacing:.13em;
 text-transform:uppercase;color:var(--gold-500)}
h1{margin:3rem 0 1.2rem;scroll-margin-top:1rem;font:600 1.1rem/1.3 var(--display);
 letter-spacing:.12em;text-transform:uppercase;color:var(--gold-500);
 display:flex;align-items:center;gap:.8rem}
h1::after{content:"";flex:1;height:1px;background:var(--gold-700);opacity:.5}
.tag{flex:none;padding:.3em .5em;border:1px solid var(--gold-700);font:600 .6rem/1 var(--plate);
 letter-spacing:.14em;color:var(--slate-300)}
.meta{margin-top:.7rem;color:var(--dim);font:500 .76rem/1.6 var(--plate);letter-spacing:.05em}
.search{width:100%;margin:1.1rem 0 0;padding:.7rem .8rem;border:1px solid var(--line);
 background:var(--card);color:var(--fg);font:400 .92rem/1.4 var(--body)}
.search::placeholder{color:var(--dim)}
.search:focus-visible{outline:2px solid var(--gold-500);outline-offset:2px;border-color:var(--gold-500)}
.toc-doc h3{margin:1.6rem 0 .5rem;font:600 .68rem/1 var(--plate);letter-spacing:.17em;
 text-transform:uppercase;color:var(--gold-500)}
ol.toc{list-style:none;margin:0;padding:0;columns:2;column-gap:2rem}
@media(max-width:640px){ol.toc{columns:1}}
ol.toc li{margin:.1rem 0;break-inside:avoid}
ol.toc a{display:block;padding:.2rem .35rem;color:var(--dim);text-decoration:none;font-size:.86rem}
ol.toc a:hover{background:var(--lift);color:var(--fg)}
ol.toc .n{display:inline-block;min-width:2.8rem;font:600 .76rem/1 var(--plate);
 letter-spacing:.04em;font-variant-numeric:tabular-nums;color:var(--slate-300)}
ol.toc a:hover .n{color:var(--gold-500)}
/* Enough headroom that a rule arrived at from a citation lands with its
   neighbours visible, rather than pinned against the top of the overlay. */
.r{scroll-margin-top:2.5rem;padding:.2rem .35rem}
/* Arriving from a citation, the rule you asked for is lit, not highlighter-penned. */
.r:target{background:var(--wash);box-shadow:-.35rem 0 0 var(--gold-500),0 0 0 .35rem var(--wash)}
.d1{margin-top:2.2rem;border-top:1px solid var(--line);padding-top:1.1rem}
.d2{margin-left:0}.d3{margin-left:1.1rem}.d4{margin-left:2.2rem}
.d5{margin-left:3.3rem}.d6{margin-left:4.4rem}
.rt{display:flex;gap:.7rem;align-items:baseline;margin:0;font-size:inherit;font-weight:inherit}
h2.rt{font:600 1.02rem/1.4 var(--body)}
/* Rule ids are the addresses a judge reads out loud, so they sit at Slate 300
   (6.34:1 on --bg, which is what .rid actually renders against), not at the
   Slate 400 divider floor. */
.rid{flex:none;min-width:4.8rem;padding-top:.1rem;color:var(--slate-300);text-decoration:none;
 font:600 .78rem/1.5 var(--plate);letter-spacing:.05em;font-variant-numeric:tabular-nums}
.rid:hover{color:var(--gold-500)}
.rtext{flex:1;max-width:68ch}
a.xref{color:var(--accent);text-decoration:none;border-bottom:1px dotted var(--accent)}
a.xref:hover{color:var(--fg);border-bottom-color:var(--fg)}
.eg{margin:.4rem 0 .4rem 5.5rem;padding:.5rem .8rem;background:var(--card);
 border-left:2px solid var(--gold-700);font-size:.87rem;color:var(--dim);max-width:64ch}
.see{margin:.25rem 0 .25rem 5.5rem;font:500 .76rem/1.6 var(--plate);letter-spacing:.06em;
 /* --dim, not slate-400: that is the divider floor (3.4:1 here) and this is
    text. An unresolvable cross-reference stays as bare text, so the refs you
    cannot follow were also the ones you could barely read. */
 color:var(--dim)}
.see a{color:var(--accent);text-decoration:none;border-bottom:1px dotted var(--accent)}
.see a:hover{color:var(--fg);border-bottom-color:var(--fg)}
a:focus-visible{outline:2px solid var(--gold-500);outline-offset:2px}
.hide{display:none}
@media print{
 /* Without color-scheme:light the UA paints the canvas near-black wherever the
    page background is transparent, and the sheet prints black on black. */
 :root{color-scheme:light;
  --bg:transparent;--fg:var(--ink-900);--dim:var(--slate-400);--line:var(--slate-400);
  --card:transparent;--accent:var(--ink-700);--wash:transparent;--lift:transparent;
  /* Raw palette tokens need remapping too, not just the semantic ones —
     anything using one DIRECTLY kept its dark-ground value on paper
     (slate-300 3.1:1, gold-500 2.2:1, mist-100 1.2:1 on white). */
  --slate-300:var(--slate-400);--gold-500:var(--gold-700);--mist-100:var(--slate-400)}
 html,body{background:transparent}
 body{font-size:10.5pt}
 .grain,.search{display:none!important}
 header h1,h1,.toc-doc h3{color:var(--gold-700)}
 .r:target{background:transparent;box-shadow:none}
 .r{break-inside:avoid}
}
"""

# Filtering is the one thing a static page genuinely needs: the rulebook is long,
# and a reader arriving from a citation often wants the neighbourhood, not a
# browser find that stops at the first of forty matches.
_JS = """
const q=document.getElementById('q'),rules=[...document.querySelectorAll('.r')];
let t;q.addEventListener('input',()=>{clearTimeout(t);t=setTimeout(()=>{
 const v=q.value.trim().toLowerCase();
 rules.forEach(r=>r.classList.toggle('hide',v&&!r.textContent.toLowerCase().includes(v)));
 document.querySelectorAll('.toc-doc,.doc h1').forEach(e=>e.classList.toggle('hide',!!v));
},120)});
"""

_PAGE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark">
<title>Riftbound Rules — {version}</title>
<style>{css}</style>
</head><body>
<div class="grain" aria-hidden="true"></div>
<div class="wrap">
<header>
  <h1>Riftbound Rules</h1>
  <div class="meta">{total} rules · rules version {version} · generated from the same
   parsed corpus the citation verifier checks against</div>
  <input id="q" class="search" type="search" placeholder="Filter rules…" autocomplete="off">
</header>
{toc}
{body}
</div><script>{js}</script></body></html>
"""


def main():
    import sys

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from corpus import rules_json, rulebook_html_path

    rules = json.load(open(rules_json(), encoding="utf-8"))
    version = os.environ.get("RIFTBOUND_RULES_VERSION", "2026-07-16")
    out = rulebook_html_path()
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(render_rulebook(rules, version))
    print(f"  {len(rules)} rules -> {out}")


if __name__ == "__main__":
    main()

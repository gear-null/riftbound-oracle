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
    order = sorted(by_doc, key=lambda d: (d not in DOC_TITLE, list(DOC_TITLE).index(d) if d in DOC_TITLE else 0, d))
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


_CSS = """
:root{--bg:#fbfbfa;--fg:#22242a;--dim:#6b7078;--line:#e3e3e0;--card:#fff;
 --accent:#2b5c9b;--mark:#fff2a8}
@media(prefers-color-scheme:dark){:root{--bg:#16181c;--fg:#e6e7ea;--dim:#9aa0a8;
 --line:#2e3034;--card:#1d1f23;--accent:#7aa7dd;--mark:#5a4a12}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
 font:15px/1.6 ui-sans-serif,-apple-system,"Segoe UI",system-ui,sans-serif}
.wrap{max-width:52rem;margin:0 auto;padding:2rem 1.25rem 6rem}
header{border-bottom:1px solid var(--line);padding-bottom:1rem;margin-bottom:1.5rem}
h1{font-size:1.5rem;margin:2.5rem 0 1rem;scroll-margin-top:4rem}
.tag{font-size:.7rem;color:var(--dim);border:1px solid var(--line);
 border-radius:3px;padding:.1rem .35rem;vertical-align:middle}
.meta{color:var(--dim);font-size:.82rem}
.search{width:100%;padding:.55rem .7rem;margin:1rem 0 0;border:1px solid var(--line);
 border-radius:6px;background:var(--card);color:var(--fg);font-size:.9rem}
.toc-doc h3{font-size:.78rem;text-transform:uppercase;letter-spacing:.06em;
 color:var(--dim);margin:1.25rem 0 .4rem}
ol.toc{list-style:none;margin:0;padding:0;columns:2;column-gap:1.5rem}
@media(max-width:640px){ol.toc{columns:1}}
ol.toc li{margin:.15rem 0;break-inside:avoid}
ol.toc a{color:inherit;text-decoration:none;font-size:.86rem}
ol.toc a:hover{color:var(--accent)}
ol.toc .n{color:var(--dim);font-variant-numeric:tabular-nums;
 display:inline-block;min-width:2.6rem}
.r{scroll-margin-top:1rem;padding:.15rem 0}
.r:target{background:var(--mark);border-radius:5px;
 box-shadow:0 0 0 .5rem var(--mark)}
.d1{margin-top:2rem;border-top:1px solid var(--line);padding-top:1rem}
.d2{margin-left:0}.d3{margin-left:1.1rem}.d4{margin-left:2.2rem}
.d5{margin-left:3.3rem}.d6{margin-left:4.4rem}
.rt{display:flex;gap:.6rem;align-items:baseline;margin:0;font-size:inherit;font-weight:inherit}
h2.rt{font-size:1.05rem;font-weight:650}
.rid{color:var(--dim);text-decoration:none;font-variant-numeric:tabular-nums;
 font-size:.8rem;min-width:4.6rem;flex:none;padding-top:.15rem}
.rid:hover{color:var(--accent)}
.rtext{flex:1}
a.xref{color:var(--accent);text-decoration:none;border-bottom:1px dotted var(--accent)}
.eg{margin:.3rem 0 .3rem 5.2rem;padding:.4rem .7rem;background:var(--card);
 border-left:2px solid var(--line);border-radius:0 4px 4px 0;
 font-size:.86rem;color:var(--dim)}
.see{margin:.2rem 0 .2rem 5.2rem;font-size:.8rem;color:var(--dim)}
.see a{color:var(--accent);text-decoration:none}
.hide{display:none}
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
<title>Riftbound Rules — {version}</title>
<style>{css}</style>
</head><body><div class="wrap">
<header>
  <h1 style="margin-top:0">Riftbound Rules</h1>
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

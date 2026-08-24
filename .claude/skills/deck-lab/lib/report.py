"""The deck report: one page, two kinds of number, never mixed.

The top half is shuffle math — exact, six figures of trials, no decisions in it.
The bottom half is played games — tens of them, each one a sequence of
judgement calls. Presenting those as one number would be dishonest, so the page
keeps them apart and puts `n` beside everything that has one.
"""
import html
import os
import re
from datetime import date

import analyze
import cards
import deckfile
import journal

HERE = os.path.dirname(os.path.abspath(__file__))
REPORTS = os.path.join(os.path.dirname(HERE), "reports")

CSS = """
:root{--bg:#fbfaf8;--fg:#1a1a19;--dim:#6b6a66;--line:#e2e0da;--card:#ffffff;
--accent:#7a5cff;--good:#1f8a5b;--warn:#b4620a;--bad:#b32d2d;--bar:#cfc7f5}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){
--bg:#14140f;--fg:#eceae4;--dim:#98958c;--line:#2e2d27;--card:#1c1b16;
--accent:#a58cff;--good:#4fc08a;--warn:#e0913f;--bad:#e06a6a;--bar:#3b3470}}
:root[data-theme=dark]{--bg:#14140f;--fg:#eceae4;--dim:#98958c;--line:#2e2d27;
--card:#1c1b16;--accent:#a58cff;--good:#4fc08a;--warn:#e0913f;--bad:#e06a6a;--bar:#3b3470}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--fg);margin:0;padding:2rem 1.25rem 5rem;
font:15px/1.55 ui-sans-serif,-apple-system,"Segoe UI",system-ui,sans-serif}
main{max-width:60rem;margin:0 auto}
h1{font-size:1.65rem;margin:0 0 .2rem;letter-spacing:-.02em}
h2{font-size:1rem;text-transform:uppercase;letter-spacing:.09em;color:var(--dim);
margin:2.6rem 0 .8rem;font-weight:600}
.sub{color:var(--dim);margin:0 0 1.6rem}
.badge{display:inline-block;padding:.12rem .5rem;border-radius:99px;font-size:.75rem;
font-weight:600;letter-spacing:.03em}
.ok{background:color-mix(in srgb,var(--good) 18%,transparent);color:var(--good)}
.no{background:color-mix(in srgb,var(--bad) 18%,transparent);color:var(--bad)}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:1rem 1.15rem;margin:.6rem 0}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
th,td{text-align:right;padding:.34rem .5rem;border-bottom:1px solid var(--line)}
th:first-child,td:first-child{text-align:left}
th{color:var(--dim);font-weight:600;font-size:.8rem}
.scroll{overflow-x:auto}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(11rem,1fr));gap:.6rem}
.stat{font-size:1.45rem;font-weight:600;letter-spacing:-.02em}
.stat span{font-size:.8rem;font-weight:400;color:var(--dim)}
.note{color:var(--dim);font-size:.88rem}
ul{margin:.4rem 0;padding-left:1.1rem}
li{margin:.15rem 0}
code{font:13px ui-monospace,SFMono-Regular,Menlo,monospace;
background:color-mix(in srgb,var(--fg) 8%,transparent);padding:.05rem .3rem;border-radius:4px}
"""


def esc(v):
    return html.escape(str(v))


def bars(counts, label):
    """A curve as inline SVG — no library, no network, scales to the page."""
    if not counts:
        return ""
    keys = sorted(counts, key=lambda k: int(k))
    peak = max(counts.values()) or 1
    w, gap, h = 44, 8, 110
    total_w = len(keys) * (w + gap)
    out = [f'<svg viewBox="0 0 {total_w} {h + 34}" width="100%" style="max-width:{total_w}px" '
           f'role="img" aria-label="{esc(label)}">']
    for i, k in enumerate(keys):
        v = counts[k]
        bh = round(h * v / peak)
        x = i * (w + gap)
        out.append(f'<rect x="{x}" y="{h - bh}" width="{w}" height="{bh}" rx="3" fill="var(--bar)"/>')
        out.append(f'<text x="{x + w/2}" y="{h - bh - 5}" text-anchor="middle" '
                   f'font-size="11" fill="var(--dim)">{v}</text>')
        out.append(f'<text x="{x + w/2}" y="{h + 20}" text-anchor="middle" '
                   f'font-size="12" fill="var(--fg)">{esc(k)}</text>')
    out.append("</svg>")
    return "".join(out)


def turn_table(sim, rows):
    turns = sim["turns"]
    head = "".join(f"<th>T{t}</th>" for t in range(1, turns + 1))
    body = []
    for label, key, fmt in rows:
        series = sim[key][1:] if not isinstance(sim[key], dict) else None
        if series is None:
            continue
        cells = "".join(f"<td>{fmt(v)}</td>" for v in series)
        body.append(f"<tr><td>{esc(label)}</td>{cells}</tr>")
    for domain, series in sorted(sim["domain_online"].items()):
        cells = "".join(f"<td>{v:.0%}</td>" for v in series[1:])
        body.append(f"<tr><td>{esc(domain)} available</td>{cells}</tr>")
    return (f'<div class="scroll"><table><tr><th>per turn</th>{head}</tr>'
            + "".join(body) + "</table></div>")


def build(deck, trials=50000, out_path=None):
    result = analyze.analyse(deck, trials=trials)
    comp = result["composition"]
    legality = deckfile.check(deck)
    played = journal.matchups(deck.name)
    total_games = sum(m["games"] for m in played)

    verdict = ('<span class="badge ok">LEGAL</span>' if legality.legal
               else '<span class="badge no">ILLEGAL</span>')

    parts = [f"""<title>{esc(deck.name)}</title><style>{CSS}</style><main>
<h1>{esc(deck.name)} {verdict}</h1>
<p class="sub">{esc(deck.legend)} · champion {esc(deck.chosen_champion or "not set")} ·
{esc("/".join(comp["domain_identity"]))} · {deckfile.MODE["name"]} · {date.today().isoformat()}</p>"""]

    if not legality.legal:
        items = "".join(f"<li>{esc(e)}</li>" for e in legality.errors)
        parts.append(f'<div class="card"><strong>This deck cannot be legally registered.</strong>'
                     f'<ul>{items}</ul></div>')

    parts.append(f"""<div class="card grid">
<div><div class="stat">{comp["main_deck_size"]}<span> main deck</span></div></div>
<div><div class="stat">{comp["average_energy"]}<span> avg energy</span></div></div>
<div><div class="stat">{comp["average_might"] or "—"}<span> avg might</span></div></div>
<div><div class="stat">{comp["cards_with_text"]}<span> of {comp["shuffled_cards"]} have text</span></div></div>
</div>""")

    parts.append("<h2>Composition</h2>")
    types = " · ".join(f"{v} {k.lower()}" for k, v in sorted(comp["by_type"].items()))
    runes = " · ".join(f"{v} {k}" for k, v in sorted(comp["rune_split"].items()))
    parts.append(f'<div class="card"><p class="note">{esc(types)} &nbsp;|&nbsp; runes: {esc(runes)}</p>'
                 f'{bars(comp["curve"], "energy curve")}'
                 f'<p class="note">Energy cost of the {comp["shuffled_cards"]} shuffled cards. '
                 f'The Chosen Champion starts in the Champion Zone and is not among them.</p></div>')

    parts.append("<h2>Shuffle math</h2>")
    parts.append(f'<p class="note">{trials:,} shuffles per line, no decisions made. '
                 f'Nothing is spent, so these are the resources and options a pilot had '
                 f'available — a ceiling, not a record of play.</p>')
    rows = [
        ("has a play", "has_a_play", lambda v: f"{v:.0%}"),
        ("castable in hand", "castable_in_hand", lambda v: f"{v:.1f}"),
        ("stranded in hand", "stranded_in_hand", lambda v: f"{v:.1f}"),
        ("blocked on power", "power_denied", lambda v: f"{v:.0%}"),
    ]
    for label, key in (("On the play", "on_the_play"), ("On the draw", "on_the_draw")):
        parts.append(f'<div class="card"><strong>{label}</strong>{turn_table(result[key], rows)}</div>')

    parts.append("<h2>Played games</h2>")
    if not played:
        parts.append('<div class="card"><p class="note">No games recorded against this deck yet. '
                     'Play some with <code>deck_cli.py new</code> and record the result with '
                     '<code>deck_cli.py record</code>; they will appear here with their sample size.</p></div>')
    else:
        rows_html = []
        for m in played:
            # A mirror carries no rate — it is 50% by construction — so the row
            # says so rather than rendering a number it does not have.
            if m["rate"] is None:
                rows_html.append(
                    f"<tr><td>{esc(m['opponent'])}</td><td>—</td><td>—</td>"
                    f"<td>{esc(m['notes'][0] if m['notes'] else '')}</td>"
                    f"<td>{m['games']}</td></tr>"
                )
                continue
            rows_html.append(
                f"<tr><td>{esc(m['opponent'])}</td><td>{m['wins']}–{m['games'] - m['wins']}</td>"
                f"<td>{m['rate']:.0%}</td><td>{m['low']:.0%} – {m['high']:.0%}</td>"
                f"<td>{m['games']}</td></tr>"
            )
        parts.append(
            '<div class="card"><div class="scroll"><table>'
            '<tr><th>opponent</th><th>W–L</th><th>rate</th><th>95% interval</th><th>n</th></tr>'
            + "".join(rows_html) + "</table></div>"
            f'<p class="note">{total_games} game(s) total. Intervals are Wilson, which stays '
            'inside 0–100% at these sample sizes. At n below about 20 the interval is wider '
            'than most differences worth acting on — treat these as anecdotes with citations, '
            'and read the game logs rather than the percentage.</p></div>'
        )

    parts.append("<h2>What this report does not know</h2>")
    caveats = [
        f"{comp['cards_with_text']} of {comp['shuffled_cards']} shuffled cards have rules text. "
        "The table does not read it — a human or an agent applies every card effect by hand, "
        "so the shuffle math above counts a card as castable, never as good.",
    ]
    if comp["ambiguous_power_split"]:
        caveats.append(
            "The card data carries a Power count and a domain list, not one domain per printed "
            "symbol, so the exact split is unknown for: "
            + ", ".join(comp["ambiguous_power_split"])
            + ". Those are treated as payable from any of the card's domains, which is "
            "permissive rather than strict."
        )
    caveats.extend(legality.unchecked)
    parts.append('<div class="card"><ul>' + "".join(f"<li>{esc(c)}</li>" for c in caveats) + "</ul></div>")

    parts.append("</main>")

    out_path = out_path or os.path.join(REPORTS, f"{_slug(deck.name)}.html")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("<!doctype html><meta charset=utf-8>"
                 '<meta name=viewport content="width=device-width,initial-scale=1">'
                 + "".join(parts))
    return out_path


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "deck"

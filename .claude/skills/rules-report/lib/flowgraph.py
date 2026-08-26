"""Draw a primer's step graph — derived, never authored.

A primer explains a procedure, and a procedure is a graph: numbered steps with
labelled transitions between them. The transitions are already in the answer
file as `steps[].exits[]`, and every one of them has been through the same
verbatim citation gate as any other claim in this project.

So the diagram is computed from that data and from nothing else. There is no
field in which an author can draw an arrow, which means the picture cannot say
something the document does not DECLARE — and a declared transition must either
cite a rule or openly downgrade the document's confidence, which the arrow then
shows: solid for stated outright, dashed for inferred or unsettled, and a heavy
inverted arrow for one whose citation failed.

"Cannot say something the CITATIONS do not" was the first wording and it was too
strong: an exit declared `structural` carries no citation and still draws. That
is the honest concession, not a hole — but the picture has to say which it is,
which is why basis reaches the stroke and the verification outcome reaches it too.

The argument is ADR 0006's, for the symbol legend: a derived artifact cannot
drift from its source, and a hand-drawn one always eventually does.

Two renderings, one graph:

    svg()      inline SVG for the report — self-contained, no library, no
               network, colours drawn from the report's CSS custom properties
               so the print sheet inverts it with everything else
    mermaid()  text source for the website and for diagramming tools that want
               to restyle it, emitted by `rules_cli.py graph`

The layout is a vertical spine with the off-spine transitions routed through
numbered lanes in the right gutter, because that is the shape every procedural
loop in these rules actually has: a sequence you fall through, plus a handful of
back-edges that send you somewhere earlier.
"""

# Geometry. Tuned against the HOT FEPR loop — 5 steps and 12 transitions, of
# which 4 are back-edges and one more is a self-return.
BOX_W = 312
BOX_H = 54
GAP = 40           # vertical room between boxes — the spine arrow lives here
LANE_W = 30        # horizontal pitch of the gutter lanes
LANE_X0 = 26       # first lane's offset past the right edge of the boxes
PAD_X = 16
PAD_Y = 22
TERMINAL_W = 96    # room for an exit-the-loop arrow past the last lane

# Basis speaks the same language here as everywhere else on the page: a gold
# edge is a transition a rule states outright, a blue one follows from the rules
# cited, a grey one is not settled. Tokens, not literals, so @media print
# remaps them along with the rest of the sheet.
EDGE_COLOUR = {
    "grounded": "var(--gold-500)",
    "structural": "var(--blue)",
    "inferred": "var(--blue)",
    "gap": "var(--slate-300)",
    # Not a basis. An edge whose citation failed the verbatim check, drawn in
    # the same inverted Mist the ✗ UNVERIFIED stamp uses, so the map carries the
    # warning the rest of a forced page already carries. It has to survive a
    # glance, a greyscale printer and a reader who does not know the palette —
    # which is why it is the one edge style that is not a hue.
    "unverified": "var(--mist-100)",
}


# Per-glyph widths at the .82rem the step label is set in, measured in a browser
# against the rendered SVG rather than guessed. A flat average was the first
# attempt and it is simply wrong for a proportional face: at 6.15px/char an
# ordinary 42-character heading measured 279px in a 262px box, and one set in
# caps measured 537px — the text ran out over the transition arrows beside it.
#
# Rounded UP within each class, because the face that actually renders is
# whatever the reader has: Beaufort and TT Norms are proprietary and not
# redistributed, so what ships is a fallback stack. Overestimating clips a
# heading a word early; underestimating puts it through the diagram.
_NARROW = "iljI.,;:'!|()[]{}/\\`"
_WIDE = "WM"


def _char_w(ch):
    if ch == " ":
        return 3.3
    if ch in _NARROW:
        return 4.4
    if ch in _WIDE:
        return 12.8
    if ch in "—–":
        return 11.6
    if ch.isdigit():
        return 8.6
    if ch.isupper():
        return 10.1
    return 7.6


def _clip(text, width):
    """Shorten to fit `width` px, on a word boundary where one is available.

    Belt only — `svg()` also clips the text to the box geometrically, because an
    estimate against an unknown font can always be wrong and a heading spilling
    over the arrows is worse than one cut a word short.
    """
    text = " ".join(str(text).split())
    if sum(_char_w(c) for c in text) <= width:
        return text
    room, cut = width - _char_w("…"), 0
    used = 0.0
    for i, ch in enumerate(text):
        used += _char_w(ch)
        if used > room:
            break
        cut = i + 1
    head = text[:cut]
    space = head.rfind(" ")
    return (head[:space] if space > 0 else head).rstrip(" ,;:—-") + "…"


def build(steps):
    """The graph: one node per step, one edge per exit, numbered in document order.

    Edge numbering is global and follows the document, so edge 4 on the diagram
    is edge 4 in the prose beneath it. Two renderings of one numbering beats two
    numberings a reader has to reconcile.
    """
    order = {s["id"]: i for i, s in enumerate(steps)}
    nodes = [{"id": s["id"], "index": i, "heading": s.get("heading", s["id"]),
              "basis": s.get("basis", "grounded"), "y": PAD_Y + i * (BOX_H + GAP)}
             for i, s in enumerate(steps)]

    edges, n = [], 0
    spine_used = [False] * len(steps)
    for i, s in enumerate(steps):
        for ex in s.get("exits", []) or []:
            n += 1
            goto = ex.get("goto")
            # `goto` absent is a deliberate value, not an omission: it is how a
            # step says the procedure ENDS here. Distinguishing it from a typo
            # is the verifier's job (it rejects a goto naming no step), so by
            # the time layout runs, None means exactly one thing.
            # `goto is not None`, matching verify_primer exactly. `if goto`
            # made an empty string falsy, so the verifier called it "a goto
            # naming no step" while the classifier read it as "the procedure
            # ends here" — two derived renderings of one JSON value telling a
            # reader two different stories.
            target = order.get(goto) if goto is not None else None
            if goto is not None and target is None:
                # A goto naming no step. verify_primer refuses to render such a
                # primer at all, so this is only reachable under --force — but
                # the edge still consumes its number, because dropping it here
                # would renumber every later transition and silently break the
                # correspondence between the map and the prose beside it.
                kind = "broken"
            elif target is None:
                kind = "out"
            elif target == i:
                kind = "self"
            elif target == i + 1 and not spine_used[i]:
                # Only the first. Two exits from the same step to the next one
                # were both drawn at the spine's fixed geometry — two identical
                # lines and two badges at identical coordinates, the later one
                # painting out the earlier with an opaque fill. One arrow shown
                # for two cited transitions, and the number the prose cites is
                # not on the map: invariant 12's "no fewer" half, without
                # --force. The rest route through the gutter like any other
                # off-spine move.
                kind = "next"
                spine_used[i] = True
            elif target == i + 1:
                kind = "skip"
            elif target > i:
                kind = "skip"
            else:
                kind = "back"
            edges.append({
                "n": n, "from": i, "to": target, "kind": kind,
                "when": ex.get("when", ""),
                "basis": ex.get("basis", "grounded"),
                # The VERIFICATION OUTCOME, not the declared basis. Styling from
                # `basis` alone meant a transition whose quote failed the
                # verbatim check still drew a solid gold "grounded" arrow, a few
                # hundred pixels above its own citation card reading ✗
                # UNVERIFIED. The banner and the stamps were honest about a
                # forced page; the diagram was the one element still claiming
                # everything was fine.
                "verified": ex.get("verified", True),
            })

    _assign_lanes(nodes, edges)
    _assign_ports(nodes, edges)
    return nodes, edges


def _assign_lanes(nodes, edges):
    """Give every gutter edge the innermost lane that no overlapping edge holds.

    Shortest span first, so a one-step hop stays tight against the boxes and the
    long loop-back rides the outside. Reversing that put a five-step back-edge
    in lane 0 and pushed every short hop out past it, which reads as though the
    long edge were the ordinary case.
    """
    import heapq

    gutter = [e for e in edges if e["kind"] in ("back", "skip", "self")]
    # `broken` and `out` edges have no target node, so they never claim a lane.

    def span(e):
        ys = [nodes[e["from"]]["y"], nodes[e["to"]]["y"]]
        return min(ys) - 6, max(ys) + BOX_H + 6

    # Interval-graph colouring by sweep. The previous version scanned every
    # already-open lane for each edge, which is O(E x lanes) — and lanes grow
    # toward E whenever spans overlap heavily, so it was quadratic in practice.
    # A primer of 100 steps with 20 exits each all pointing at one common step
    # (a completely ordinary "and here is where it can bail out early" shape,
    # and one that VERIFIES CLEANLY) took 1.2s to lay out and produced a
    # 59,000px-wide, 1MB inline SVG; 10,000 edges took forty seconds. No
    # `--force` involved, and no subprocess in rules_cli.py passes a timeout.
    #
    # Sorting by span start and keeping freed lanes in a heap gives the same
    # assignment in O(E log E). Ties break on the SHORTEST span first, which
    # preserves the property the old comment describes: a one-step hop stays
    # tight against the boxes and the long loop-back rides the outside,
    # because reversing that reads as though the long edge were the ordinary case.
    ordered = sorted(gutter, key=lambda e: (span(e)[0], span(e)[1] - span(e)[0]))
    free = []          # lanes released, smallest index first
    active = []        # (bottom, lane) of lanes still occupied
    next_lane = 0
    for e in ordered:
        top, bot = span(e)
        while active and active[0][0] < top:
            heapq.heappush(free, heapq.heappop(active)[1])
        if free:
            lane = heapq.heappop(free)
        else:
            lane, next_lane = next_lane, next_lane + 1
        e["lane"] = lane
        heapq.heappush(active, (bot, lane))
    for e in edges:
        e.setdefault("lane", 0)


def _assign_ports(nodes, edges):
    """Space every connection evenly along the right edge of the box it touches.

    Three back-edges arriving at Finalize all landed on the same point, so the
    arrowheads stacked and the picture said "something comes back here" without
    saying how many things. Each endpoint now gets its own slot, ordered by lane
    so the lines do not cross each other on the way in.
    """
    touching = {i: [] for i in range(len(nodes))}
    for e in edges:
        if e["kind"] in ("back", "skip", "self"):
            touching[e["from"]].append((e, "src"))
            touching[e["to"]].append((e, "dst"))
        elif e["kind"] == "out":
            touching[e["from"]].append((e, "src"))

    for i, items in touching.items():
        # Sorted by lane, and by edge number to break the tie a self-edge
        # creates by occupying two slots on the same box with the same lane.
        # Python's sort is stable, so the self-edge's source stays above its
        # target and the lobe cannot render inside out.
        items.sort(key=lambda t: (t[0]["lane"], t[0]["n"]))
        count = len(items)
        for k, (e, role) in enumerate(items):
            # Widened from 0.24-0.76. A hub step can carry a dozen
            # connections, and the old span put them under 2px apart with
            # 7px arrowheads — the stacking this function exists to stop.
            # Density past what even this span can separate is refused
            # upstream by MAX_TRANSITIONS rather than drawn badly.
            frac = 0.5 if count == 1 else 0.14 + 0.72 * k / (count - 1)
            e["y_" + role] = nodes[i]["y"] + BOX_H * frac


def _clip_path(height):
    """The geometric backstop on the label estimate.

    One clip region serves every box: they share an x range and differ only in
    y, so a single full-height rect cuts each label at the same right edge. If
    the width estimate above is ever wrong — a font the reader has that the
    measurement did not — the heading is cut at the box rather than running out
    across the transition arrows.
    """
    return (f'<clipPath id="fg-box" clipPathUnits="userSpaceOnUse">'
            f'<rect x="0" y="0" width="{BOX_W - 8}" height="{height}"/></clipPath>')


def _badge(x, y, n, colour, failed=False):
    """The edge number, as a tag the eye can find against a line.

    Sized to its digits. At a fixed 18px the second digit of every transition
    past nine sat on the border — first noticed on paper, where the box prints
    as a hairline rule and the clipping is unmistakable.
    """
    w = 18 if len(str(n)) < 2 else 11 + 7 * len(str(n))
    # A failed edge's number inverts to solid Mist on Ink, exactly as the ✗
    # UNVERIFIED citation stamp does — the same signal in the same visual
    # language, so a reader who has met one recognises the other.
    fill = colour if failed else "var(--well)"
    ink = "var(--ink-900)" if failed else colour
    return (f'<g class="fg-badge"><rect x="{x - w / 2:.1f}" y="{y - 8:.1f}" width="{w}" '
            f'height="16" fill="{fill}" stroke="{colour}" stroke-width="1"/>'
            f'<text x="{x:.1f}" y="{y + 3.5:.1f}" text-anchor="middle" '
            f'class="fg-num" fill="{ink}">{n}</text></g>')


def svg(steps, label="Procedure"):
    """The whole graph as one inline <svg>, or "" when there is nothing to draw.

    Returns markup only — no file, no network, no script. The report embeds it
    directly, so it survives being emailed, printed, or opened from a USB stick
    with the wifi off, which is the environment a judge actually has.
    """
    nodes, edges = build(steps)
    # No transitions means no shape to show. A column of boxes with nothing
    # between them tells a reader strictly less than the numbered list of the
    # same headings already sitting in the rail, so the section is omitted
    # entirely rather than rendered empty — a linear primer is a legitimate
    # document, not a procedure missing its arrows.
    if not nodes or not any(e["kind"] != "broken" for e in edges):
        return ""

    lanes = max([e["lane"] for e in edges if e["kind"] in ("back", "skip", "self")] or [-1]) + 1
    has_out = any(e["kind"] == "out" for e in edges)
    gutter = LANE_X0 + lanes * LANE_W
    width = BOX_W + gutter + (TERMINAL_W if has_out else 12)
    height = PAD_Y * 2 + len(nodes) * BOX_H + (len(nodes) - 1) * GAP

    out = []
    for node in nodes:
        y = node["y"]
        colour = EDGE_COLOUR.get(node["basis"], "var(--slate-300)")
        out.append(
            f'<g class="fg-node">'
            f'<rect x="0.5" y="{y + 0.5:.1f}" width="{BOX_W - 1}" height="{BOX_H - 1}" '
            f'fill="var(--well)" stroke="var(--rule)" stroke-width="1"/>'
            f'<rect x="0.5" y="{y + 0.5:.1f}" width="3" height="{BOX_H - 1}" fill="{colour}"/>'
            # The step number, so a box on the map and a plate in the prose are
            # obviously the same thing. Without it the only correspondence was
            # the heading text, which the map has to clip.
            f'<text x="{PAD_X}" y="{y + BOX_H / 2 + 4:.1f}" class="fg-idx" '
            f'fill="{colour}">{node["index"] + 1}</text>'
            f'<text x="{PAD_X + 20}" y="{y + BOX_H / 2 + 4:.1f}" class="fg-step" '
            f'clip-path="url(#fg-box)">'
            f'{_esc(_clip(node["heading"], BOX_W - PAD_X - 34))}</text>'
            f'<title>{node["index"] + 1}. {_esc(node["heading"])}</title></g>')

    for e in sorted(edges, key=lambda e: e["n"]):
        if e["kind"] != "broken":
            out.append(_edge_svg(e, nodes, gutter, has_out))

    # `role="img"` with a real description, because the SVG is a summary of the
    # numbered transitions written out in full beneath it — a reader using a
    # screen reader gets the authoritative version either way, and a caption
    # that merely said "diagram" would have been worse than none.
    # Counts what is DRAWN. A transition whose goto names no step keeps its
    # number but cannot be placed, and the description went on counting it — so
    # a reader using a screen reader was told about an arrow nobody can see,
    # while the caption beside it still claimed every transition is on the map.
    drawn = [e for e in edges if e["kind"] != "broken"]
    desc = (f'{len(nodes)} steps and {len(drawn)} transitions; '
            "each transition is numbered and cited in the text below.")
    if len(drawn) != len(edges):
        desc += (f' {len(edges) - len(drawn)} further transition(s) could not be '
                 "drawn because they name no step — see Verification problems.")
    return (
        f'<svg class="flowgraph" viewBox="0 0 {width} {height}" width="{width}" '
        f'height="{height}" role="img" aria-label="{_esc(label)}: {_esc(desc)}" '
        f'preserveAspectRatio="xMinYMin meet">'
        f'<title>{_esc(label)}</title><desc>{_esc(desc)}</desc>'
        f'<defs>{_ARROWS}{_clip_path(height)}</defs>' + "".join(out) + "</svg>")


def _edge_svg(e, nodes, gutter, has_out):
    failed = not e.get("verified", True)
    colour = ("var(--mist-100)" if failed
              else EDGE_COLOUR.get(e["basis"], "var(--slate-300)"))
    src = nodes[e["from"]]
    # A failed edge is drawn heavier and in long dashes, so it separates from
    # every basis style in colour AND in weight AND in rhythm.
    dash = (' stroke-dasharray="9 4"' if failed
            else "" if e["basis"] == "grounded" else ' stroke-dasharray="4 3"')
    head = f'#fg-head-{"unverified" if failed else _key(e["basis"])}'
    title = f'<title>{_esc(str(e["n"]) + ". " + e["when"])}</title>'

    if e["kind"] == "next":
        # The fall-through case is the spine itself: straight down the middle,
        # between the two boxes it joins.
        x = BOX_W / 2
        y0, y1 = src["y"] + BOX_H, nodes[e["to"]]["y"]
        return (f'<g class="fg-edge">{title}'
                f'<line x1="{x}" y1="{y0}" x2="{x}" y2="{y1 - 7:.1f}" stroke="{colour}" '
                f'stroke-width="{2.4 if failed else 1.6}"{dash} marker-end="url({head})"/>'
                f'{_badge(x + 22, (y0 + y1) / 2, e["n"], colour, failed)}</g>')

    if e["kind"] == "out":
        # Leaving the procedure. Drawn past the last lane so it cannot be
        # mistaken for a transition to a step further down.
        y = e["y_src"]
        x0, x1 = BOX_W, BOX_W + gutter + 46
        return (f'<g class="fg-edge">{title}'
                f'<line x1="{x0}" y1="{y}" x2="{x1:.1f}" y2="{y}" stroke="{colour}" '
                f'stroke-width="{2.4 if failed else 1.6}"{dash} marker-end="url({head})"/>'
                f'<text x="{x1 + 8:.1f}" y="{y + 3.5:.1f}" class="fg-out" fill="{colour}">'
                f'exits</text>'
                f'{_badge((x0 + x1) / 2, y - 11, e["n"], colour, failed)}</g>')

    lane_x = BOX_W + LANE_X0 + e["lane"] * LANE_W
    if e["kind"] == "self":
        # A step that sends you back to itself. Drawn as a closed lobe rather
        # than an arc between two points, because the two points are the same.
        y0, y1 = e["y_src"], e["y_dst"]
        # Pushed past its lane rather than sitting in it. A lobe that shares a
        # lane with the back-edges arriving at the same box put its badge in the
        # middle of their arrowheads, and the tightest cluster on the diagram
        # was the one place a reader most needs to count the arrows.
        lobe = lane_x + 10
        d = (f"M{BOX_W} {y0:.1f} C{lobe} {y0 - 10:.1f} {lobe} {y1 + 10:.1f} "
             f"{BOX_W + 7} {y1:.1f}")
        return (f'<g class="fg-edge">{title}'
                f'<path d="{d}" fill="none" stroke="{colour}" stroke-width="{2.4 if failed else 1.6}"{dash} '
                f'marker-end="url({head})"/>'
                f'{_badge(lobe + 12, src["y"] + BOX_H / 2, e["n"], colour, failed)}</g>')

    # A back-edge or a forward skip: out to the lane, along it, back in.
    up = e["kind"] == "back"
    y0, y1 = e["y_src"], e["y_dst"]
    d = (f"M{BOX_W} {y0:.1f} C{lane_x} {y0:.1f} {lane_x} {y0:.1f} {lane_x} "
         f"{y0 + (-14 if up else 14):.1f} L{lane_x} {y1 + (14 if up else -14):.1f} "
         f"C{lane_x} {y1:.1f} {lane_x} {y1:.1f} {BOX_W + 7} {y1:.1f}")
    return (f'<g class="fg-edge">{title}'
            f'<path d="{d}" fill="none" stroke="{colour}" stroke-width="{2.4 if failed else 1.6}"{dash} '
            f'marker-end="url({head})"/>'
            f'{_badge(lane_x, (y0 + y1) / 2, e["n"], colour, failed)}</g>')


def _key(basis):
    return "structural" if basis in ("structural", "inferred") else (
        basis if basis in EDGE_COLOUR else "gap")


# One marker per basis colour: SVG markers cannot inherit `stroke` from the path
# that uses them, so a single shared arrowhead drew every edge's tip gold —
# including the grey ones the page had just called unsettled.
_ARROWS = "".join(
    f'<marker id="fg-head-{k}" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" '
    f'markerHeight="7" orient="auto-start-reverse">'
    f'<path d="M0 0 L8 4 L0 8 Z" fill="{v}"/></marker>'
    for k, v in (("grounded", EDGE_COLOUR["grounded"]),
                 ("structural", EDGE_COLOUR["structural"]),
                 ("gap", EDGE_COLOUR["gap"]),
                 ("unverified", EDGE_COLOUR["unverified"]))
)


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def mermaid(steps, topic="Procedure"):
    """The same graph as Mermaid source, for tools that want to restyle it.

    Emitted by `rules_cli.py graph` so the website and any diagramming pass work
    from the verified transitions rather than from a fresh reading of the prose.
    Node ids are the step ids, so a diff of this file after a rules update names
    the transition that moved.

    Every label is escaped. The SVG above is emitted straight into a page that
    escapes for HTML, but this export leaves the project entirely — and Mermaid
    renders labels as HTML by default, so an unescaped `<` in a step heading is
    markup wherever the graph is finally drawn.
    """
    nodes, edges = build(steps)
    # `_mid` maps every non-alphanumeric character to "_", so it is not
    # injective: `s1.a` and `s1_a` both became S_s1_a, silently collapsing two
    # declared steps into one node and turning the transition between them into
    # a self-loop — in the export that exists so a diagram cannot outrun its
    # citations. Verification cannot see it, because the JSON ids ARE unique.
    # Disambiguated here, where every id is in hand.
    ids, seen = {}, {}
    for node in nodes:
        base = _mid(node["id"])
        seen[base] = seen.get(base, 0) + 1
        ids[node["id"]] = base if seen[base] == 1 else f"{base}__{seen[base]}"
    lines = [f"%% {_mlabel(topic)} — derived from verified transitions; do not hand-edit",
             "flowchart TD"]
    for node in nodes:
        lines.append(f'  {ids[node["id"]]}["{_mlabel(node["heading"])}"]')
    if any(e["kind"] == "out" for e in edges):
        lines.append('  DONE(["procedure ends"])')
    for e in sorted(edges, key=lambda e: e["n"]):
        if e["kind"] == "broken":
            continue
        target = "DONE" if e["to"] is None else ids[nodes[e["to"]]["id"]]
        arrow = "-->" if e["basis"] == "grounded" else "-.->"
        lines.append(f'  {ids[nodes[e["from"]]["id"]]} {arrow}'
                     f'|"{e["n"]}. {_mlabel(e["when"])}"| {target}')
    return "\n".join(lines) + "\n"


def _mid(step_id):
    """A Mermaid-safe node id."""
    return "S_" + "".join(ch if ch.isalnum() else "_" for ch in str(step_id))


# Mermaid's own escape syntax: `#` plus an entity name or code, then `;`. It
# survives both the parser and the HTML label renderer, which a bare character
# reference does not.
#
# `#` is in the table because it introduces the escape — leaving it out makes
# every other substitution ambiguous with text the author actually wrote. The
# rest are the characters that mean something structurally: `"` closes a quoted
# label, `|` delimits an edge label, and `<>&` are markup once Mermaid renders
# the label as HTML.
_MERMAID_ESCAPES = {
    "#": "#35;", '"': "#quot;", "<": "#lt;", ">": "#gt;", "&": "#amp;", "|": "#124;",
}


def _mlabel(text):
    """One line of escaped label text, safe inside a quoted Mermaid label.

    Whitespace is collapsed first: a newline inside a heading or a `when` would
    otherwise end the statement early and silently truncate the graph, which is
    the one failure that would leave a *plausible* diagram behind.
    """
    return "".join(_MERMAID_ESCAPES.get(ch, ch)
                   for ch in " ".join(str(text).split()))

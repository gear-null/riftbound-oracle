"""Emit a primer's step graph as Fireworks Tech Graph IR — derived, never authored.

Fireworks renders technical diagrams far better than anything this project is
going to write, and the reason it is safe to use is that it accepts a
**structured document**, not a prompt. `fireworks.py render architecture ir.json
out.svg` takes nodes and arrows and draws them. So the IR below is computed from
`flowgraph.build` — the same verified transitions the in-report map is drawn
from — and no natural-language description of the procedure is ever handed to
anything. A prompt would put a model back in charge of the arrows, which is
precisely what invariant 12 exists to prevent.

Division of labour:

    flowgraph.build   the graph: which steps, which transitions, what basis
    this module       that graph as Fireworks IR, plus the vertical layout
    Fireworks         routing, typography, markers, the visual language

Fireworks routes better than a hand-rolled router and is worth deferring to. It
is NOT given `route_points` except for a self-return, which has no direct path
to hang a label on and would otherwise be refused with "no collision-free label
position".

**The IR is the artifact this project stands behind; rendering it is optional.**
Fireworks lives outside the skill folder, and ADR 0004 says nothing in the
skill may depend on anything outside it. So `rules_cli.py graph` always writes
the IR — self-contained, checkable, diffable — and renders an SVG only if a
Fireworks install can be found. A missing install costs you a picture, never an
answer.

Style 3 (Blueprint) is the chosen skin: a blue-black ground with cyan rules,
the closest renderable match to the report's own Runeterra palette. Style 8
(Dark Luxury, gold on black) is closer still and cannot be used — Fireworks
refuses to render it from IR and asks for a hand-crafted SVG instead, which
would hand the drawing back to a model.
"""
import flowgraph

# Fireworks names its edge classes by role — control / read / neutral — and
# gives each its own colour and marker. This project names them by basis. The
# map is total over RANK's vocabulary, and `unverified` is not a basis: it is
# what an edge becomes when its citation fails, and it takes the strongest
# signal Fireworks has.
FLOW_FOR_BASIS = {
    "grounded": "control",
    "structural": "read",
    "inferred": "read",
    "gap": "neutral",
}
FLOW_UNVERIFIED = "feedback"

STYLE_BLUEPRINT = 3

# Layout. Fireworks wants explicit node geometry and routes between it, so the
# spine is ours and the wiring is theirs. Roomier than the in-report map
# because this artifact is a standalone page, not a column beside prose.
BOX_W = 320
BOX_H = 72
GAP = 132
PAD_X = 96
PAD_Y = 132
END_W = 210
END_GAP = 520


def _legend(edges):
    """Only the edge classes this diagram actually uses.

    Same rule as the report's basis key: a legend row for a style that does not
    appear on the page is a line the reader has to hold for nothing.
    """
    rows = [
        ("control", "a rule states this outright"),
        ("read", "follows from the rules cited"),
        ("neutral", "the rules do not settle it"),
        (FLOW_UNVERIFIED, "FAILED VERIFICATION — do not rely on this"),
    ]
    used = {_flow(e) for e in edges if e["kind"] != "broken"}
    return [{"flow": flow, "label": label} for flow, label in rows if flow in used]


def _flow(edge):
    if not edge.get("verified", True):
        return FLOW_UNVERIFIED
    return FLOW_FOR_BASIS.get(edge["basis"], "neutral")


def build(ans, style=STYLE_BLUEPRINT):
    """The primer as Fireworks IR. Reads `steps` and nothing else.

    `ans` must already have been through `verify_primer`, so `exits[].verified`
    is set — `rules_cli.py graph` refuses on a primer with problems, which is
    what keeps a diagram from travelling further than its citations.
    """
    steps = ans.get("steps") or []
    nodes, edges = flowgraph.build(steps)
    drawn = [e for e in edges if e["kind"] != "broken"]

    def y_of(index):
        return PAD_Y + index * (BOX_H + GAP)

    ir_nodes = [
        {
            "id": node["id"],
            "kind": "rect",
            "x": PAD_X,
            "y": y_of(node["index"]),
            "width": BOX_W,
            "height": BOX_H,
            "type_label": f'STEP {node["index"] + 1}',
            "label": node["heading"],
        }
        for node in nodes
    ]

    # The exit node's id must not be one a step already uses. `__procedure_ends`
    # is unlikely, not impossible, and a primer declaring it produced an IR with
    # two nodes sharing an id — which verified clean, because the collision is
    # created HERE and not in the document. Same failure as `_mid` collapsing
    # two step ids in the mermaid export, in the other direction.
    end_id = _END_ID
    taken = {node["id"] for node in nodes}
    while end_id in taken:
        end_id += "_"

    end_x = PAD_X + BOX_W + END_GAP
    leaves = any(e["kind"] == "out" for e in drawn)
    if leaves:
        # Opposite the MIDDLE of the spine. Hung off the last step, the first
        # step's exit arrow travelled the whole height of the page to reach it.
        middle = y_of((len(nodes) - 1) / 2.0) if nodes else PAD_Y
        ir_nodes.append({
            "id": end_id, "kind": "rect", "x": end_x, "y": int(middle),
            "width": END_W, "height": BOX_H,
            "type_label": "EXIT", "label": "procedure ends",
        })

    ir_arrows = []
    for edge in sorted(drawn, key=lambda e: e["n"]):
        arrow = {
            "id": f't{edge["n"]}',
            "source": nodes[edge["from"]]["id"],
            "target": end_id if edge["to"] is None else nodes[edge["to"]]["id"],
            "flow": _flow(edge),
            "label": str(edge["n"]),
        }
        if edge["kind"] == "self":
            # The one place Fireworks needs help. A self-return's direct path is
            # zero-length, so its router finds no segment long enough to carry a
            # label and refuses the whole diagram. An explicit lobe gives it one.
            top = y_of(edge["from"])
            arrow["source_port"] = arrow["target_port"] = "right"
            arrow["route_points"] = [
                [PAD_X + BOX_W + 90, int(top + 18)],
                [PAD_X + BOX_W + 90, int(top + BOX_H - 18)],
            ]
        ir_arrows.append(arrow)

    return {
        "schema_version": 1,
        "mode": "architecture",
        "template_type": "flowchart",
        "style": style,
        # Fireworks' showcase contract assumes an architecture diagram: few
        # edges, short routes, no crossings. A procedure is not that shape —
        # twelve transitions over five steps cross each other by nature, and a
        # self-return's "route stretch" is its length divided by a direct
        # distance of zero, a number that means nothing. Raised deliberately,
        # and only these two: bends, spacing and label clearance still apply.
        "quality_profile": {
            "profile": "standard",
            "max_route_stretch": 60.0,
            "max_bridged_crossings": 40,
        },
        "width": int(end_x + END_W + 60) if leaves else int(PAD_X * 2 + BOX_W + 420),
        "height": int(y_of(max(len(nodes) - 1, 0)) + BOX_H + PAD_Y),
        "title": ans.get("topic", "Procedure"),
        "subtitle": _subtitle(ans),
        "nodes": ir_nodes,
        "arrows": ir_arrows,
        "legend": _legend(edges),
    }


_END_ID = "__procedure_ends"


def _subtitle(ans):
    """Says what the picture is derived from, on the picture.

    This artifact travels — to a website, into a deck, onto a phone — away from
    the report that carries the citations. The one thing it must take with it is
    that it was derived rather than drawn, and which corpus it was derived from.
    """
    corpus = ans.get("corpus") or {}
    version = corpus.get("CR")
    stamp = f" · Comprehensive Rules {version}" if version else ""
    return ("derived from the transitions this primer declares"
            f"{stamp} · unofficial")

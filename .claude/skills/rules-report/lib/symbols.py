"""Riftbound's written shorthand — [A], [M], [R] — derived from the rules.

Rules text is dense with bracketed shorthand. `[E]: Add [Y].` is unreadable
until you know that E is exhaust and Y is Order, and a reader meeting it cold
has no way in.

The legend is DERIVED from the corpus rather than hardcoded, for the same
reason everything else here is: a hand-written table is a second source of
truth that silently rots. Riot defines each shorthand in the rules themselves —
CR 134.2 for the six domains, CR 135.2.e for the rest — so this parses those
rules and every legend entry can cite the rule that defines it. Add a domain,
renumber a section, and the legend follows automatically.

The literal shorthand is deliberately NOT replaced with glyphs. The goal is a
reader who learns to read `[A]` plainly; substituting a symbol would make the
report legible while leaving Riot's actual PDFs no easier to read.
"""
import re

# "Fury is associated with the color red and ... Its shorthand is [R]."
DOMAIN_RE = re.compile(
    r"^(?P<name>[A-Z][a-z]+) is associated with the color (?P<colour>[a-z]+).*?"
    r"shorthand is \[(?P<token>[^\]]+)\]",
    re.S,
)

# "Might is represented by the ... Its shorthand is [M]."
SYMBOL_RE = re.compile(r"shorthand is \[(?P<token>[^\]]+)\]")

# Rules text colour names -> something that stays legible on both themes.
# Riot's own colour per CR 134.2; the hex is a readable rendering of it, not a
# brand value, and it is only ever used to tint a one-character label.
COLOUR = {
    "red": "#d0453e", "green": "#3f8f4f", "blue": "#3b6fb5",
    "orange": "#c2762a", "purple": "#8257b8", "yellow": "#b08908",
}


def _first_sentence(text):
    m = re.match(r"\s*(.+?\.)(?:\s|$)", text)
    return (m.group(1) if m else text).strip()


def build_legend(rules):
    """token -> {meaning, rule, colour}. Keyed without the brackets."""
    by_id = {r["id"]: r for r in rules if r["doc"] == "CR"}
    legend = {}

    # Six domains: CR 134.2.a .. 134.2.f
    for rid, rule in by_id.items():
        if not rid.startswith("134.2."):
            continue
        m = DOMAIN_RE.match(rule["text"].strip())
        if m:
            legend[m.group("token")] = {
                "meaning": f'Power of {m.group("name")} ({m.group("colour")})',
                "rule": rid,
                "colour": COLOUR.get(m.group("colour")),
            }

    # Everything else: CR 135.2.e.*
    described = {
        "E": "Exhaust this permanent (a cost)",
        "M": "Might",
        "A": "Power of any Domain",
        "C": "Power of this card's own Domain",
        ">": "Marks the ability a keyword modifies",
    }
    for rid, rule in by_id.items():
        if not rid.startswith("135.2.e."):
            continue
        m = SYMBOL_RE.search(rule["text"])
        if not m:
            continue
        token = m.group("token")
        legend.setdefault(token, {
            "meaning": described.get(token) or _first_sentence(rule["text"]),
            "rule": rid,
            "colour": None,
        })
    # 135.2.e.7 states the [>] rule without the words "shorthand is".
    if "135.2.e.7" in by_id:
        legend.setdefault(">", {
            "meaning": described[">"], "rule": "135.2.e.7", "colour": None,
        })

    return legend


# A bare number in brackets is an Energy amount — CR 429.5: '"Add [2]." means
# "Add 2 Energy."' Matched separately since the amount varies.
NUMBER_RULE = "429.5"


def is_number_token(token):
    return token.isdigit()


TOKEN_RE = re.compile(r"\[([^\]\[]{1,3})\]")


def scan(text, legend):
    """Which shorthand tokens appear in this text.

    Deliberately narrow: only tokens already in the legend, plus bare numbers.
    Rules text is also full of bracketed prose — [Warning], [do X], [Reaction] —
    and glossing those as symbols would turn a helpful key into noise.
    """
    used = set()
    for token in TOKEN_RE.findall(text or ""):
        if token in legend or is_number_token(token):
            used.add(token)
    return used

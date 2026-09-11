#!/usr/bin/env python3
"""What Riftbound's card text actually says, counted — the pre-step to a DSL.

Issue #26 wants a card-script DSL whose vocabulary is *closed and small*, and
the plan (§4.3) puts numbers on "small": ~50-90 effect primitives, 25-40 trigger
events, under 10 replacement kinds. Those targets are borrowed from Forge, which
covers 33,697 MTG cards with ~206 primitives. Borrowed numbers are a hypothesis,
not a measurement, and the plan says so: derive the vocabulary *empirically
first*, before freezing anything.

This script is that measurement. It splits every card's printed text into
clauses and classifies each clause, so the vocabulary can be read off counts
instead of guessed from a sample someone happened to look at.

Three properties make the number trustworthy enough to size a DSL with:

1.  **Nothing is dropped.** A clause that matches no pattern lands in an
    explicit `unclassified` bucket *with its text*, and the report prints them.
    A classifier with a silent fallback reports whatever coverage you want.

2.  **Two numbers, not one.** "Clause classified" is the weak claim: a clause
    reading "draw 1 and give a unit +2 {M}" is "classified" the moment `draw`
    matches, with half its meaning unexamined. So the report also carries a
    RESIDUE audit — the content words in effect clauses that no pattern
    accounts for. Coverage that looks complete while the residue is large means
    the splitter is too coarse, not that the vocabulary is done.

3.  **The field is named.** Gauntlet counts are quoted with the gauntlet's
    version and content digest, because "396 cards" means nothing once someone
    re-pulls the field.

Pure stdlib, Python 3.9+. It reads the deck-lab skill's vendored card data and
imports the skill's own deck loader so that the card set it measures is exactly
the one `deck_cli.py gauntlet` reports. It writes nothing anywhere.

    python3 engine-train/census.py                # human-readable report
    python3 engine-train/census.py --markdown     # the tables, for docs/
    python3 engine-train/census.py --audit        # unclassified + residue only
    python3 engine-train/census.py --json out.json
"""
import argparse
import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SKILL = os.path.join(REPO, ".claude", "skills", "deck-lab")
LIB = os.path.join(SKILL, "lib")
CARDS_JSON = os.path.join(SKILL, "data", "cards.json")


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_pool():
    """{canonical name: record} for every distinct card, errata already applied.

    `cards.json` is keyed by lookup alias, so it holds 1,037 keys for 954 cards;
    collapsing on the record's own `name` is what makes a per-card count a count
    of cards. The `errata` field is a provenance marker — the pipeline has
    already replaced the text with Riot's corrected wording — so reading `text`
    here *is* reading errata'd text, which is what #26 asks for.
    """
    with open(CARDS_JSON, encoding="utf-8") as fh:
        raw = json.load(fh)
    pool = {}
    for entry in raw.values():
        pool[entry["name"]] = entry
    return pool, raw


def load_gauntlet():
    """(card names, version, digest) for the gauntlet, via the skill's own loader.

    Re-implementing the name resolution here would be a second source of truth
    that drifts: the gauntlet's lists spell champions `Master Yi, Wuju
    Bladesman` where the card data spells them `Master Yi - Wuju Bladesman`, and
    a census that resolved 390 of 396 would look like a census of 390 cards.
    Importing is read-only and bytecode is suppressed, so the skill folder is
    not touched.

    Raises rather than falling back to "all cards": a census that quietly
    measured the whole pool while its heading said "gauntlet" is exactly the
    kind of wrong number this file exists to avoid.
    """
    sys.dont_write_bytecode = True
    if LIB not in sys.path:
        sys.path.insert(0, LIB)
    import deckfile  # noqa: E402  (deliberately late; see docstring)

    decks = [deckfile.load(p) for p in deckfile.gauntlet_paths()]
    if not decks:
        raise SystemExit("no gauntlet lists found under %s" % SKILL)
    return (
        deckfile.distinct_cards(decks),
        deckfile.gauntlet_version(),
        deckfile.gauntlet_digest(),
        len(decks),
    )


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------
#
# Two notations reach this script for the same symbols. Riftcodex sends
# `:rb_energy_1::rb_rune_chaos:`; Riot's errata articles print `[1][P]` for the
# identical cost (see src/errata.ts). Sixty-three records carry the errata
# notation, so a classifier that knew only one of them would mis-read the
# corrected text of exactly the cards whose text most recently changed.
#
# Both fold to one brace form, taken from the shorthand the rules themselves
# define: CR 134.2 for the six domains, CR 135.2.e for the rest.

DOMAIN_SHORTHAND = {
    "fury": "R", "calm": "G", "mind": "B",
    "body": "O", "chaos": "P", "order": "Y",
}

#: Tokens the corpus prints in brackets that are SYMBOLS, not keywords.
#: `[S]` is Might's retired shorthand (CR 135.2.e.3 names it as previous rules
#: information); one card still carries it, and reading it as a keyword would
#: invent a keyword that does not exist.
SYMBOL_BRACKETS = {
    "M": "M", "A": "A", "C": "C", "E": "E", "S": "M",
    "R": "R", "G": "G", "B": "B", "O": "O", "P": "P", "Y": "Y",
    ">": ">", ">>": ">>",
}

#: The 25 keywords of CR 805-829, verbatim. Anything else in brackets is a game
#: action the corpus has set in the symbol font (`[Add]`, `[Stun]`, `[Burn 3]`)
#: or a state with no CR entry (`[Mighty]`) — both are reported separately,
#: because "how many keywords are there" must not be answered by counting
#: brackets.
#: `{name: (CR section, what kind of ability the rules say it is)}`. The kind
#: is quoted from each section's own first line, and it is the bridge from
#: keyword to DSL construct: a Triggered Ability keyword IS a trigger, so a card
#: with `[Deathknell]` and a `When I conquer` line has two triggers, not one —
#: which is the question #26 asks in "how many cards have more than one
#: trigger".
KEYWORD_KIND = {
    "Accelerate":   ("805", "optional additional cost (unit ability)"),
    "Action":       ("806", "permissive"),
    "Assault":      ("807", "passive"),
    "Deathknell":   ("808", "triggered"),
    "Deflect":      ("809", "passive"),
    "Ganking":      ("810", "passive"),
    "Hidden":       ("811", "action prerequisite"),
    "Legion":       ("812", "dependent"),
    "Reaction":     ("813", "permissive"),
    "Shield":       ("814", "passive"),
    "Tank":         ("815", "passive"),
    "Temporary":    ("816", "triggered"),
    "Vision":       ("817", "triggered"),
    "Equip":        ("818", "activated"),
    "Quick-Draw":   ("819", "triggered + permissive"),
    "Repeat":       ("820", "optional additional cost"),
    "Weaponmaster": ("821", "triggered"),
    "Ambush":       ("822", "passive"),
    "Hunt":         ("823", "triggered"),
    "Level":        ("824", "dependent"),
    "Unique":       ("825", "deck constraint"),
    "Backline":     ("826", "passive"),
    "Empower":      ("827", "activated"),
    "Empowered":    ("828", "dependent"),
    "Flow":         ("829", "passive"),
}
CR_KEYWORDS = set(KEYWORD_KIND)
TRIGGERED_KEYWORDS = {k for k, v in KEYWORD_KIND.items() if "triggered" in v[1]}

#: Upstream serves reminder text butted against the next sentence with no
#: separator: `(Play on your turn or in showdowns.)Each player kills...`. The
#: deck-lab skill spaces `)`/`]` before a capital for DISPLAY and deliberately
#: keeps the data byte-identical. A parser needs more: `Draw 2.[Level 6][>]`
#: and `Draw 1.{4}{B}: Score 1 point` run a full stop into the next ability.
#: Widened here and only here — this is a reading of the text, not an edit of it.
_SEAMS = (
    (re.compile(r"([)\]])([A-Z(\[])"), r"\1 \2"),
    (re.compile(r"(\.)([A-Z(\[{])"), r"\1 \2"),
    (re.compile(r"(\})([A-Z])"), r"\1 \2"),
)


def normalise(text):
    """Printed text with one symbol notation and no run-together sentences."""
    t = text or ""
    t = re.sub(r":rb_energy_(\d+):", lambda m: "{%s}" % m.group(1), t)
    t = t.replace(":rb_might:", "{M}").replace(":rb_exhaust:", "{E}")
    t = t.replace(":rb_rune_rainbow:", "{A}")
    for domain, short in DOMAIN_SHORTHAND.items():
        t = t.replace(":rb_rune_%s:" % domain, "{%s}" % short)
    t = re.sub(r"\[(\d+)\]", lambda m: "{%s}" % m.group(1), t)
    t = re.sub(
        r"\[([^\]]{1,2})\]",
        lambda m: "{%s}" % SYMBOL_BRACKETS[m.group(1)]
        if m.group(1) in SYMBOL_BRACKETS else m.group(0),
        t,
    )
    t = t.replace("[ADD]", "[Add]")          # one card shouts it
    t = t.replace("’", "'")
    for pattern, repl in _SEAMS:
        t = pattern.sub(repl, t)
    return re.sub(r"\s+", " ", t).strip()


def split_reminder(text):
    """(rules text, [reminder spans]).

    CR 135.2.d.3: the presence, absence or exact wording of reminder text has no
    effect on game function. So it is removed before clauses are counted — left
    in, every `[Assault 2]` would contribute a phantom "+2 {M} while it's an
    attacker" clause and the primitive counts would measure Riot's editorial
    habits rather than the game.
    """
    out, reminders, depth, buf = [], [], 0, []
    for ch in text:
        if ch == "(":
            depth += 1
            if depth == 1:
                continue
        if depth:
            if ch == ")":
                depth -= 1
                if depth == 0:
                    reminders.append("".join(buf).strip())
                    buf = []
                    continue
            buf.append(ch)
        else:
            out.append(ch)
    body = re.sub(r"\s+", " ", "".join(out)).replace(" .", ".").strip()
    return body, reminders


# ---------------------------------------------------------------------------
# Segmentation
# ---------------------------------------------------------------------------

KEYWORD_TOKEN = re.compile(r"^\[([A-Z][A-Za-z'-]*)(?: (\d+))?\]")
ANY_BRACKET = re.compile(r"\[([A-Z][A-Za-z'-]*)(?: (\d+))?\]")
#: Riot's errata articles print keywords WITHOUT brackets — `Ganking (I can
#: move…)`, `Equip {O}`, `Action (Play on your turn…)`. Only accepted when what
#: follows is a cost, a dash or the end of the ability, because `Empower` and
#: `Predict` are game actions as well as keywords and `Empower me` is an
#: instruction, not a keyword reference.
BARE_KEYWORD = re.compile(
    r"^(Accelerate|Action|Assault|Deathknell|Deflect|Ganking|Hidden|Legion|"
    r"Reaction|Shield|Tank|Temporary|Vision|Equip|Quick-Draw|Repeat|"
    r"Weaponmaster|Ambush|Hunt|Level|Unique|Empowered|Backline|Flow)"
    r"(?: (\d+))?(?=\s*(?:\{|[-—]|$))"
)
#: An activated ability's cost, ending in the colon that introduces its effect:
#: `{E}:`, `{4}{B}{B}, {E}:`, `{1}{R}, Recycle a unit from your trash, {E}:`.
ACTIVATED = re.compile(r"^([^.:]{1,80}):\s")
#: One comma-separated piece of such a cost: a run of symbols, or a short
#: imperative used as a cost (`Kill this`, `Disempower me`).
_COST_PART = re.compile(r"^(?:\{[^}]*\}\s*)+$|^[A-Z][a-z]+\b[^,]{0,40}$")


def match_activated(text):
    """The cost header of an activated ability, or None.

    A colon is not enough on its own. `While you control this battlefield,
    friendly legends have "{E}: Attach an Equipment…"` contains a brace token
    and a colon, and an earlier version of this read the whole first half of
    that sentence as a cost — turning a passive into an activated ability and
    hiding its condition in the `unclassified` bucket. So every piece of the
    header has to look like a cost, and at least one has to be actual symbols.
    """
    m = ACTIVATED.match(text)
    if not m:
        return None
    parts = [p.strip() for p in m.group(1).split(",")]
    if not parts or not all(_COST_PART.match(p) for p in parts if p):
        return None
    if not any(re.match(r"^(?:\{[^}]*\}\s*)+$", p) for p in parts if p):
        return None
    return m

SENTENCE = re.compile(r"(?<=\.)\s+")

MODE_HEADER = re.compile(r"^Choose (one|two|three)\s*[-—]\s*", re.I)

#: Where one instruction ends and the next begins inside a sentence. Order
#: matters: the longest separator has to win, or `. Then do this: ` is split
#: twice and leaves an empty clause.
INSTRUCTION_SPLITS = [
    r"then do this:\s*",
    r"then you may do this:\s*",
    r"[,.]?\s*then,?\s+",
    r"otherwise,\s*",
    r";\s*",
]
_SPLIT_RE = re.compile("(?:%s)" % "|".join(INSTRUCTION_SPLITS), re.I)

#: A trigger condition runs from its opening word to the comma that closes it.
#: `While` is here because it is *shaped* like a trigger and must be separated
#: from its effect the same way — it is classified as an ongoing condition, not
#: a trigger, further down.
TRIGGER_HEAD = re.compile(
    r"^(When(?:ever)?\b|At\b|The (?:first|second|third|next|last)\b"
    r"|The \w+ time\b|Once each turn\b|\d+ times each turn\b|While\b"
    r"|Starting\b|After\b|Before\b|As you\b|As I\b|Each time\b)",
    re.I,
)

#: `and` joins two instructions only when what follows it starts like one. The
#: alternative — splitting on every `and` — cuts "Bird, Cat, Dog, and Poro" into
#: a clause, which is how a census invents primitives that are not there.
AND_SPLIT = re.compile(
    r"\s+and\s+(?=(?:\[|\{|"
    r"draw|give|buff|deal|kill|ready|exhaust|banish|channel|discard|recycle|"
    r"play|move|stun|heal|score|gain|add|return|reveal|counter|attach|detach|"
    r"create|burn|empower|disempower|skip|pay|spend|take|put|look|choose|hide|"
    r"predict|swap|double|prevent|replace|enter|can|cost|have|has|get|use)\b)",
    re.I,
)

#: A trailing `if …` / `unless …` is a gate on the instruction before it.
TRAILING_COND = re.compile(
    r",?\s+(?:even\s+)?(if\s+(?!you do\b).+|unless\s+.+)$", re.I)

#: CR 355.10.c.1's "[do X] to [do Y]": the cost inside an instruction. Split
#: only when what follows `to` is a BASE-FORM verb, so `move a friendly unit to
#: your base` and `return it to its owner's hand` keep their destinations and
#: only `exhaust me to channel 1 rune` is cut in two.
COST_TO = re.compile(
    r"\bto\s+(?=(?:draw|give|buff|deal|kill|ready|exhaust|banish|channel|"
    r"discard|recycle|play|move|stun|heal|score|gain|add|return|reveal|"
    r"counter|attach|detach|create|burn|empower|disempower|skip|pay|spend|"
    r"take|put|look|choose|hide|predict|swap|double|prevent|replace|recall|"
    r"use|copy|score)\b)",
    re.I,
)

#: What the text after a trigger's closing comma looks like when it is the
#: EFFECT rather than more of the condition. Base-form verbs only — `discard`
#: but not `discarded` — because the shape this exists to survive is
#: `When this is played, discarded, or killed, draw 1`, where the first comma
#: is inside the trigger and only the last one closes it.
INSTRUCTION_START = re.compile(
    r"^(?:if|unless|then|you|they|it|its|their|your|my|i|this|that|each|all|"
    r"any|every|other|another|friendly|enemy|opposing|both|the|an?|players?|"
    r"opponents?|units?|gears?|spells?|cards?|runes?|legends?|champions?|"
    r"draw|give|buff|deal|kill|ready|exhaust|banish|channel|discard|recycle|"
    r"play|move|stun|heal|score|gain|add|return|reveal|counter|attach|detach|"
    r"create|burn|empower|disempower|skip|pay|spend|take|put|look|choose|hide|"
    r"predict|swap|double|prevent|replace|enter|use|ignore|attack|defend|"
    r"conquer|hold|reduce|increase|set|copy|shuffle|search|activate)\b",
    re.I,
)

#: A comma that is still inside an enumeration, not the one that closes the
#: trigger: `When you play a unit, gear, or activated ability with …` and
#: `When this is played, discarded, or killed, …`. Without this the first
#: comma wins, the trigger loses two of its three events, and the rest of the
#: sentence is parsed as something it is not.
ENUMERATION_TAIL = re.compile(r"^(?:or\b|[\w'{}+ -]{1,32},\s*or\b)", re.I)


class Clause(object):
    """One clause, plus everything the classifier could say about it."""

    __slots__ = ("card", "text", "kind", "bucket", "selectors", "keywords",
                 "choices", "costs", "replacement", "duration", "for_each",
                 "gate", "residue")

    def __init__(self, card, text, kind="effect", gate=None):
        self.card = card
        self.text = text
        self.kind = kind
        self.bucket = []
        self.selectors = []
        self.keywords = []
        self.choices = []
        self.costs = []
        self.replacement = None
        self.duration = None
        self.for_each = False
        self.gate = gate
        self.residue = []


def segment(card_name, text):
    """Printed text -> clauses, in printed order.

    The four shapes a Riftbound card is built from, peeled in this order:
    a keyword reference (optionally carrying a cost and optionally gating what
    follows via `[>]` or an em dash), an activated ability's cost, a mode list,
    and plain sentences.
    """
    body, _ = split_reminder(normalise(text))
    clauses = []
    if not body:
        return clauses

    rest = body
    gate = None
    guard = 0
    while rest:
        guard += 1
        if guard > 200:                      # a malformed text must not hang
            clauses.append(Clause(card_name, rest, "unclassified"))
            break
        rest = rest.strip()
        if not rest:
            break

        m = KEYWORD_TOKEN.match(rest) or BARE_KEYWORD.match(rest)
        if m and m.group(1) not in CR_KEYWORDS:
            # Bracketed but not a keyword: the corpus sets game actions in the
            # symbol font too (`[Stun] a unit`, `[Add] {2}`, `[Burn 3]`). Peeling
            # those off as their own clause left `a unit` behind as a fragment
            # and invented a keyword that CR 805-829 does not list. Unbracket
            # and let it be read as the instruction it is.
            inner = m.group(1) + ((" " + m.group(2)) if m.group(2) else "")
            rest = inner + " " + rest[m.end():].lstrip()
            m = None
        if m:
            head = "[%s%s]" % (m.group(1),
                               (" " + m.group(2)) if m.group(2) else "")
            rest = rest[m.end():].lstrip()
            # A keyword may carry a cost: `[Empower] {3}{Y}`, `[Flow] {3}{R}`.
            # `{>}` is excluded: it is the binder of CR 135.2.e.7, and reading
            # it as a cost swallowed the binder, so `[Empowered]{>} I have +1
            # {M}` lost its gate and the ongoing-conditional passives the plan
            # specifically asks about counted as unconditional ones.
            cost = re.match(r"^((?:\{(?!>)[^}]*\}\s*)+)", rest)
            if cost:
                head += " " + cost.group(1).strip()
                rest = rest[cost.end():].lstrip()
            clause = Clause(card_name, head, "keyword", gate)
            clauses.append(clause)
            # `[>]` (CR 135.2.e.7) and the em dash both bind the keyword to the
            # ability that follows it. Everything up to the end of the next
            # sentence is that ability.
            bound = re.match(r"^(?:\{>+\}|[-—])\s*", rest)
            if bound:
                rest = rest[bound.end():].lstrip()
                gate = m.group(1) + ((" " + m.group(2)) if m.group(2) else "")
            continue

        m = match_activated(rest)
        if m:
            for part in m.group(1).split(","):
                part = part.strip()
                if part:
                    clauses.append(Clause(card_name, part, "cost", gate))
            rest = rest[m.end():].lstrip()
            continue

        m = MODE_HEADER.match(rest)
        if m:
            clauses.append(Clause(card_name, m.group(0).strip(), "mode", gate))
            rest = rest[m.end():].lstrip()
            continue

        parts = SENTENCE.split(rest, 1)
        sentence = parts[0]
        rest = parts[1] if len(parts) > 1 else ""
        clauses.extend(split_sentence(card_name, sentence, gate))
        gate = None                          # a gate reaches one ability only
    return clauses


def split_sentence(card_name, sentence, gate):
    """One sentence -> its trigger, its conditions and its instructions."""
    out = []
    s = sentence.strip()
    if not s:
        return out

    m = TRIGGER_HEAD.match(s)
    if m:
        head, tail = _split_on_condition_comma(s)
        kind = "condition" if re.match(r"^While\b", head, re.I) else "trigger"
        out.append(Clause(card_name, head.strip(" .,"), kind, gate))
        if not tail:
            # No comma closed it, so this sentence is the condition and nothing
            # else — `While you control this battlefield` on its own line, or a
            # keyword-gated fragment. Returning it as a condition rather than
            # dropping through to the effect splitter is what keeps it out of
            # `unclassified` for the wrong reason.
            return out
        s = tail

    for chunk in _SPLIT_RE.split(s):
        chunk = chunk.strip(" .")
        if not chunk:
            continue
        # A leading `If …,` is a gate, not an instruction.
        lead = re.match(r"^(If\b[^,]*|Unless\b[^,]*),\s*", chunk, re.I)
        if lead:
            out.append(Clause(card_name, lead.group(1), "condition", gate))
            chunk = chunk[lead.end():].strip()
            if not chunk:
                continue
        elif re.match(r"^(?:if|unless|while)\b", chunk, re.I):
            # A whole chunk that is only a condition — `If they do` left behind
            # once `, then do this:` was split off. Without this it reached the
            # effect table, matched no primitive, and was reported as text the
            # vocabulary cannot express when in fact it is a plain conditional.
            out.append(Clause(card_name, chunk, "condition", gate))
            continue
        for piece in AND_SPLIT.split(chunk):
            piece = piece.strip(" .,")
            if not piece:
                continue
            trailing = TRAILING_COND.search(piece)
            tail_cond = None
            if trailing and len(piece) > len(trailing.group(1)) + 3:
                tail_cond = trailing.group(1)
                piece = piece[:trailing.start()].strip(" .,")
            out.extend(_split_cost_within(card_name, piece, gate))
            if tail_cond:
                out.append(Clause(card_name, tail_cond, "condition", gate))
    return out


def _split_cost_within(card_name, piece, gate):
    """`[do X] to [do Y]` -> a cost clause and an effect clause (CR 355.10.c.1).

    `you may exhaust me to channel 1 rune` is a cost and an effect, and the
    rules say so explicitly. Counting it as one clause with two primitives
    would hide the commonest cost shape in the game behind the effect it buys.

    The one exception is an additional cost, which already names itself:
    `you may pay {1} as an additional cost to play me` is one clause about
    playing this card, not a cost to play something else.
    """
    m = COST_TO.search(piece)
    if not m or re.search(r"additional cost", piece, re.I):
        return [Clause(card_name, piece, "effect", gate)]
    left = piece[:m.start()].strip(" .,")
    right = piece[m.end():].strip(" .,")
    if not left or not right:
        return [Clause(card_name, piece, "effect", gate)]
    return [Clause(card_name, left, "cost", gate),
            Clause(card_name, right, "effect", gate)]


def _split_on_condition_comma(sentence):
    """Split a trigger head from its effect at the comma that closes it.

    The first top-level comma is right most of the time and catastrophically
    wrong for multi-event triggers: `When this is played, discarded, or killed,
    draw 1` would yield the trigger `when this is played` and the instruction
    `discarded, or killed, draw 1`, inventing an event the card does not have
    and losing two it does.

    So: take the first comma whose tail actually *starts like an instruction*,
    and fall back to the first comma when none does. `if` and `unless` count as
    instruction starts, because `When I attack, if you control 4 or fewer runes,
    deal 2` must keep its condition as a separate clause rather than folding it
    into the trigger.
    """
    depth = 0
    first = None
    for i, ch in enumerate(sentence):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth = max(0, depth - 1)
        elif ch == "," and depth == 0:
            tail = sentence[i + 1:].strip()
            if first is None:
                first = i
            if ENUMERATION_TAIL.match(tail):
                continue
            if INSTRUCTION_START.match(tail):
                return sentence[:i].strip(), tail
    if first is not None:
        return sentence[:first].strip(), sentence[first + 1:].strip()
    return sentence.strip(), ""


# ---------------------------------------------------------------------------
# Lexicons
# ---------------------------------------------------------------------------
#
# Every table below is ordered, and the first match wins. The ids are the names
# a DSL would use; the CR column is the rule that defines the action, which is
# what a script's `citations` field would carry (#26).

def _rx(pattern):
    return re.compile(pattern, re.I)


#: Trigger events. `id, CR, regex`. First match wins, so the specific shapes
#: are listed before the general ones.
TRIGGERS = [
    ("play_self",        "383.4.a", _rx(r"\bplay (?:me|this)\b|\b(?:me|this) (?:is|are) played\b|\bi'?m played\b")),
    ("play_other",       "383",     _rx(r"\bplays?\b|\bplayed\b")),
    ("conquer",          "383.4.c", _rx(r"\bconquer")),
    ("hold",             "383.4.d", _rx(r"\bholds?\b|\bhold\b")),
    ("attack",           "383.4.e", _rx(r"\battacks?\b|\battacking\b")),
    ("defend",           "383.4.f", _rx(r"\bdefends?\b|\bdefending\b")),
    ("win_combat",       "383",     _rx(r"\bwins? (?:a |the )?combat")),
    ("lose_combat",      "383",     _rx(r"\bloses? (?:a |the )?combat")),
    ("showdown_begins",  "383",     _rx(r"\bshowdown (?:begins|starts)\b|\bcombat (?:begins|starts)\b")),
    ("combat_ends",      "383",     _rx(r"\bcombat .*ends\b|\bshowdown ends\b|\bcombat ends\b")),
    ("die",              "428",     _rx(r"\bdies\b|\bdie\b|\bis killed\b|\bare killed\b|\bkilled\b")),
    ("kill_trigger",     "428",     _rx(r"\bkills?\b")),
    ("recycle_trigger",  "416",     _rx(r"\brecycles?\b")),
    ("hide_trigger",     "421",     _rx(r"\bhides?\b|\bhidden\b")),
    ("banish_trigger",   "427",     _rx(r"\bbanish(?:es|ed)?\b")),
    ("use_ability",      "377",     _rx(r"\buse[sd]?\b")),
    ("move",             "420",     _rx(r"\bmoves?\b")),
    ("become_empowered", "441",     _rx(r"\bbecomes? \[?empowered")),
    ("become_state",     "383",     _rx(r"\bbecomes?\b")),
    ("targeted",         "383.4.b", _rx(r"\bchoose[sn]?\b")),
    ("combat_damage",    "417",     _rx(r"\b(?:deals?|is dealt|takes?) .*damage")),
    ("readied",          "415",     _rx(r"\bready\b|\breadies\b|\bis readied\b")),
    ("exhausted",        "414",     _rx(r"\bexhaust")),
    ("buffed",           "426",     _rx(r"\bbuffs?\b|\bbuffed\b")),
    ("stunned",          "423",     _rx(r"\bstun")),
    ("empower_other",    "441",     _rx(r"\bempowers?\b")),
    ("draw_trigger",     "413",     _rx(r"\bdraws?\b")),
    ("discard_trigger",  "422",     _rx(r"\bdiscards?\b|\bdiscarded\b")),
    ("burn_trigger",     "440",     _rx(r"\bburns?\b")),
    ("channel_trigger",  "430",     _rx(r"\bchannels?\b")),
    ("score_trigger",    "383",     _rx(r"\bscores?\b|\bgains? .*points?\b")),
    ("gain_control",     "383",     _rx(r"\bgains? control\b")),
    ("equip_trigger",    "818",     _rx(r"\bequip|\battach")),
    ("reveal_trigger",   "424",     _rx(r"\brevealed?\b|\blooks? at\b")),
    ("enters",           "383",     _rx(r"\benters?\b")),
    ("leaves",           "383",     _rx(r"\bleaves?\b|\breturn(?:s|ed)?\b")),
    ("beginning_phase",  "310",     _rx(r"^at\b.*\bbeginning\b")),
    ("start_of_turn",    "307",     _rx(r"^(?:at|starting)\b.*\bstart of\b")),
    ("end_of_turn",      "307",     _rx(r"^at\b.*\bend of\b.*\bturn\b")),
    ("end_of_phase",     "307",     _rx(r"^at\b.*\bend of\b")),
    ("phase_other",      "307",     _rx(r"^at\b")),
    ("nth_time",         "383.1",   _rx(r"\b(?:first|second|third|\w+) time\b")),
    ("delayed_next",     "383",     _rx(r"^the next\b")),
    ("each_time",        "383.1",   _rx(r"^each time\b")),
    ("as_played",        "355.1",   _rx(r"^as\b")),
    ("frequency_only",   "383.3.e", _rx(r"^(?:once each turn|\d+ times each turn)\b")),
    ("pay_trigger",      "444",     _rx(r"\bpays?\b|\bspends?\b|\bspent\b")),
]

#: Trigger rows loose enough to fire on a clause that a specific row already
#: explained. They are consulted only when nothing specific matched, so
#: `When I attack or defend` counts as two events while `When I become
#: [Empowered]` does not also count as a generic "becomes".
TRIGGER_FALLBACKS = {
    "become_state", "enters", "leaves", "phase_other", "as_played",
    "pay_trigger", "reveal_trigger", "play_other", "nth_time", "targeted",
    "start_of_turn", "end_of_phase",
}

#: Effect primitives. `id, CR game action (or None), regex`.
#: The CR column is the point of the exercise: #26 wants primitives that ARE the
#: rules' named game actions wherever one exists, so that a script's citation is
#: a real rule and not a label invented here.
PRIMITIVES = [
    # --- the CR's 32 named game actions, 413-444 ----------------------------
    ("burn_out",     "431", _rx(r"\bburns? out\b")),
    ("draw",         "413", _rx(r"\bdraws?\b|\bdrawn\b")),
    ("exhaust",      "414", _rx(r"\bexhausts?\b")),
    ("ready",        "415", _rx(r"\bready\b|\breadies\b|\breadied\b")),
    ("recycle",      "416", _rx(r"\brecycles?\b|\brecycling\b")),
    ("deal",         "417", _rx(r"\bdeals?\b|\bdealt\b")),
    ("heal",         "418", _rx(r"\bheals?\b")),
    ("play",         "419", _rx(r"\bplays?\b|\bplayed\b")),
    ("move",         "420", _rx(r"\bmove[sd]?\b|\bmoving\b")),
    ("hide",         "421", _rx(r"\bhides?\b|\bhidden\b")),
    ("discard",      "422", _rx(r"\bdiscard(?:s|ed)?\b")),
    ("stun",         "423", _rx(r"\bstuns?\b|\bstunned\b")),
    ("reveal",       "424", _rx(r"\breveal(?:s|ed|ing)?\b")),
    ("counter",      "425", _rx(r"\bcounters?\b")),
    ("buff",         "426", _rx(r"\bbuffs?\b|\[buff\]|\bbuffed\b")),
    ("banish",       "427", _rx(r"\bbanish(?:es|ed)?\b")),
    ("kill",         "428", _rx(r"\bkills?\b|\bkilled\b")),
    ("add",          "429", _rx(r"\badds?\b|\[add\]")),
    ("channel",      "430", _rx(r"\bchannels?\b")),
    ("double",       "432", _rx(r"\bdoubles?\b")),
    ("swap",         "433", _rx(r"\bswaps?\b")),
    ("attach",       "434", _rx(r"\battach(?:es|ed)?\b|\bequips?\b")),
    ("detach",       "435", _rx(r"\bdetach(?:es|ed)?\b|\bunattach(?:es|ed)?\b")),
    ("predict",      "436", _rx(r"\bpredicts?\b|\[predict")),
    ("prevent",      "437", _rx(r"\bprevents?\b")),
    ("replace",      "438", _rx(r"\breplaces?\b")),
    ("create",       "439", _rx(r"\bcreates?\b")),
    ("burn",         "440", _rx(r"\bburns?\b|\[burn")),
    ("empower",      "441", _rx(r"\bempowers?\b|\[empower\]")),
    ("disempower",   "442", _rx(r"\bdisempowers?\b")),
    ("skip",         "443", _rx(r"\bskips?\b")),
    ("pay",          "444", _rx(r"\bpay(?:s|ing)?\b|\bpaid\b")),
    # --- the three the plan already knew it had to add ----------------------
    ("give_might",   None,  _rx(r"[+-]\s*\d*\s*\{M\}|[+-]\s*\d+\s*might\b"
                                r"|\bgives?\b[^.]*\bmight\b|\bgrants?\b[^.]*\bmight\b")),
    ("create_token", None,  _rx(r"\btokens?\b")),
    ("score",        None,  _rx(r"\bscores?\b|\bgains? \d+ points?\b")),
    # --- everything the data added that the plan did not list ---------------
    ("grant_keyword", None, _rx(r"(?:gives?|grants?|has|have|gain(?:s)?)\b[^.]*\[[A-Z]|^\[[A-Z][^\]]*\](?:[,\s]|$)")),
    ("modify_cost",  None,  _rx(r"\bcosts?\b[^.]{0,60}\b(?:less|more)\b"
                                r"|\b(?:less|more)\b[^.]{0,60}\bcosts?\b"
                                r"|\breduce[sd]?\b[^.]{0,30}\bcost"
                                r"|\bcost\b[^.]{0,30}\b(?:is|are) (?:reduced|increased)"
                                r"|\bto a minimum of\b|\bcosts? \{")),
    ("gain_xp",      None,  _rx(r"\bgains? \d+ xp\b|\bgain \d+ xp\b")),
    ("spend",        None,  _rx(r"\bspends?\b|\bspent\b")),
    ("return_to",    None,  _rx(r"\breturns?\b")),
    ("look_at",      None,  _rx(r"\blooks? at\b")),
    ("put",          None,  _rx(r"\bputs?\b|\bplaces?\b")),
    ("name",         None,  _rx(r"\bnames? an?\b")),
    ("modify_tag",   None,  _rx(r"\btags?\b")),
    ("activate",     "383.4.g", _rx(r"\bactivates?\b")),
    ("take_turn",    None,  _rx(r"\btakes? (?:a|an extra|another) turn\b")),
    ("become_copy",  None,  _rx(r"\bbecomes? a copy\b|\bcopy\b|\bcopies\b")),
    ("gain_control", None,  _rx(r"\bgains? control\b|\btakes? control\b|^you control\b")),
    ("enter",        "355.2", _rx(r"\benters?\b")),
    # Recall is CR 455, NOT one of the game actions at 413-444 the plan's
    # primitive list was drawn from — and CR 456 is explicit that a Recall is
    # not a Move and cannot be stopped by anything that stops Movement. A DSL
    # that spelled it `move(to=base)` would be wrong in a way no test of the
    # common case would catch.
    ("recall",       "455", _rx(r"\brecall(?:s|ed)?\b")),
    ("ignore",       None,  _rx(r"\bignor(?:e|es|ed|ing)\b")),
    ("modify_trigger", "383", _rx(r"\btriggers?\b")),
    ("win_game",     None,  _rx(r"\bwins? the game\b")),
    ("choose",       "355", _rx(r"\bchoos(?:e|es|en|ing)\b|\bchose\b|\btargets?\b")),
    ("use",          "377", _rx(r"\buse[sd]?\b")),
    ("permission",   None,  _rx(r"\bcan\b(?!')|\bmay be\b")),
    ("restriction",  None,  _rx(r"\bcan'?t\b|\bcannot\b|\bmust\b|\bonly\b"
                                r"|\bdon'?t\b|\bdoesn'?t\b")),
    # --- fallbacks: only consulted when nothing above matched ---------------
    ("set_stat",     None,  _rx(r"\bbecomes?\b|\bis increased\b|\bis reduced\b"
                                r"|\bincrease[sd]?\b|\breduce[sd]?\b|\bset to\b")),
    ("no_op",        None,  _rx(r"\bnothing\b")),
]

#: Primitive rows that describe the SHAPE of a clause rather than an action —
#: `can`, `only`, `becomes`. Left in the main pass they fire alongside every
#: real primitive and inflate the counts that are supposed to size the DSL, so
#: they are consulted only when nothing specific matched. That also makes them
#: readable as what they are: the clauses whose verb the table cannot name.
PRIMITIVE_FALLBACKS = {"set_stat", "no_op"}

#: Selector atoms, counted as occurrences across clauses (they are annotations
#: on a clause, not clauses of their own).
SELECTORS = [
    ("side:friendly",    _rx(r"\bfriendly\b|\byou control\b|\byour\b|\bi control\b")),
    ("side:enemy",       _rx(r"\benemy\b|\ban opponent(?:'s)?\b|\bopposing\b|\bthey control\b|\bopponents?\b")),
    ("side:any",         _rx(r"\bany (?:unit|gear|card|player|trash)\b|\beach player\b|\ball units\b|\bevery\b|\bsomething\b")),
    ("negated",          _rx(r"\bnon-?\w+\b")),
    ("type:unit",        _rx(r"\bunits?\b")),
    ("type:gear",        _rx(r"\bgears?\b|\bequipment\b")),
    ("type:spell",       _rx(r"\bspells?\b")),
    ("type:rune",        _rx(r"\brunes?\b")),
    ("type:battlefield", _rx(r"\bbattlefields?\b")),
    ("type:token",       _rx(r"\btokens?\b")),
    ("type:legend",      _rx(r"\blegends?\b")),
    ("type:champion",    _rx(r"\bchampions?\b")),
    ("type:card",        _rx(r"\bcards?\b")),
    ("type:ability",     _rx(r"\babilit(?:y|ies)\b")),
    ("self",             _rx(r"\bme\b|\bmy\b|\bI\b|\bthis\b")),
    ("at:here",          _rx(r"\bhere\b")),
    ("at:battlefield",   _rx(r"\bat (?:a|the|that|another|each|any) battlefield")),
    ("at:base",          _rx(r"\b(?:in|to|at) (?:a|the|its|your|their|any) base\b|\bbase\b")),
    ("at:showdown",      _rx(r"\bshowdowns?\b")),
    ("at:location",      _rx(r"\blocations?\b")),
    ("zone:hand",        _rx(r"\bhands?\b")),
    ("zone:trash",       _rx(r"\btrash(?:es)?\b")),
    ("zone:deck",        _rx(r"\bmain deck\b|\bdecks?\b")),
    ("zone:top_of_deck", _rx(r"\btop of\b|\btop \d+ cards?\b")),
    ("zone:board",       _rx(r"\bthe board\b")),
    ("zone:banishment",  _rx(r"\bbanishment\b|\bbanished\b")),
    ("zone:champion",    _rx(r"\bchampion zone\b")),
    ("another",          _rx(r"\banother\b|\bother\b")),
    ("up_to_n",          _rx(r"\bup to \w+\b")),
    ("any_number",       _rx(r"\bany number of\b")),
    ("all",              _rx(r"\ball\b|\beach\b|\bevery\b")),
    ("count:two_plus",   _rx(r"\b(?:two|three|four|2|3|4) (?:other )?(?:units?|gears?|cards?|runes?)\b")),
    ("by_cost",          _rx(r"\bcosts? \{?\d|\bcosting\b|\bcost \w+ or (?:less|greater|more)\b")),
    ("by_might",         _rx(r"\bmight \d|\b\d+ \{M\} or (?:less|greater|more)\b|\bless might\b|\bmore might\b|\bhighest might\b|\blowest might\b")),
    # by_tag's word list is BUILT FROM THE CARD DATA at import time, not typed
    # out here: the tag universe is whatever the sets print, and a hand-written
    # list would report `Bilgewater` as vocabulary the census cannot name the
    # day a set adds a region.
    ("by_tag",           None),   # filled in by _install_tag_selector()
    ("by_state",         _rx(r"\bstunned\b|\bbuffed\b|\b\[?empowered\]?\b|\bexhausted\b|\bready\b|\bhidden\b|\bdamaged\b|\battacking\b|\bdefending\b|\boccupied\b|\bopen\b|\bface ?down\b|\bmighty\b")),
    ("by_keyword",       _rx(r"\bwith \[[A-Z]")),
    ("owner",            _rx(r"\bowners?'?\b|\bcontrollers?'?\b")),
]

#: Condition atoms.
CONDITIONS = [
    ("paid_additional_cost", _rx(r"paid the additional cost")),
    ("if_you_do",            _rx(r"^if (?:you|they) do\b")),
    ("would_event",          _rx(r"\bwould\b")),
    ("unless_pays",          _rx(r"^unless\b")),
    ("alone",                _rx(r"\balone\b")),
    ("score_threshold",      _rx(r"\bscore\b|\bpoints? of\b|\bvictory score\b")),
    ("has_keyword",          _rx(r"\bhas \[|\bhave \[|\bwith \[")),
    ("already",              _rx(r"\balready\b")),
    ("has_played",           _rx(r"\byou'?ve played\b|\bplayed (?:a|an|another)\b")),
    ("phase_check",          _rx(r"\bbeginning phase\b|\b\w+ phase\b")),
    ("controls",             _rx(r"\bcontrols?\b|\byou have\b|\bthey have\b")),
    ("count_threshold",      _rx(r"\b\d+ or (?:more|fewer|less|greater)\b|\b\d+\+\b")),
    ("spent",                _rx(r"\bspent\b|\bpaid\b")),
    ("state_of_self",        _rx(r"\bi'?m\b|\bi am\b|\bi have\b|\bmy\b")),
    ("state_of_object",      _rx(r"\bstunned\b|\bbuffed\b|\bempowered\b|\bexhausted\b"
                                 r"|\bready\b|\bhidden\b|\bmighty\b|\bdamaged\b"
                                 r"|\battacking\b|\bdefending\b|\bface ?down\b"
                                 r"|\bequipped\b|\battached\b")),
    ("zone_of_object",       _rx(r"\bin (?:your|their|a|the) (?:hand|trash|deck|base)\b|\bat a battlefield\b|\bhere\b")),
    ("whose_turn",           _rx(r"\byour turn\b|\btheir turn\b|\bthis turn\b")),
    ("cant",                 _rx(r"\bcan'?t\b|\bcannot\b|\bunable\b|\bcouldn'?t\b"
                                 r"|\bdidn'?t\b|\bwouldn'?t\b|\bdon'?t\b")),
    ("this_killed_it",       _rx(r"\bthis kills?\b|\bif it (?:dies|died)\b")),
    ("comparison",           _rx(r"\bmore than\b|\bfewer than\b|\bequal to\b|\bgreater\b|\bless\b")),
    ("played_from",          _rx(r"\bplayed this from\b|\bfrom your hand\b|\bfrom your trash\b")),
    ("empty",                _rx(r"\bno \w+\b|\bempty\b|\bnothing\b")),
    ("is_type",              _rx(r"\bis an?\b|\bit'?s an?\b|\bwas an?\b")),
]

#: Choice forms.
CHOICES = [
    ("may",            _rx(r"\byou may\b|\bthey may\b|\bmay\b")),
    ("choose_object",  _rx(r"\bchoose[sn]?\b")),
    ("choose_mode",    _rx(r"^choose (?:one|two|three)\b")),
    ("up_to",          _rx(r"\bup to\b")),
    ("any_number",     _rx(r"\bany number of\b")),
    ("unless_pays",    _rx(r"\bunless\b.*\bpays?\b|\bmust pay\b")),
    ("opponent_picks", _rx(r"\ban opponent (?:chooses|reveals|picks)\b|\beach player (?:chooses|kills)\b|\bthe defender must\b")),
    ("order",          _rx(r"\bin any order\b")),
]

#: Cost forms.
COSTS = [
    ("exhaust_self",     _rx(r"\{E\}")),
    ("energy",           _rx(r"\{\d+\}")),
    ("power_any",        _rx(r"\{A\}")),
    ("power_own",        _rx(r"\{C\}")),
    ("power_domain",     _rx(r"\{[RGBOPY]\}")),
    ("additional_cost",  _rx(r"\badditional cost\b")),
    ("spend_xp",         _rx(r"\bspend \d+ xp\b")),
    ("spend_buff",       _rx(r"\bspend a buff\b|\bspend \d+ buffs?\b")),
    ("sacrifice",        _rx(r"\bkill (?:a|another|one of your) friendly\b|\bkill me\b|\bkill one of\b")),
    ("discard_cost",     _rx(r"\bdiscard\b")),
    ("recycle_cost",     _rx(r"\brecycle\b")),
    ("banish_cost",      _rx(r"\bbanish\b")),
    ("free",             _rx(r"\{0\}|\bignoring (?:its|any and all) costs?\b")),
]

#: Replacement effects. CR 369.1 names the identifying words: "as", "would",
#: "instead" — and CR 369.3 adds the "enters …" shape.
REPLACEMENTS = [
    ("instead",           _rx(r"\binstead\b")),
    ("would",             _rx(r"\bwould\b")),
    ("enters_modified",   _rx(r"\benters? (?:ready|exhausted|stunned|buffed|empowered)\b"
                              r"|\benter (?:ready|exhausted)\b|\bplay .* exhausted\b")),
    ("as_enters",         _rx(r"^as (?:you play|i am played|i enter|this enters|it enters)")),
    ("ignoring_cost",     _rx(r"\bignoring (?:its|their|any and all) costs?\b")),
    ("cost_replacement",  _rx(r"\bcosts? \{?[\dACRGBOPY]+\}? less\b|\bcosts? \{?[\dACRGBOPY]+\}? more\b|\bto a minimum of\b")),
    ("prevent_damage",    _rx(r"\bprevent")),
    ("skip_event",        _rx(r"\bskips?\b")),
    ("replace_token",     _rx(r"\breplaces?\b")),
]

DURATIONS = [
    ("this_turn",     _rx(r"\bthis turn\b")),
    ("this_combat",   _rx(r"\bthis combat\b|\bthis showdown\b")),
    ("end_of_this_turn", _rx(r"\bat the end of this turn\b")),
    ("next_turn",     _rx(r"\bnext turn\b|\byour next\b")),
    ("until_event",   _rx(r"\buntil\b")),
    ("while_state",   _rx(r"\bwhile\b")),
    ("permanent",     _rx(r"\bbuffs?\b|\bpermanently\b")),
]

_TAGS_INSTALLED = [0]


def install_tag_selector(pool):
    """Point `by_tag` at the tag vocabulary this corpus actually prints.

    Called from `Census.__init__` rather than only from `main`, so that
    importing this module and building a census by hand cannot produce quietly
    different numbers from running the script.
    """
    if _TAGS_INSTALLED[0]:
        return _TAGS_INSTALLED[0]
    tags = set()
    for entry in pool.values():
        for tag in entry.get("stats", {}).get("tags") or []:
            tags.add(re.escape(tag.lower()))
    pattern = (r"\btagged?\b|\bwith the \w+ tag\b"
               + ("|" + "|".join(r"\b%s\b" % t for t in sorted(tags)) if tags else ""))
    for i, row in enumerate(SELECTORS):
        if row[0] == "by_tag":
            SELECTORS[i] = ("by_tag", _rx(pattern))
            _TAGS_INSTALLED[0] = len(tags)
            return len(tags)
    raise AssertionError("by_tag row missing from SELECTORS")


#: The token specs a `create_token(spec)` primitive would have to name. Counted
#: because "one primitive" hides however many distinct tokens the game defines,
#: and a DSL that spells each one as its own primitive is a DSL 10 entries
#: larger than it looks.
TOKEN_SPEC = re.compile(
    r"\b(?:a|an|the|two|three|four|\d+)\s+(?:ready\s+|exhausted\s+)?"
    r"(?:\d+\s*\{M\}\s+)?"
    r"([A-Z][\w'-]*(?:\s+[A-Z][\w'-]*)*)\s+(?:unit|gear|spell|battlefield)?\s*token",
)

#: Words that carry no mechanical weight; the residue audit ignores them, so a
#: leftover word is genuinely something the vocabulary does not name.
STOPWORDS = set("""
a an and the to of in on at for from with by or if is are be been being it its
it's their them they you your yours my me mine i we our this that those these
each any all other another one two three four five six seven eight nine ten
than then there here as so do does did doing not no nor but into over under up
down out off again more most less least many much number amount equal per when
while where who whom which what how why also just only same such both either
neither every during before after until unless because since about above below
between among within without instead may can will would should must have has
had having get gets got s t n rest way times time turn turns player players
point points card cards don't doesn't isn't aren't won't i'm it's you've
they're there's else already still also same different next last first
""".split())


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def _all_matches(table, text, fallbacks=frozenset()):
    """Every row that matches, with fallback rows used only as a last resort."""
    specific, loose = [], []
    for row in table:
        if not row[-1].search(text):
            continue
        (loose if row[0] in fallbacks else specific).append(row[0])
    return specific or loose


def classify(clause):
    """Fill in everything the lexicons can say about one clause.

    A clause keeps its kind from segmentation; what changes here is whether it
    earns a bucket. An `effect` clause that matches no primitive becomes
    `unclassified` — that demotion is the whole instrument, and it is why the
    bucket is never empty by construction.
    """
    text = clause.text

    clause.selectors = _all_matches(SELECTORS, text)
    clause.choices = _all_matches(CHOICES, text)
    clause.costs = _all_matches(COSTS, text)
    clause.for_each = bool(re.search(r"\bfor each\b", text, re.I))
    durations = _all_matches(DURATIONS, text)
    clause.duration = durations[0] if durations else None

    for name, param in re.findall(r"\[([A-Z][A-Za-z'-]*)(?: (\d+))?\]", text):
        if name in CR_KEYWORDS:
            clause.keywords.append(name + (":" + param if param else ""))

    replacement = _all_matches(REPLACEMENTS, text)
    if replacement:
        clause.replacement = replacement[0]

    if clause.kind == "keyword":
        m = KEYWORD_TOKEN.match(text)
        if m and m.group(1) in CR_KEYWORDS:
            clause.bucket = [m.group(1)]
        elif m:
            # Bracketed but not a CR keyword: a game action in the symbol font,
            # or `[Mighty]`, which the rules never define. Reported, not hidden.
            clause.bucket = ["non-keyword:" + m.group(1)]
        else:
            clause.kind = "unclassified"
        return clause

    if clause.kind == "trigger":
        hits = _all_matches(TRIGGERS, text, TRIGGER_FALLBACKS)
        if hits:
            clause.bucket = hits
        else:
            clause.kind = "unclassified"
        return clause

    if clause.kind == "condition":
        hits = _all_matches(CONDITIONS, text)
        clause.bucket = hits[:1] if hits else ["condition:other"]
        return clause

    if clause.kind == "cost":
        # A cost line is either symbols (`{1}{R}, {E}`) or a game action used as
        # a cost (`Recycle a unit from your trash`, `Kill this`, `Disempower
        # me`) — CR 355.10.c.1's "[do X] to [do Y]". Falling back to the
        # primitive table rather than inventing cost-only ids keeps the DSL
        # from needing a second vocabulary for the same actions.
        hits = clause.costs
        if hits:
            clause.bucket = hits
        else:
            actions = _all_matches(PRIMITIVES, text, PRIMITIVE_FALLBACKS)
            if actions:
                clause.bucket = ["action:" + a for a in actions]
            else:
                clause.kind = "unclassified"
        return clause

    if clause.kind == "mode":
        clause.bucket = ["choose_mode"]
        return clause

    hits = _all_matches(PRIMITIVES, text, PRIMITIVE_FALLBACKS)
    if not hits and clause.keywords and re.fullmatch(
            r"(?:\[[A-Z][^\]]*\][,\s]*)+", text.strip()):
        # `I have [Deflect], [Ganking], and [Shield]` splits into pieces that
        # are a keyword and nothing else. That is still a grant.
        hits = ["grant_keyword"]
    if hits:
        clause.bucket = hits
        clause.residue = residue_of(clause)
    else:
        clause.kind = "unclassified"
    return clause


#: Words a primitive explains that its own regex does not literally cover.
#: `give a unit +2 {M}` matches `give_might` on the `+2 {M}`, and "give" would
#: otherwise show up in the residue as an unnamed verb — which would be a
#: reporting artefact, not a finding.
EXPLAINED_BY = {
    "give_might": ["give", "gives", "given", "might", "mights", "grants",
                   "grant", "gain", "gains"],
    "grant_keyword": ["give", "gives", "grants", "grant", "gain", "gains",
                      "has", "have"],
    "create_token": ["play", "plays", "create", "creates"],
    "modify_cost": ["cost", "costs", "less", "more", "minimum", "reduce",
                    "reduced", "reducing", "energy", "power"],
    "return_to": ["hand", "owner", "owners"],
    "gain_xp": ["gain", "gains"],
    "deal": ["damage", "might", "mights"],
    "heal": ["damage"],
    "prevent": ["damage"],
    "ignore": ["energy", "power", "cost", "costs"],
    "choose": ["chosen"],
    "set_stat": ["might", "increase", "increased", "reduce", "reduced"],
    "spend": ["buff", "buffs"],
    "pay": ["energy", "power"],
    "modify_trigger": ["effect", "effects"],
    "use": ["ability", "abilities"],
}


def _word(raw):
    """One residue/consumed word, so both sides compare the same way.

    `its owner's hand` yields the word `owner's` and the selector that explains
    it matched the text `owner`; without folding both the same way the word
    would be reported as unexplained vocabulary that the table in fact names.
    """
    return re.sub(r"'s$|'$", "", raw.lower())


def residue_of(clause):
    """Content words in an effect clause that nothing in the lexicons explains.

    The point of measuring this: `draw 1 and give a unit +2 {M}` matches `draw`
    and is counted as classified, while `give` and `{M}` were never looked at.
    Everything the selector, cost, choice and replacement tables matched counts
    as explained too — those are real vocabulary, just counted in another
    section — so what is left is genuinely unnamed. A verb high in the residue
    is a primitive the table is missing; a long residue overall means the
    splitter is leaving clauses too big and the counts understate the
    vocabulary.
    """
    text = clause.text
    consumed = set()
    tables = [(PRIMITIVES, clause.bucket), (SELECTORS, clause.selectors),
              (CHOICES, clause.choices), (COSTS, clause.costs),
              (DURATIONS, [clause.duration] if clause.duration else []),
              (REPLACEMENTS, [clause.replacement] if clause.replacement else [])]
    for table, hits in tables:
        for row in table:
            if row[0] not in hits:
                continue
            consumed.update(EXPLAINED_BY.get(row[0], ()))
            for m in row[-1].finditer(text):
                for word in re.findall(r"[A-Za-z']+", m.group(0)):
                    consumed.add(_word(word))
    # A keyword reference and a token spec are vocabulary counted elsewhere
    # (§9, §9b); leaving their words in the residue would report `[Deflect]` as
    # an unnamed verb.
    for kw in clause.keywords:
        consumed.update(kw.split(":")[0].lower().split("-"))
    for spec in TOKEN_SPEC.findall(text):
        consumed.update(_word(w) for w in spec.split())

    out = []
    for word in re.findall(r"[A-Za-z'][A-Za-z']+", text):
        low = _word(word)
        if not low or low in STOPWORDS or low in consumed:
            continue
        out.append(low)
    return out


# ---------------------------------------------------------------------------
# Census
# ---------------------------------------------------------------------------

class Census(object):
    def __init__(self, label, pool, names):
        install_tag_selector(pool)
        self.label = label
        self.cards = sorted(n for n in names if n in pool)
        self.missing = sorted(n for n in names if n not in pool)
        self.pool = pool
        self.clauses = []
        self.by_card = {}
        self.words = {}
        self.rules_words = {}
        self.reminders = 0
        self.token_specs = collections.Counter()
        self.brackets = collections.Counter()
        for name in self.cards:
            entry = pool[name]
            body, reminders = split_reminder(normalise(entry.get("text", "")))
            self.reminders += len(reminders)
            for spec in TOKEN_SPEC.findall(body):
                self.token_specs[spec.strip()] += 1
            for token, param in ANY_BRACKET.findall(body):
                self.brackets[token + (":" + param if param else "")] += 1
            self.words[name] = len(re.findall(r"[\w{}+'-]+", normalise(entry.get("text", ""))))
            self.rules_words[name] = len(re.findall(r"[\w{}+'-]+", body))
            clauses = [classify(c) for c in segment(name, entry.get("text", ""))]
            self.by_card[name] = clauses
            self.clauses.extend(clauses)

    # -- aggregates --------------------------------------------------------

    def with_text(self):
        return [n for n in self.cards if self.rules_words[n] > 0]

    def kinds(self):
        return collections.Counter(c.kind for c in self.clauses)

    def buckets(self, kind):
        out = collections.Counter()
        for c in self.clauses:
            if c.kind == kind:
                for b in c.bucket:
                    out[b] += 1
        return out

    def annotation(self, attr):
        out = collections.Counter()
        for c in self.clauses:
            for v in getattr(c, attr) or []:
                out[v] += 1
        return out

    def replacements(self):
        return collections.Counter(
            c.replacement for c in self.clauses if c.replacement)

    def cards_with_replacement(self):
        return sorted({c.card for c in self.clauses if c.replacement})

    def triggers_per_card(self):
        """Trigger clauses PLUS triggered-ability keywords.

        Counting only `When …` lines reported 6 gauntlet cards with more than
        one trigger. `[Deathknell]` is a triggered ability by CR 808 and
        `[Hunt]`, `[Vision]`, `[Temporary]`, `[Weaponmaster]` and `[Quick-Draw]`
        are too, so a card carrying one of those alongside a `When …` line has
        two triggers for the engine even though only one says "when".
        """
        out = collections.Counter()
        for name, clauses in self.by_card.items():
            n = sum(1 for c in clauses if c.kind == "trigger")
            n += sum(1 for c in clauses if c.kind == "keyword"
                     and c.bucket and c.bucket[0] in TRIGGERED_KEYWORDS)
            out[name] = n
        return out

    def examples(self, kind, bucket, limit=3):
        seen = []
        for c in self.clauses:
            if c.kind == kind and bucket in c.bucket and c.card not in seen:
                seen.append(c.card)
            if len(seen) >= limit:
                break
        return seen

    def example_text(self, kind, bucket):
        for c in self.clauses:
            if c.kind == kind and bucket in c.bucket:
                return c.text
        return ""

    def unclassified(self):
        return [c for c in self.clauses if c.kind == "unclassified"]

    def residue(self):
        out = collections.Counter()
        for c in self.clauses:
            for w in c.residue:
                out[w] += 1
        return out


def coverage_cut(counter, total, target=0.95):
    """The smallest prefix of `counter` (by count) that reaches `target` share.

    Returns (chosen ids in order, cumulative share at each step). This is the
    number #26 actually asks for: not "how many distinct phrasings exist" but
    "how many atoms buy 95% of the clauses", which is the size the DSL has to
    be.
    """
    chosen, running = [], 0
    if not total:
        return chosen
    for name, n in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0])):
        running += n
        chosen.append((name, n, running / float(total)))
        if running / float(total) >= target:
            break
    return chosen


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def hist(values, buckets):
    out = collections.Counter()
    for v in values:
        for lo, hi, label in buckets:
            if lo <= v <= hi:
                out[label] += 1
                break
    return out


CLAUSE_BUCKETS = [
    (0, 0, "0"), (1, 1, "1"), (2, 2, "2"), (3, 3, "3"), (4, 4, "4"),
    (5, 6, "5-6"), (7, 9, "7-9"), (10, 14, "10-14"), (15, 9999, "15+"),
]


def table(rows, headers):
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))
    out = ["| " + " | ".join(h.ljust(widths[i]) for i, h in enumerate(headers)) + " |"]
    out.append("|" + "|".join("-" * (w + 2) for w in widths) + "|")
    for row in rows:
        out.append("| " + " | ".join(str(c).ljust(widths[i])
                                     for i, c in enumerate(row)) + " |")
    return out


def bucket_rows(gaunt, full, kind, attr=None, limit=None):
    """Rows of `bucket | gauntlet | all | example card`, sorted by gauntlet count."""
    g = gaunt.annotation(attr) if attr else gaunt.buckets(kind)
    a = full.annotation(attr) if attr else full.buckets(kind)
    names = sorted(set(g) | set(a), key=lambda n: (-g.get(n, 0), -a.get(n, 0), n))
    if limit:
        names = names[:limit]
    rows = []
    for n in names:
        example = ""
        if not attr:
            ex = gaunt.examples(kind, n, 1) or full.examples(kind, n, 1)
            example = ex[0] if ex else ""
        rows.append((n, g.get(n, 0), a.get(n, 0), example))
    return rows


def render(gaunt, full, meta, markdown=False, top=None):
    L = []
    w = L.append

    def head(level, text):
        w("")
        w(("#" * level + " " + text) if markdown else (text.upper()))
        w("")

    def block(rows, headers):
        if markdown:
            L.extend(table(rows, headers))
        else:
            L.extend(table(rows, headers))

    w("# Riftbound card-text vocabulary census" if markdown
      else "RIFTBOUND CARD-TEXT VOCABULARY CENSUS")
    w("")
    w("- corpus: `.claude/skills/deck-lab/data/cards.json` — %d distinct cards "
      "under %d lookup names (%d cards carry Riot errata; %d bare champion "
      "names are ambiguous aliases, not ambiguous cards)"
      % (meta["pool"], meta["aliases"], meta["errata"], meta["ambiguous_aliases"]))
    w("- field: `%s` (`%s`) — %d lists, %d distinct cards"
      % (meta["version"], meta["digest"], meta["lists"], len(gaunt.cards)))
    w("- generated by `engine-train/census.py`; re-run to reproduce every "
      "number below.")

    head(2, "1. Scope")
    rows = []
    for c in (gaunt, full):
        counts = [len(c.by_card[n]) for n in c.cards]
        with_text = c.with_text()
        unc = len(c.unclassified())
        rows.append((
            c.label, len(c.cards), len(with_text), len(c.clauses),
            "%.2f" % (len(c.clauses) / float(len(with_text)) if with_text else 0),
            sorted(counts)[len(counts) // 2] if counts else 0,
            max(counts) if counts else 0,
            unc,
            "%.1f%%" % (100.0 * unc / len(c.clauses) if c.clauses else 0),
        ))
    block(rows, ["scope", "cards", "with text", "clauses", "clauses/card",
                 "median", "max", "unclassified", "share"])

    head(2, "2. Clauses by kind")
    kg, ka = gaunt.kinds(), full.kinds()
    rows = [(k, kg.get(k, 0), ka.get(k, 0))
            for k in sorted(set(kg) | set(ka), key=lambda k: -kg.get(k, 0))]
    block(rows, ["kind", "gauntlet", "all 954"])

    head(2, "3. Trigger events")
    rows = bucket_rows(gaunt, full, "trigger")
    block(rows, ["trigger event", "gauntlet", "all 954", "example card"])

    head(2, "4. Effect primitives")
    cr = {row[0]: row[1] for row in PRIMITIVES}
    g, a = gaunt.buckets("effect"), full.buckets("effect")
    names = sorted(set(g) | set(a), key=lambda n: (-g.get(n, 0), -a.get(n, 0), n))
    rows = [(n, cr.get(n) or "—", g.get(n, 0), a.get(n, 0),
             (gaunt.examples("effect", n, 1) or full.examples("effect", n, 1) or [""])[0])
            for n in names]
    block(rows, ["primitive", "CR", "gauntlet", "all 954", "example card"])

    head(2, "5. Selector atoms")
    block(bucket_rows(gaunt, full, None, "selectors"),
          ["selector atom", "gauntlet", "all 954", ""])

    head(2, "6. Condition atoms")
    block(bucket_rows(gaunt, full, "condition"),
          ["condition atom", "gauntlet", "all 954", "example card"])

    head(2, "7. Choice forms")
    block(bucket_rows(gaunt, full, None, "choices"),
          ["choice form", "gauntlet", "all 954", ""])

    head(2, "8. Cost forms")
    w("Counted wherever they appear, not only on an activated ability's cost "
      "line: `You may pay {1} as an additional cost to play me` is a cost "
      "inside an effect clause. Activated-ability cost lines specifically: "
      "%d gauntlet clauses, %d across all 954."
      % (gaunt.kinds().get("cost", 0), full.kinds().get("cost", 0)))
    w("")
    block(bucket_rows(gaunt, full, None, "costs"),
          ["cost form", "gauntlet", "all 954", ""])

    head(2, "9. Keyword references")
    kg = gaunt.annotation("keywords")
    ka = full.annotation("keywords")
    names = sorted(set(kg) | set(ka), key=lambda n: (-kg.get(n, 0), n))
    block([(n, KEYWORD_KIND[n.split(":")[0]][0],
            KEYWORD_KIND[n.split(":")[0]][1], kg.get(n, 0), ka.get(n, 0))
           for n in names],
          ["keyword[:param]", "CR", "kind (per CR)", "gauntlet", "all 954"])
    w("")
    w("- distinct CR keywords referenced: **%d of the 25** in CR 805-829 "
      "(gauntlet), %d (all 954)"
      % (len({n.split(":")[0] for n in kg}), len({n.split(":")[0] for n in ka})))
    nonkw_g = {k: v for k, v in gaunt.brackets.items()
               if k.split(":")[0] not in CR_KEYWORDS}
    nonkw_a = {k: v for k, v in full.brackets.items()
               if k.split(":")[0] not in CR_KEYWORDS}
    if nonkw_a:
        w("")
        w("Bracketed in the corpus but NOT a CR keyword — game actions set in "
          "the symbol font, plus one state the rules never define:")
        w("")
        block([(k, nonkw_g.get(k, 0), nonkw_a.get(k, 0))
               for k in sorted(set(nonkw_g) | set(nonkw_a),
                               key=lambda k: (-nonkw_a.get(k, 0), k))],
              ["token", "gauntlet", "all 954"])

    head(2, "9b. Token specs")
    w("`create_token(spec)` is one primitive; these are the specs it has to "
      "name.")
    w("")
    tg, ta = gaunt.token_specs, full.token_specs
    block([(k, tg.get(k, 0), ta.get(k, 0))
           for k in sorted(set(tg) | set(ta), key=lambda k: (-ta.get(k, 0), k))],
          ["token spec", "gauntlet", "all 954"])

    head(2, "10. Replacement effects")
    rg, ra = gaunt.replacements(), full.replacements()
    names = sorted(set(rg) | set(ra), key=lambda n: (-rg.get(n, 0), n))
    block([(n, rg.get(n, 0), ra.get(n, 0)) for n in names],
          ["replacement kind", "gauntlet clauses", "all 954 clauses"])
    w("")
    w("- gauntlet cards with at least one replacement clause: **%d of %d** (%.0f%%)"
      % (len(gaunt.cards_with_replacement()), len(gaunt.with_text()),
         100.0 * len(gaunt.cards_with_replacement()) / max(1, len(gaunt.with_text()))))
    w("- all 954: **%d of %d**"
      % (len(full.cards_with_replacement()), len(full.with_text())))

    head(2, "11. Triggers per card")
    for c in (gaunt, full):
        tpc = c.triggers_per_card()
        counts = [tpc[n] for n in c.with_text()]
        h = hist(counts, [(0, 0, "0"), (1, 1, "1"), (2, 2, "2"),
                          (3, 3, "3"), (4, 99, "4+")])
        w("- %s: %s (cards with >1 trigger: **%d**)"
          % (c.label,
             ", ".join("%s=%d" % (k, h.get(k, 0)) for k in ["0", "1", "2", "3", "4+"]),
             sum(1 for v in counts if v > 1)))

    head(2, "12. Clauses per card")
    for c in (gaunt, full):
        counts = [len(c.by_card[n]) for n in c.with_text()]
        h = hist(counts, CLAUSE_BUCKETS)
        w("- %s: %s" % (c.label, ", ".join(
            "%s=%d" % (b[2], h.get(b[2], 0)) for b in CLAUSE_BUCKETS)))

    head(2, "13. Text length")
    for c in (gaunt, full):
        printed = [c.words[n] for n in c.with_text()]
        rules = [c.rules_words[n] for n in c.with_text()]
        w("- %s: printed median %d, mean %.1f, max %d; **over 100 words: %d** "
          "(%.1f%%)"
          % (c.label, sorted(printed)[len(printed) // 2],
             sum(printed) / float(len(printed)), max(printed),
             sum(1 for v in printed if v > 100),
             100.0 * sum(1 for v in printed if v > 100) / len(printed)))
        w("  rules text only (reminder text removed): median %d, max %d, "
          "over 100 words: %d"
          % (sorted(rules)[len(rules) // 2], max(rules),
             sum(1 for v in rules if v > 100)))

    head(2, "14. The vocabulary that covers 95% of gauntlet clauses")
    for kind, attr, label in [("trigger", None, "trigger events"),
                              ("effect", None, "effect primitives"),
                              (None, "selectors", "selector atoms"),
                              ("condition", None, "condition atoms"),
                              (None, "choices", "choice forms"),
                              (None, "costs", "cost forms")]:
        counter = gaunt.annotation(attr) if attr else gaunt.buckets(kind)
        total = sum(counter.values())
        cut = coverage_cut(counter, total)
        w("- **%s**: %d of %d distinct atoms reach 95%% of %d occurrences — %s"
          % (label, len(cut), len(counter), total,
             ", ".join("`%s`(%d)" % (n, k) for n, k, _ in cut)))
    rg = gaunt.replacements()
    w("- **replacement kinds**: %d distinct — %s"
      % (len(rg), ", ".join("`%s`(%d)" % (n, k) for n, k in
                            sorted(rg.items(), key=lambda kv: -kv[1]))))

    head(2, "15. Unclassified")
    for c in (gaunt, full):
        w("- %s: **%d clauses** (%.1f%% of %d) across %d cards"
          % (c.label, len(c.unclassified()),
             100.0 * len(c.unclassified()) / max(1, len(c.clauses)),
             len(c.clauses), len({x.card for x in c.unclassified()})))
    w("")
    w("Every unclassified gauntlet clause, in full:")
    w("")
    if not gaunt.unclassified():
        w("_(none — every gauntlet clause matched something. That is a claim "
          "the residue audit in §16 exists to check, not one to take on its "
          "own.)_")
    for cl in sorted(gaunt.unclassified(), key=lambda c: (c.card, c.text)):
        w("- `%s` — %s" % (cl.card, cl.text))
    w("")
    w("Every unclassified clause across all %d cards:" % len(full.cards))
    w("")
    for cl in sorted(full.unclassified(), key=lambda c: (c.card, c.text)):
        w("- `%s` — %s" % (cl.card, cl.text))

    head(2, "16. Residue audit")
    w("Content words inside CLASSIFIED effect clauses that no matched "
      "primitive accounts for. A verb high in this list is a primitive the "
      "table is missing; a noun is usually a selector already counted in §5.")
    w("")
    res = gaunt.residue()
    block([(word, n) for word, n in res.most_common(top or 40)],
          ["residue word", "gauntlet occurrences"])
    total_words = sum(
        len(re.findall(r"[A-Za-z'][A-Za-z']+", c.text))
        for c in gaunt.clauses if c.kind == "effect")
    w("")
    w("- residue is %d of %d content words in gauntlet effect clauses (%.1f%%)"
      % (sum(res.values()), total_words,
         100.0 * sum(res.values()) / max(1, total_words)))

    if gaunt.missing or full.missing:
        head(2, "17. Names that did not resolve")
        for c in (gaunt, full):
            if c.missing:
                w("- %s: %d — %s" % (c.label, len(c.missing), ", ".join(c.missing)))

    return "\n".join(L)


def render_cards(pool, names):
    """Every clause of the named cards, as the classifier sees them.

    Coverage numbers are cheap to make look good and impossible to trust
    without this: the only way to know a clause was classified *correctly* is
    to read the printed text beside what the classifier made of it.
    """
    L = []
    for name in names:
        entry = pool.get(name)
        if entry is None:
            L.append("?? no such card: %s" % name)
            continue
        L.append("=== %s [%s]" % (name, entry["stats"].get("type")))
        L.append("    %s" % normalise(entry.get("text", "")))
        for c in (classify(x) for x in segment(name, entry.get("text", ""))):
            bits = ["%-13s %s" % (c.kind, c.text)]
            if c.bucket:
                bits.append("        -> %s" % ", ".join(c.bucket))
            extra = []
            if c.selectors:
                extra.append("sel=%s" % "+".join(c.selectors))
            if c.choices:
                extra.append("choice=%s" % "+".join(c.choices))
            if c.costs:
                extra.append("cost=%s" % "+".join(c.costs))
            if c.replacement:
                extra.append("repl=%s" % c.replacement)
            if c.duration:
                extra.append("dur=%s" % c.duration)
            if c.keywords:
                extra.append("kw=%s" % "+".join(c.keywords))
            if c.for_each:
                extra.append("for_each")
            if c.gate:
                extra.append("gate=%s" % c.gate)
            if c.residue:
                extra.append("residue=%s" % ",".join(c.residue))
            if extra:
                bits.append("        .. %s" % "  ".join(extra))
            L.append("  " + "\n  ".join(bits))
        L.append("")
    return "\n".join(L)


def render_audit(gaunt):
    L = []
    L.append("UNCLASSIFIED — gauntlet (%d)" % len(gaunt.unclassified()))
    for cl in sorted(gaunt.unclassified(), key=lambda c: (c.card, c.text)):
        L.append("  [%s] %s :: %s" % (cl.kind, cl.card, cl.text))
    L.append("")
    L.append("RESIDUE — gauntlet (top 80)")
    for word, n in gaunt.residue().most_common(80):
        L.append("  %5d  %s" % (n, word))
    return "\n".join(L)


def to_json(gaunt, full, meta):
    def dump(c):
        return {
            "label": c.label,
            "cards": len(c.cards),
            "cards_with_text": len(c.with_text()),
            "clauses": len(c.clauses),
            "kinds": dict(c.kinds()),
            "triggers": dict(c.buckets("trigger")),
            "primitives": dict(c.buckets("effect")),
            "selectors": dict(c.annotation("selectors")),
            "conditions": dict(c.buckets("condition")),
            "choices": dict(c.annotation("choices")),
            "costs": dict(c.annotation("costs")),
            "cost_lines": dict(c.buckets("cost")),
            "token_specs": dict(c.token_specs),
            "keywords": dict(c.annotation("keywords")),
            "replacements": dict(c.replacements()),
            "cards_with_replacement": len(c.cards_with_replacement()),
            "unclassified": [{"card": x.card, "text": x.text}
                             for x in c.unclassified()],
        }
    return json.dumps({"meta": meta, "gauntlet": dump(gaunt), "all": dump(full)},
                      indent=1, sort_keys=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--markdown", action="store_true",
                    help="emit the report as markdown for docs/engine/")
    ap.add_argument("--audit", action="store_true",
                    help="only the unclassified clauses and the residue audit")
    ap.add_argument("--json", metavar="PATH",
                    help="also write the raw counts as JSON")
    ap.add_argument("--top", type=int, default=None,
                    help="rows to show in the residue table (default 40)")
    ap.add_argument("--card", action="append", metavar="NAME", default=[],
                    help="dump one card's clauses and classifications; repeatable")
    ap.add_argument("--sample", type=int, metavar="N",
                    help="dump N gauntlet cards, evenly spaced through the "
                         "alphabetised list — the spot check for §1's coverage")
    args = ap.parse_args(argv)

    pool, raw = load_pool()
    tag_count = install_tag_selector(pool)
    names, version, digest, lists = load_gauntlet()
    meta = {
        "pool": len(pool),
        "aliases": len(raw),
        "errata": len({v["name"] for v in raw.values() if v.get("errata")}),
        # `ambiguous` sits on a base-name ALIAS ("ahri"), not on a card: it says
        # that bare name could mean three different champion cards. Counting it
        # per card would report 37 ambiguous cards, which is not a thing that
        # exists.
        "ambiguous_aliases": sum(1 for v in raw.values() if v.get("ambiguous")),
        "version": version,
        "digest": digest,
        "lists": lists,
        "tags": tag_count,
    }
    gaunt = Census("gauntlet", pool, names)
    full = Census("all", pool, set(pool))

    if args.card or args.sample:
        picked = list(args.card)
        if args.sample:
            with_text = [n for n in gaunt.cards if gaunt.rules_words[n] > 0]
            step = max(1, len(with_text) // args.sample)
            picked += with_text[::step][:args.sample]
        print(render_cards(pool, picked))
        return 0

    if args.audit:
        print(render_audit(gaunt))
    else:
        print(render(gaunt, full, meta, markdown=args.markdown, top=args.top))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            fh.write(to_json(gaunt, full, meta))
    return 0


if __name__ == "__main__":
    sys.exit(main())

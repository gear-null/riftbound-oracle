"""The card-script AST: a closed vocabulary, and a validator that says why.

WHY THE VOCABULARY IS CLOSED

The plan sized this DSL from Forge's numbers and asked for the real ones first.
`docs/engine/vocabulary-census.md` measured them over the committed corpus:
**33 effect primitives, 20 trigger events, 25 selector atoms, 17 condition
atoms, 4 choice forms, 10 cost forms, 6 replacement kinds and 5 durations cover
95% of the 1,224 gauntlet clauses**, with all 25 CR keywords and 10 token specs.
Those atoms are the vocabulary. Nothing here is invented: every construct below
carries the count that earned it a row and the CR section that names it.

The closure is the lever, not an aesthetic. LLM generation against a fat
per-card API (XMage's 2,712 symbols) measured 5.3% exact accuracy; the DSL
exists to make the target small enough to hit.

DECLARED VS ACTIVE

`decisions.py` declares every decision kind the API will ever emit and marks the
subset this slice actually produces. Same discipline here, for the same reason:
every atom the census found anywhere in the 954-card pool is **declared**, and
the 95% cut is **active**. A script may only use an active atom. Using a
declared-but-inactive one is not a typo and must not be reported as one — it is
a real thing a card says that this vocabulary version has not taken on, so it
gets its own error code, its census count, and an instruction to mark the clause
`unsupported` instead. That is the difference between a vocabulary with a known
edge and one with a silent one.

WHY ERRORS ARE RECORDS

`validate()` returns a list of dicts, never a raised string. Each carries the
JSON path, the offending token, the expected set, and a rule citation where the
rules decide the matter. The compiler's repair loop feeds them straight back to
the model (plan §4.3 step 1); `deck_cli.py scripts --card X` prints the same
records to a person. A message would serve neither.
"""
import hashlib
import json
import re

import cards

#: The schema this module implements. A script names it, so a script written
#: against a different vocabulary is refused rather than half-understood.
SCHEMA = "riftbound-card-script/1"

#: How a script says where it came from (ADR 0009: scripts are data, and the
#: provenance of each one is part of the data).
SOURCES = ("manual", "compiled")

#: Clause-level coverage marks. The instrument is the clause, never the card:
#: the prior C++ engine reported near-complete coverage under "has a non-empty
#: body" and its own audit then found 325 of 787 cards with a real gap.
CLAUSE_STATUS = ("implemented", "approx", "unsupported")


# ---------------------------------------------------------------------------
# Citable sections
# ---------------------------------------------------------------------------
#
# A citation is checked against this table and nothing looser, so `CR:4133` and
# `CR:999` are refused rather than carried. The table is closed on purpose and
# for the same reason the vocabulary is: adding a rule to it is a deliberate
# act, and the gloss is what makes a reviewer able to tell a right citation from
# a plausible one. Verified against `rules-report`'s corpus at authoring time;
# `docs/engine/scripts.md` says how to re-check it after a rules update.

SECTIONS = {
    "108": "Non-Board Zones",
    "128": "Privacy",
    "137": "Might Bonus",
    "179": "Tokens",
    "194": "Points",
    "198": "Locations",
    "202": "Costs",
    "313": "Priority",
    "341": "Showdowns",
    "349": "Playing Cards",
    "355": "Make relevant choices",
    "360": "Abilities",
    "356": "Determine Total Cost",
    "357": "Pay the card's costs",
    "363": "Passive Abilities",
    "364": "Conditions, rules, constraints and statements",
    "367": "Replacement Effects",
    "369": "Replacement Effects intercede during execution",
    "372": "More than one Replacement Effect",
    "376": "Activated Abilities",
    "377": "Activated Abilities are repeatable effects with a cost",
    "382": "Triggered Abilities",
    "383": "Triggered Abilities are repeatable effects",
    "386": "Reflexive Triggers",
    "389": "Delayed Abilities",
    "393": "Linked Abilities",
    "407": "Game Actions",
    "413": "Draw",
    "414": "Exhaust",
    "415": "Ready",
    "416": "Recycle",
    "417": "Deal",
    "418": "Heal",
    "419": "Play",
    "420": "Move",
    "421": "Hide",
    "422": "Discard",
    "423": "Stun",
    "424": "Reveal",
    "425": "Counter",
    "426": "Buff",
    "427": "Banish",
    "428": "Kill",
    "429": "Add",
    "430": "Channel",
    "431": "Burn Out",
    "432": "Double",
    "433": "Swap",
    "434": "Attach",
    "435": "Detach",
    "436": "Predict",
    "437": "Prevent",
    "438": "Replace",
    "439": "Create",
    "440": "Burn",
    "441": "Empower",
    "442": "Disempower",
    "443": "Skip",
    "444": "Pay",
    "445": "Movement",
    "454": "Recalls",
    "455": "A Recall relocates a Permanent to its Base",
    "456": "Recalls are not Moves",
    "459": "Combat",
    "464": "The Combat Showdown Step",
    "465": "The Combat Damage Step",
    "466": "The Resolution Step",
    "467": "Scoring",
    "470": "Score once per Battlefield per turn",
    "473": "Layers",
    "477": "The layer order",
    "700": "Additional Rules",
    "701": "Buffs",
    "706": "Mighty",
    "716": "Attachment",
    "728": "XP",
    "800": "Keywords",
    "805": "Accelerate",
    "806": "Action",
    "807": "Assault",
    "808": "Deathknell",
    "809": "Deflect",
    "810": "Ganking",
    "811": "Hidden",
    "812": "Legion",
    "813": "Reaction",
    "814": "Shield",
    "815": "Tank",
    "816": "Temporary",
    "817": "Vision",
    "818": "Equip",
    "819": "Quick-Draw",
    "820": "Repeat",
    "821": "Weaponmaster",
    "822": "Ambush",
    "823": "Hunt",
    "824": "Level",
    "825": "Unique",
    "826": "Backline",
    "827": "Empower",
    "828": "Empowered",
    "829": "Flow",
}

_CITE_RE = re.compile(r"^CR:(\d{3})((?:\.\d+|\.[a-z])*)$")


# ---------------------------------------------------------------------------
# The atoms
# ---------------------------------------------------------------------------
#
# `name, cite, gauntlet, pool, active`. The counts are the census's, quoted so
# an error record can say how much of the corpus an atom is worth: "reserved,
# 4 gauntlet clauses" is a different message from "no such atom".


class Atom(object):
    __slots__ = ("name", "cite", "gauntlet", "pool", "active")

    def __init__(self, name, cite, gauntlet, pool, active):
        self.name = name
        self.cite = cite
        self.gauntlet = gauntlet
        self.pool = pool
        self.active = active

    def __repr__(self):
        return "Atom(%r, active=%r)" % (self.name, self.active)


def _atoms(rows):
    return dict((r[0], Atom(*r)) for r in rows)


def _active(table):
    return tuple(sorted(n for n, a in table.items() if a.active))


#: Effect primitives — census §4. `cite` is the CR game action where the rules
#: name one; the six without a CR action are the ones a DSL has to invent, and
#: they cite the rule that governs what they do instead.
PRIMITIVES = _atoms([
    # active: the 33 that cover 95% of gauntlet clauses (census §14)
    ("give_might",   "CR:477", 89, 189, True),
    ("play",         "CR:419", 84, 186, True),
    ("draw",         "CR:413", 65, 134, True),
    ("ready",        "CR:415", 38,  98, True),
    ("choose",       "CR:355", 36,  93, True),
    ("grant_keyword", "CR:800", 33, 104, True),
    ("deal",         "CR:417", 32, 105, True),
    ("modify_cost",  "CR:356", 29,  75, True),
    ("move",         "CR:420", 29,  63, True),
    ("kill",         "CR:428", 29,  62, True),
    ("restriction",  "CR:364", 21,  50, True),
    ("buff",         "CR:426", 20,  50, True),
    ("recycle",      "CR:416", 19,  33, True),
    ("return_to",    "CR:108", 17,  35, True),
    ("pay",          "CR:444", 14,  28, True),
    ("channel",      "CR:430", 14,  26, True),
    ("ignore",       "CR:357", 13,  30, True),
    ("reveal",       "CR:424", 13,  28, True),
    ("discard",      "CR:422", 12,  30, True),
    ("add",          "CR:429", 11,  30, True),
    ("stun",         "CR:423", 11,  24, True),
    ("banish",       "CR:427", 10,  28, True),
    ("exhaust",      "CR:414",  9,  16, True),
    ("gain_xp",      "CR:728",  8,  18, True),
    ("look_at",      "CR:128",  8,  15, True),
    ("score",        "CR:467",  8,  15, True),
    ("enter",        "CR:355",  7,  32, True),
    ("permission",   "CR:364",  7,  13, True),
    ("counter",      "CR:425",  7,  11, True),
    ("recall",       "CR:455",  6,  13, True),
    ("put",          "CR:108",  6,  10, True),
    ("heal",         "CR:418",  6,   9, True),
    # `create_token` is active, but it is not an op: a token spec inside a
    # selector carries it, because the census counts "Play three Recruit unit
    # tokens" as both `play` and `create_token` and a script should not have to
    # say it twice. See TOKENS and `_selector`.
    ("create_token", "CR:179", 41,  85, True),
    # declared, not active: the tail. Every one is a real thing a card says.
    ("spend",        "CR:728",  5,  17, False),
    ("empower",      "CR:441",  4,  16, False),
    ("attach",       "CR:434",  4,  14, False),
    ("use",          "CR:377",  3,   9, False),
    ("hide",         "CR:421",  3,   8, False),
    ("predict",      "CR:436",  3,   8, False),
    ("disempower",   "CR:442",  3,   7, False),
    ("burn",         "CR:440",  2,   7, False),
    ("become_copy",  "CR:438",  2,   6, False),
    ("set_stat",     "CR:477",  2,   6, False),
    ("modify_trigger", "CR:383", 2,   4, False),
    ("gain_control", "CR:477",  1,   7, False),
    ("detach",       "CR:435",  1,   5, False),
    ("win_game",     "CR:194",  1,   3, False),
    ("swap",         "CR:433",  1,   1, False),
    ("take_turn",    "CR:407",  1,   1, False),
    ("double",       "CR:432",  0,   6, False),
    ("modify_tag",   "CR:407",  0,   5, False),
    ("prevent",      "CR:437",  0,   4, False),
    ("name",         "CR:407",  0,   2, False),
    ("activate",     "CR:383",  0,   1, False),
    ("replace",      "CR:438",  0,   1, False),
    ("skip",         "CR:443",  0,   1, False),
])

#: The two game actions at 413-444 that no card's text names. The census found
#: them performed constantly and printed never: a deck runs out and its owner
#: Burns Out; tokens come into existence. They are engine actions, and naming
#: them here is what stops a compiler inventing a surface form for them.
ENGINE_ONLY = {
    "burn_out": ("CR:431", "a deck running out is a rule, not an instruction"),
    "create": ("CR:439", "a card prints 'play a Gold gear token', never 'create' one"),
}

#: Trigger events — census §3. A trigger is a SET of these plus an optional
#: frequency, because 18 of the 184 gauntlet trigger clauses name more than one
#: event and taking the first comma as the trigger's end drops the rest.
TRIGGERS = _atoms([
    ("play_self",       "CR:383", 63, 141, True),
    ("conquer",         "CR:383", 29,  50, True),
    ("move",            "CR:420", 14,  35, True),
    ("attack",          "CR:383", 12,  41, True),
    ("hold",            "CR:383", 12,  38, True),
    ("play_other",      "CR:383", 12,  33, True),
    ("defend",          "CR:383",  9,  16, True),
    ("die",             "CR:428",  8,  17, True),
    ("beginning_phase", "CR:383",  6,   8, True),
    ("win_combat",      "CR:466",  6,   7, True),
    ("delayed_next",    "CR:389",  3,   6, True),
    ("discard_trigger", "CR:422",  3,   4, True),
    ("end_of_turn",     "CR:383",  3,   6, True),
    ("targeted",        "CR:383",  3,   4, True),
    ("as_played",       "CR:355",  2,   2, True),
    ("become_state",    "CR:383",  2,   3, True),
    ("readied",         "CR:415",  2,   6, True),
    ("reveal_trigger",  "CR:424",  2,   2, True),
    ("stunned",         "CR:423",  2,   4, True),
    # `nth_time` and `frequency_only` are counted as events by the census and
    # are NOT events: CR 383.1.b's "the first time ... each turn" and 383.3.e's
    # "once each turn" modify an event. They are the `frequency` field, and the
    # 20th active atom is `nth_time` reached through it.
    ("nth_time",        "CR:383",  2,   2, True),
    ("frequency_only",  "CR:383",  1,   3, False),
    ("become_empowered", "CR:441", 1,   3, False),
    ("combat_damage",   "CR:417",  1,   2, False),
    ("combat_ends",     "CR:466",  1,   2, False),
    ("empower_other",   "CR:441",  1,   4, False),
    ("equip_trigger",   "CR:818",  1,   2, False),
    ("hide_trigger",    "CR:421",  1,   2, False),
    ("score_trigger",   "CR:467",  1,   2, False),
    ("showdown_begins", "CR:341",  1,   2, False),
    ("banish_trigger",  "CR:427",  0,   2, False),
    ("buffed",          "CR:426",  0,   4, False),
    ("burn_trigger",    "CR:440",  0,   1, False),
    ("draw_trigger",    "CR:413",  0,   1, False),
    ("kill_trigger",    "CR:428",  0,   2, False),
    ("leaves",          "CR:108",  0,   2, False),
    ("phase_other",     "CR:383",  0,   1, False),
    ("recycle_trigger", "CR:416",  0,   2, False),
    ("start_of_turn",   "CR:383",  0,   1, False),
    ("use_ability",     "CR:377",  0,   1, False),
])

#: Selector atoms — census §5, on four independent axes plus `self`. The axes
#: are what keeps the count at 38 rather than one selector per printed phrase.
SELECTORS = _atoms([
    ("self",             "CR:407", 330, 859, True),
    ("type:unit",        "CR:407", 259, 627, True),
    ("side:friendly",    "CR:407", 176, 405, True),
    ("by_state",         "CR:407", 147, 309, True),
    ("at:here",          "CR:198",  66, 136, True),
    ("side:enemy",       "CR:407",  65, 184, True),
    ("type:battlefield", "CR:198",  61, 178, True),
    ("type:token",       "CR:179",  43,  91, True),
    ("all",              "CR:407",  42, 131, True),
    ("type:card",        "CR:407",  42,  92, True),
    ("type:gear",        "CR:407",  42, 108, True),
    ("type:spell",       "CR:407",  32,  84, True),
    ("zone:hand",        "CR:108",  32,  65, True),
    ("another",          "CR:407",  29,  84, True),
    ("at:base",          "CR:198",  27,  55, True),
    ("type:rune",        "CR:407",  25,  55, True),
    ("count:two_plus",   "CR:407",  24,  41, True),
    ("zone:trash",       "CR:108",  24,  49, True),
    ("by_tag",           "CR:407",  22,  72, True),
    ("at:battlefield",   "CR:198",  20,  91, True),
    ("owner",            "CR:407",  20,  43, True),
    ("up_to_n",          "CR:355",  18,  28, True),
    ("zone:deck",        "CR:108",  16,  33, True),
    ("by_cost",          "CR:356",  15,  48, True),
    ("side:any",         "CR:407",  15,  42, True),
    # declared, not active
    ("type:ability",     "CR:360",  13,  36, False),
    ("zone:top_of_deck", "CR:108",  12,  19, False),
    ("at:location",      "CR:198",  10,  17, False),
    ("by_keyword",       "CR:800",   9,  25, False),
    ("by_might",         "CR:477",   7,  24, False),
    ("negated",          "CR:407",   6,   9, False),
    ("at:showdown",      "CR:341",   4,   7, False),
    ("any_number",       "CR:355",   3,  13, False),
    ("zone:board",       "CR:108",   3,   4, False),
    ("type:legend",      "CR:407",   2,   6, False),
    ("type:champion",    "CR:407",   2,   2, False),
    ("zone:champion",    "CR:108",   2,   2, False),
    ("zone:banishment",  "CR:108",   0,   3, False),
])

#: Condition atoms — census §6.
CONDITIONS = _atoms([
    ("controls",             "CR:364", 11, 37, True),
    ("state_of_object",      "CR:364",  9, 13, True),
    ("alone",                "CR:364",  7,  9, True),
    ("if_you_do",            "CR:364",  7, 20, True),
    ("paid_additional_cost", "CR:202",  7, 15, True),
    ("state_of_self",        "CR:364",  7, 23, True),
    ("would_event",          "CR:369",  5, 12, True),
    ("is_type",              "CR:364",  4, 10, True),
    ("already",              "CR:364",  3,  3, True),
    ("cant",                 "CR:364",  3,  5, True),
    ("score_threshold",      "CR:467",  3,  5, True),
    ("unless_pays",          "CR:444",  3,  5, True),
    ("comparison",           "CR:364",  2,  3, True),
    ("has_played",           "CR:419",  2,  4, True),
    ("count_threshold",      "CR:364",  1,  7, True),
    ("empty",                "CR:364",  1,  1, True),
    ("has_keyword",          "CR:800",  1,  1, True),
    ("phase_check",          "CR:364",  1,  4, False),
    ("played_from",          "CR:419",  1,  1, False),
    ("spent",                "CR:202",  1,  7, False),
    ("whose_turn",           "CR:364",  1, 10, False),
    ("this_killed_it",       "CR:428",  0,  1, False),
    ("zone_of_object",       "CR:108",  0,  6, False),
])

#: Choice forms — census §7. `choose_mode` is the one most likely to be
#: over-built relative to its use: once in the gauntlet, five times in the pool.
CHOICES = _atoms([
    ("may",            "CR:355", 82, 181, True),
    ("choose_object",  "CR:355", 41, 107, True),
    ("up_to",          "CR:355", 18,  28, True),
    ("opponent_picks", "CR:355",  4,   6, True),
    ("any_number",     "CR:355",  3,  13, False),
    ("choose_mode",    "CR:355",  1,  10, False),
    ("unless_pays",    "CR:444",  1,   2, False),
    ("order",          "CR:355",  1,   1, False),
])

#: Cost forms — census §8. Seven of the thirteen are a game action used as a
#: cost, and they cite the same rule the action does: CR 355.10.c.1's
#: "[do X] to [do Y]" says a cost IS an instruction, in a cost position.
COSTS = _atoms([
    ("energy",          "CR:444", 77, 210, True),
    ("power_domain",    "CR:444", 42, 102, True),
    ("exhaust_self",    "CR:414", 26,  92, True),
    ("power_any",       "CR:444", 23,  63, True),
    ("additional_cost", "CR:202", 23,  47, True),
    ("recycle_cost",    "CR:416", 19,  38, True),
    ("discard_cost",    "CR:422", 14,  34, True),
    ("banish_cost",     "CR:427", 11,  30, True),
    ("sacrifice",       "CR:428", 10,  16, True),
    ("free",            "CR:357",  8,  16, True),
    ("spend_xp",        "CR:728",  5,  13, False),
    ("power_own",       "CR:444",  5,   7, False),
    ("spend_buff",      "CR:701",  2,   5, False),
])

#: Replacement kinds — census §10. Each is its own node type, because the two
#: commonest are not the general machinery at all: a cost reduction is
#: arithmetic in the cost calculation and `enters ready` is a flag set as a
#: permanent arrives. Only `would` and `instead` have to intercept an event,
#: and those are 22 gauntlet clauses across 16 cards.
REPLACEMENTS = _atoms([
    ("cost_replacement", "CR:367", 19, 44, True),
    ("enters_modified",  "CR:367", 17, 57, True),
    ("instead",          "CR:369", 15, 34, True),
    ("ignoring_cost",    "CR:367",  8, 17, True),
    ("would",            "CR:369",  7, 19, True),
    ("as_enters",        "CR:367",  3,  9, True),
    ("prevent_damage",   "CR:437",  0,  2, False),
    ("replace_token",    "CR:438",  0,  1, False),
    ("skip_event",       "CR:443",  0,  1, False),
])

#: Modifier durations — census §5b. The other half of `give_might(n, until)`.
DURATIONS = _atoms([
    ("this_turn",   "CR:477", 77, 194, True),
    ("permanent",   "CR:701", 19,  50, True),
    ("while_state", "CR:477", 14,  40, True),
    ("until_event", "CR:477",  3,   3, True),
    ("this_combat", "CR:459",  1,   2, True),
    ("next_turn",   "CR:477",  0,   2, False),
])

#: The CR keyword glossary, 805-829. All 25 appear in the gauntlet. The kind is
#: the rules' own classification, and the kind IS the construct: eight passives,
#: six triggered abilities, three dependent, two permissive, two activated, two
#: optional additional costs, one action prerequisite, one deck constraint.
#: That is eight kinds of thing, not 25 more primitives.
KEYWORD_KINDS = ("passive", "triggered", "dependent", "permissive", "activated",
                 "optional_additional_cost", "action_prerequisite", "deck_constraint")

KEYWORDS = {
    "Accelerate":   ("CR:805", "optional_additional_cost", False),
    "Action":       ("CR:806", "permissive", False),
    "Assault":      ("CR:807", "passive", True),
    "Deathknell":   ("CR:808", "triggered", False),
    "Deflect":      ("CR:809", "passive", True),
    "Ganking":      ("CR:810", "passive", False),
    "Hidden":       ("CR:811", "action_prerequisite", False),
    "Legion":       ("CR:812", "dependent", False),
    "Reaction":     ("CR:813", "permissive", False),
    "Shield":       ("CR:814", "passive", True),
    "Tank":         ("CR:815", "passive", False),
    "Temporary":    ("CR:816", "triggered", False),
    "Vision":       ("CR:817", "triggered", False),
    "Equip":        ("CR:818", "activated", False),
    "Quick-Draw":   ("CR:819", "triggered", False),
    "Repeat":       ("CR:820", "optional_additional_cost", False),
    "Weaponmaster": ("CR:821", "triggered", False),
    "Ambush":       ("CR:822", "passive", False),
    "Hunt":         ("CR:823", "triggered", True),
    "Level":        ("CR:824", "dependent", True),
    "Unique":       ("CR:825", "deck_constraint", False),
    "Backline":     ("CR:826", "passive", False),
    "Empower":      ("CR:827", "activated", False),
    "Empowered":    ("CR:828", "dependent", False),
    "Flow":         ("CR:829", "passive", False),
}

#: The six keywords whose ability is a TRIGGER. Counting these is what takes
#: "cards with more than one trigger" from 6 to 15 in the gauntlet, and the
#: event each one fires on is the rules', not a guess.
KEYWORD_TRIGGERS = {
    "Deathknell": ("die",),
    "Temporary": ("beginning_phase",),
    "Vision": ("play_self",),
    "Quick-Draw": ("play_self",),
    "Weaponmaster": ("play_self",),
    "Hunt": ("conquer", "hold"),
}

#: Bracketed in the corpus, set in the keyword font, and NOT a keyword: CR
#: 805-829 does not define it. `Mighty` is a derived STATE (CR 706-711: a unit
#: is Mighty while its Might is 5 or more). A DSL that builds its keyword table
#: by scanning brackets invents a 26th keyword; this table is why this one
#: cannot. The same goes for the game actions the corpus sets in that font.
NOT_KEYWORDS = {
    "Mighty": ("CR:706", 'a derived state — use a selector state or `{"cond": "state_of_object", "state": "mighty"}`'),
    "Add": ("CR:429", 'a game action — use {"op": "add"}'),
    "Stun": ("CR:423", 'a game action — use {"op": "stun"}'),
    "Buff": ("CR:426", 'a game action — use {"op": "buff"}'),
    "Predict": ("CR:436", "a game action, reserved outside the 95% cut"),
    "Burn": ("CR:440", "a game action, reserved outside the 95% cut"),
}

#: Object states a selector or a condition may name. Read out of the rules, not
#: out of the card text: `by_state` is one census atom over this vocabulary.
STATES = ("ready", "exhausted", "stunned", "hidden", "empowered", "damaged",
          "buffed", "mighty", "attacking", "defending", "equipped", "attached",
          "contested", "occupied", "token", "in_combat")

#: Token specs — census §9b. Closed, because a token that is not on this list is
#: one the corpus never prints, and a compiler inventing one would be inventing
#: a card. `Baron Pit` is a battlefield token; the rest are units and gear.
TOKENS = {
    "Gold": ("gear", 10, 25),
    "Recruit": ("unit", 9, 15),
    "Sand Soldier": ("unit", 5, 6),
    "Sprite": ("unit", 4, 8),
    "Reflection": ("unit", 2, 3),
    "Shadow Clone": ("unit", 2, 3),
    "Bird": ("unit", 1, 6),
    "Mech": ("unit", 1, 6),
    "Baron Pit": ("battlefield", 1, 1),
    "Tentacle": ("unit", 1, 1),
    "Brush": ("battlefield", 0, 1),
}

#: Zones a script may name (CR 106-108), and locations on the board (CR 198).
#: One name per census `zone:` atom and no more: a zone this vocabulary can
#: write but the census never counted would be vocabulary nobody measured.
#: `zone:top_of_deck` is deliberately absent — it is the deck plus a `position`,
#: which is the shape the census's own `put(zone, position)` primitive has, and
#: spelling it as a zone would give the vocabulary two ways to say one thing.
ZONES = ("hand", "trash", "deck", "banishment", "champion", "board")
LOCATIONS = ("base", "here", "battlefield", "location", "showdown")
SIDES = ("friendly", "enemy", "any")
TYPES = ("unit", "gear", "spell", "rune", "battlefield", "token", "card",
         "ability", "legend", "champion")
SEATS = ("you", "opponent", "each", "controller", "owner", "me")
COMPARISONS = ("<", "<=", "=", ">=", ">")

#: The closed predicate vocabulary for `restriction` and `permission`. Not in
#: the census — it counted the primitive, not its argument — so it is grown one
#: card at a time and each row names the card that needed it. A predicate with
#: no card behind it is a predicate nobody measured.
PREDICATES = {
    "be_chosen_by_enemy": "Akali, Silent · Baron Nashor · [Deflect]",
    "play_to_occupied_battlefield": "Arachnoid Horror",
    "move_battlefield_to_battlefield": "[Ganking]",
    "hide_additional_card": "Bandle Tree",
    "be_assigned_damage_first": "[Tank]",
    "be_assigned_damage_last": "[Backline]",
    "deal_combat_damage": "[Stun]",
    "be_reacted_to": "Seal of Unity",
    "play_from_trash": "[Flow] · Last Rites",
}

#: What a scenario test may ask the engine to do, and what it may assert. Both
#: closed, and validated now: the interpreter (#25) executes them, and a test
#: whose shape nobody checked until then is a test written against a guess.
TEST_ACTIONS = ("play", "activate", "trigger", "move", "standard_move",
                "begin_turn", "end_turn", "combat", "showdown", "score",
                "conquer", "hold", "discard", "kill", "resolve", "attack", "defend")
TEST_EXPECTATIONS = ("zone_count", "zone_has", "zone_lacks", "board_count",
                     "state", "might", "damage", "buffs", "points", "xp",
                     "energy", "power", "chain", "cost", "keyword", "refused")


# ---------------------------------------------------------------------------
# Error records
# ---------------------------------------------------------------------------
#
# Codes are part of the interface: the repair loop switches on them. Adding one
# is a schema change; the selftest asserts every code below is produced by some
# deliberately broken script, so a code nobody can reach cannot be added here
# and quietly believed in.

CODES = (
    "schema_not_recognised",   # wrong or missing `schema`
    "missing_field",           # a required key is absent
    "unexpected_field",        # a key the schema does not define
    "wrong_type",              # right key, wrong JSON type
    "unknown_atom",            # a token no census table contains
    "reserved_atom",           # a real census atom outside the active cut
    "engine_only_atom",        # a game action no card's text names
    "not_a_keyword",           # bracketed in the corpus, not in CR 805-829
    "unknown_keyword",         # not a keyword at all
    "keyword_kind",            # a keyword used in the wrong kind of position
    "keyword_parameter",       # a parameter on a keyword that takes none, or none on one that does
    "bad_citation",            # malformed, or a section not in SECTIONS
    "missing_citation",        # a node with no `cites`
    "wrong_citation",          # `cites` omits the construct's own rule
    "bad_value",               # out of range, empty, or contradictory
    "unknown_card",            # not a card in the vendored pool
    "clause_not_in_text",      # a clause whose words are not in the printed text
    "bad_clause_ref",          # a clause pointing at a node that does not exist
    "version_stale",           # `version` is not the hash of the body
    "bad_test",                # a scenario test the interpreter could not run
    "filename_mismatch",       # the file is not named after the card it scripts
    "unreadable",              # the file is not JSON at all
)


def error(code, path, message, token=None, expected=None, cite=None):
    """One structured error record.

    Dict rather than an exception, and returned rather than raised: the repair
    loop needs every error in a script, not the first one, and it needs them as
    data. `expected` is the closed set the token should have come from — which
    is the field that makes an automated repair possible at all.
    """
    record = {"code": code, "path": path, "message": message}
    if token is not None:
        record["token"] = token
    if expected is not None:
        record["expected"] = sorted(expected)[:40]
    if cite is not None:
        record["cite"] = cite
    return record


class _Walk(object):
    """Collects errors and the atoms a script exercised, along one walk."""

    def __init__(self, lookup):
        self.errors = []
        self.atoms = set()
        self.lookup = lookup
        self.node_paths = set()
        #: How many keyword-gated abilities enclose the node being walked. A
        #: gated passive's modifier lasts exactly as long as its gate holds, so
        #: inside one a `while_state` duration takes its state FROM the gate
        #: rather than repeating it — `[Empowered][>] I have +1 {M}` says the
        #: state once, and so does the script.
        self.gated = 0

    def add(self, *a, **kw):
        self.errors.append(error(*a, **kw))

    def atom(self, category, name):
        self.atoms.add("%s:%s" % (category, name))


# ---------------------------------------------------------------------------
# Node field specifications
# ---------------------------------------------------------------------------
#
# One entry per construct. `req` are required keys, `opt` optional; the value is
# the checker name. Keeping these as data rather than as code is what lets the
# error record name the expected set without a second table to drift from.

_EFFECTS = {
    "draw":        dict(req={"n": "value"}, opt={"seat": "seat"}),
    "exhaust":     dict(req={"what": "selector"}, opt={}),
    "ready":       dict(req={"what": "selector"}, opt={}),
    "recycle":     dict(req={"what": "selector"}, opt={"n": "value", "from": "zone"}),
    "deal":        dict(req={"n": "value", "to": "selector"},
                        opt={"source": "selector", "split": "bool"}),
    "heal":        dict(req={"what": "selector"}, opt={}),
    "play":        dict(req={"what": "selector"},
                        opt={"n": "value", "to": "location", "from": "zone",
                             "enters": "state", "cost": "costs", "ignoring": "cost_kind"}),
    "move":        dict(req={"what": "selector"},
                        opt={"to": "location", "swap_with": "selector"}),
    "discard":     dict(req={"n": "value"}, opt={"seat": "seat", "what": "selector"}),
    "stun":        dict(req={"what": "selector"}, opt={}),
    "reveal":      dict(req={}, opt={"what": "selector", "n": "value", "from": "zone",
                                     "position": "position", "until_find": "selector",
                                     "bind": "name"}),
    "counter":     dict(req={"what": "selector"}, opt={"unless": "condition"}),
    "buff":        dict(req={"what": "selector"}, opt={"n": "value"}),
    "banish":      dict(req={"what": "selector"}, opt={}),
    "kill":        dict(req={"what": "selector"}, opt={}),
    "add":         dict(req={}, opt={"power": "domain", "n": "value", "token": "token",
                                     "to": "location"}),
    "channel":     dict(req={"n": "value"}, opt={"exhausted": "bool", "seat": "seat"}),
    "pay":         dict(req={"cost": "costs"}, opt={"seat": "seat"}),
    "give_might":  dict(req={"what": "selector", "n": "value", "until": "duration"},
                        opt={"min": "int", "state": "state", "event": "trigger_event"}),
    # The parameter rides on the keyword reference (`{"keyword": "Assault",
    # "value": 2}`) rather than on a sibling field, so a keyword that must carry
    # a number cannot be granted without one.
    "grant_keyword": dict(req={"what": "selector", "keyword": "keyword", "until": "duration"},
                          opt={"state": "state", "event": "trigger_event"}),
    "modify_cost": dict(req={"what": "selector", "delta": "int"},
                        opt={"min": "int", "affects": "cost_kind"}),
    "restriction": dict(req={"who": "selector", "cant": "predicate"},
                        opt={"unless": "condition"}),
    "permission":  dict(req={"who": "selector", "may": "predicate"},
                        opt={"when": "condition"}),
    "return_to":   dict(req={"what": "selector", "to": "zone"}, opt={"seat": "seat"}),
    "put":         dict(req={"what": "selector", "to": "zone"},
                        opt={"position": "position", "n": "value", "from": "zone"}),
    "look_at":     dict(req={"n": "value", "from": "zone"},
                        opt={"position": "position", "bind": "name"}),
    "gain_xp":     dict(req={"n": "value"}, opt={"seat": "seat"}),
    "score":       dict(req={"n": "value"}, opt={"seat": "seat"}),
    "enter":       dict(req={"where": "location"}, opt={"what": "selector", "state": "state"}),
    "recall":      dict(req={"what": "selector"}, opt={}),
    "ignore":      dict(req={"affects": "cost_kind"}, opt={"of": "selector"}),
    "choose":      dict(req={"what": "selector"}, opt={"n": "value", "bind": "name"}),
}

_CHOICE_NODES = {
    "may":            dict(req={"do": "effects"}, opt={"cost": "costs", "seat": "seat"}),
    # `targets` is checked by `_choice` rather than listed as required, so the
    # error a script gets carries CR 355.10 — the rule that decides the question
    # — instead of a bare "this field is missing".
    "choose_object":  dict(req={"what": "selector", "do": "effects"},
                           opt={"bind": "name", "n": "value", "targets": "bool"}),
    "up_to":          dict(req={"n": "value", "what": "selector", "do": "effects"},
                           opt={"bind": "name", "targets": "bool"}),
    "opponent_picks": dict(req={"what": "selector", "do": "effects"},
                           opt={"bind": "name", "seat": "seat"}),
}

_COST_NODES = {
    "energy":          dict(req={"n": "int"}, opt={}),
    "power_domain":    dict(req={"domain": "domain", "n": "int"}, opt={}),
    "power_any":       dict(req={"n": "int"}, opt={}),
    "exhaust_self":    dict(req={}, opt={"what": "selector"}),
    "recycle_cost":    dict(req={"n": "int"}, opt={"from": "zone", "what": "selector"}),
    "discard_cost":    dict(req={"n": "int"}, opt={"what": "selector"}),
    "banish_cost":     dict(req={}, opt={"what": "selector"}),
    "sacrifice":       dict(req={"what": "selector"}, opt={}),
    "additional_cost": dict(req={"pay": "costs"}, opt={"optional": "bool", "keyword": "keyword"}),
    "free":            dict(req={}, opt={}),
}

_ABILITIES = {
    "passive":     dict(req={"effect": "effects"}, opt={}),
    "activated":   dict(req={"cost": "costs", "effect": "effects"},
                        opt={"frequency": "frequency", "timing": "keyword",
                             "keyword": "keyword"}),
    "triggered":   dict(req={"trigger": "trigger", "effect": "effects"},
                        opt={"keyword": "keyword"}),
    "reflexive":   dict(req={"effect": "effects"}, opt={"trigger": "trigger"}),
    "delayed":     dict(req={"trigger": "trigger", "effect": "effects"}, opt={}),
    # the six replacement kinds, each its own node type
    "cost_replacement": dict(req={"applies_to": "selector", "delta": "int"},
                             opt={"min": "int", "affects": "cost_kind", "when": "condition"}),
    "enters_modified":  dict(req={"applies_to": "selector", "enters": "state"},
                             opt={"when": "condition", "until": "duration",
                                  "frequency": "frequency"}),
    # `event` is optional here and required on `would`: CR 369.1 gives both the
    # same identifying words, but "instead" is also printed for the narrow shape
    # where the replaced thing is the instruction the clause itself just gave
    # ("Give a unit +2 {M}. If it's [Empowered], give it +4 {M} instead"). With no
    # event named, the replaced event is the sibling instruction.
    "instead":          dict(req={"applies_to": "selector", "do": "effects"},
                             opt={"event": "trigger_event", "when": "condition",
                                  "optional": "bool", "cost": "costs",
                                  "until": "duration", "frequency": "frequency"}),
    "would":            dict(req={"event": "trigger_event", "applies_to": "selector",
                                  "do": "effects"},
                             opt={"when": "condition", "optional": "bool", "cost": "costs",
                                  "seat": "seat", "until": "duration",
                                  "frequency": "frequency"}),
    "as_enters":        dict(req={"do": "effects"}, opt={"when": "condition"}),
    "ignoring_cost":    dict(req={"applies_to": "selector", "affects": "cost_kind"},
                             opt={"when": "condition"}),
}

#: Which census atoms each ability kind exercises. A replacement kind is its own
#: atom AND usually the primitive it performs, because the census counts the
#: clause in both tables.
_ABILITY_ATOMS = {
    "cost_replacement": (("replacement", "cost_replacement"), ("primitive", "modify_cost")),
    "enters_modified": (("replacement", "enters_modified"), ("primitive", "enter")),
    "instead": (("replacement", "instead"),),
    # A `would` ability replaces the event it intercepts, which is the word the
    # card prints: every gauntlet `would` clause also says "instead", and the
    # census counts the clause in the replacement table twice and in the
    # condition table once.
    "would": (("replacement", "would"), ("replacement", "instead"),
              ("condition", "would_event")),
    "as_enters": (("replacement", "as_enters"), ("trigger", "as_played")),
    "ignoring_cost": (("replacement", "ignoring_cost"), ("primitive", "ignore"),
                      ("cost", "free")),
}

_SELECTOR_FIELDS = {
    "self": "bool", "side": "side", "type": "type", "at": "location",
    "zone": "zone", "position": "position", "state": "state", "tag": "name",
    "cost": "bound", "might": "bound", "keyword": "keyword", "token": "token",
    "another": "bool", "all": "bool", "count": "int", "up_to": "int",
    "any_number": "bool", "owner": "seat", "not": "selector", "rest": "bool",
    "bind": "name", "ref": "name", "targets": "bool", "n": "int",
}

#: The selector field that carries each census selector atom.
_SELECTOR_ATOM_OF = {
    "self": "self", "another": "another", "all": "all", "tag": "by_tag",
    "cost": "by_cost", "might": "by_might", "keyword": "by_keyword",
    "state": "by_state", "owner": "owner", "not": "negated",
    "any_number": "any_number", "up_to": "up_to_n",
}

_CONDITIONS = {
    "controls":             dict(req={"what": "selector"}, opt={"n": "int", "op": "comparison"}),
    "state_of_object":      dict(req={"what": "selector", "state": "state"}, opt={"negated": "bool"}),
    "state_of_self":        dict(req={"state": "state"}, opt={"negated": "bool"}),
    "alone":                dict(req={"what": "selector"}, opt={"where": "location"}),
    "if_you_do":            dict(req={}, opt={}),
    "paid_additional_cost": dict(req={}, opt={"keyword": "keyword"}),
    "would_event":          dict(req={"event": "trigger_event"}, opt={"what": "selector"}),
    "is_type":              dict(req={"what": "selector", "type": "type"},
                                 opt={"tag": "name", "keyword": "keyword",
                                      "negated": "bool"}),
    "already":              dict(req={"what": "selector"},
                                 opt={"state": "state", "negated": "bool"}),
    "cant":                 dict(req={}, opt={"what": "selector"}),
    "score_threshold":      dict(req={"seat": "seat"}, opt={"within": "int", "at_least": "int"}),
    "unless_pays":          dict(req={"seat": "seat", "cost": "costs"}, opt={}),
    "comparison":           dict(req={"left": "value", "op": "comparison", "right": "value"}, opt={}),
    "has_played":           dict(req={"what": "selector"}, opt={"n": "int", "this_turn": "bool"}),
    "count_threshold":      dict(req={"what": "selector", "op": "comparison", "n": "int"}, opt={}),
    "empty":                dict(req={}, opt={"zone": "zone", "what": "selector", "seat": "seat"}),
    "has_keyword":          dict(req={"what": "selector", "keyword": "keyword"}, opt={"value": "int"}),
}

_TRIGGER_FIELDS = {
    "events": "events", "who": "who", "what": "selector", "where": "location",
    "condition": "condition", "frequency": "frequency", "keyword": "keyword",
    "seat": "seat", "state": "state",
}

#: CR 383.4.d.2 and 383.4.c.2: `When I hold` and `When you hold` are the same
#: words and a different subscription — the first fires only from a unit present
#: at the battlefield, the second from anything referencing the player. The
#: census counts the event; only the rules say who is listening, so the DSL
#: makes the listener a required field rather than a convention.
WHO = ("me", "you", "any", "enemy", "friendly")


# ---------------------------------------------------------------------------
# The walk
# ---------------------------------------------------------------------------

def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _keys(node, spec, path, w, kind_key):
    """Required/unexpected key check for one node against its spec."""
    allowed = set(spec["req"]) | set(spec["opt"]) | {kind_key, "cites", "note", "when", "id"}
    for key in sorted(spec["req"]):
        if key not in node:
            w.add("missing_field", "%s.%s" % (path, key),
                  "%r requires %r" % (node.get(kind_key), key),
                  token=None, expected=sorted(spec["req"]))
    for key in sorted(node):
        if key not in allowed:
            w.add("unexpected_field", "%s.%s" % (path, key),
                  "%r is not a field of %r" % (key, node.get(kind_key)),
                  token=key, expected=sorted(allowed))


def _field(value, checker, path, w):
    """Check one field value against one checker name."""
    if checker == "int":
        if not _is_int(value):
            w.add("wrong_type", path, "expected an integer", token=repr(value))
    elif checker == "bool":
        if not isinstance(value, bool):
            w.add("wrong_type", path, "expected true or false", token=repr(value))
    elif checker == "name":
        if not isinstance(value, str) or not value:
            w.add("wrong_type", path, "expected a non-empty string", token=repr(value))
    elif checker == "value":
        _value(value, path, w)
    elif checker == "selector":
        _selector(value, path, w)
    elif checker == "condition":
        _condition(value, path, w)
    elif checker == "effects":
        _effects(value, path, w)
    elif checker == "costs":
        _costs(value, path, w)
    elif checker == "trigger":
        _trigger(value, path, w)
    elif checker == "frequency":
        _frequency(value, path, w)
    elif checker == "token":
        _token(value, path, w)
    elif checker == "duration":
        _enum_atom(value, DURATIONS, "duration", path, w)
    elif checker == "trigger_event":
        _enum_atom(value, TRIGGERS, "trigger", path, w)
    elif checker == "keyword":
        _keyword(value, path, w)
    elif checker == "predicate":
        if value not in PREDICATES:
            w.add("unknown_atom", path, "no such predicate", token=value,
                  expected=PREDICATES.keys(), cite="CR:364")
    elif checker == "bound":
        _bound(value, path, w)
    elif checker == "events":
        _events(value, path, w)
    elif checker in ("zone", "location", "state", "side", "type", "seat",
                     "position", "domain", "comparison", "who", "cost_kind"):
        _enum(value, checker, path, w)
    else:                                   # pragma: no cover - programming error
        raise AssertionError("no checker named %r" % checker)


_ENUMS = {
    "zone": ZONES,
    "location": LOCATIONS,
    "state": STATES,
    "side": SIDES,
    "type": TYPES,
    "seat": SEATS,
    "position": ("top", "bottom"),
    "domain": cards.DOMAINS + (cards.COLORLESS, "any"),
    "comparison": COMPARISONS,
    "who": WHO,
    "cost_kind": ("energy", "power", "total"),
}


def _enum(value, checker, path, w):
    allowed = _ENUMS[checker]
    if value not in allowed:
        w.add("unknown_atom", path, "not one of the %s vocabulary" % checker,
              token=value, expected=allowed)
        return
    # Several enums ARE census selector atoms, and using one exercises it.
    for category, prefix in (("zone", "zone:"), ("location", "at:"), ("type", "type:"),
                             ("side", "side:")):
        if checker == category:
            _atom_or_reserved(prefix + str(value), SELECTORS, "selector", path, w)


def _atom_or_reserved(name, table, category, path, w):
    atom = table.get(name)
    if atom is None:
        w.add("unknown_atom", path, "no census atom named %r" % (name,),
              token=name, expected=_active(table))
        return False
    if not atom.active:
        w.add("reserved_atom", path,
              "%r is a census atom (%d gauntlet clause(s), %d across the pool) but is "
              "outside this vocabulary's active cut — mark the clause `unsupported` "
              "rather than reaching for it" % (name, atom.gauntlet, atom.pool),
              token=name, expected=_active(table), cite=atom.cite)
        return False
    w.atom(category, name)
    return True


def _enum_atom(value, table, category, path, w):
    if not isinstance(value, str):
        w.add("wrong_type", path, "expected a %s name" % category, token=repr(value))
        return
    _atom_or_reserved(value, table, category, path, w)


def _value(value, path, w):
    """An integer, or one of the three count-scaled forms the census found."""
    if _is_int(value):
        return
    if not isinstance(value, dict):
        w.add("wrong_type", path, "expected an integer or a scaled value",
              token=repr(value), expected=("for_each", "might_of", "cost_of"))
        return
    forms = {"for_each": "for_each", "might_of": "might_of", "cost_of": "cost_of"}
    named = [k for k in value if k in forms]
    if len(named) != 1:
        w.add("bad_value", path, "a scaled value names exactly one form",
              token=json.dumps(value, sort_keys=True), expected=forms)
        return
    form = named[0]
    for key in sorted(value):
        if key not in (form, "per", "min", "max"):
            w.add("unexpected_field", "%s.%s" % (path, key),
                  "%r is not a field of a %s value" % (key, form), token=key,
                  expected=(form, "per", "min", "max"))
    _selector(value[form], "%s.%s" % (path, form), w)
    if form == "for_each":
        w.atom("modifier", "for_each")


def _bound(value, path, w):
    """`{"op": "<=", "n": 3}` — a comparison on a numeric trait."""
    if not isinstance(value, dict):
        w.add("wrong_type", path, "expected a bound", token=repr(value),
              expected=("op", "n"))
        return
    for key in ("op", "n"):
        if key not in value:
            w.add("missing_field", "%s.%s" % (path, key), "a bound needs %r" % key,
                  expected=("op", "n"))
    for key in sorted(value):
        if key not in ("op", "n"):
            w.add("unexpected_field", "%s.%s" % (path, key), "not a field of a bound",
                  token=key, expected=("op", "n"))
    if "op" in value:
        _enum(value["op"], "comparison", "%s.op" % path, w)
    if "n" in value and not _is_int(value["n"]):
        w.add("wrong_type", "%s.n" % path, "expected an integer", token=repr(value["n"]))


def _token(value, path, w):
    """A token spec. Closed: the corpus prints eleven, and no card invents one."""
    if not isinstance(value, dict):
        w.add("wrong_type", path, "expected a token spec", token=repr(value),
              expected=TOKENS.keys())
        return
    name = value.get("name")
    if name not in TOKENS:
        w.add("unknown_atom", "%s.name" % path, "no such token in the corpus",
              token=name, expected=TOKENS.keys(), cite="CR:179")
        return
    kind, _, _ = TOKENS[name]
    if value.get("type") != kind:
        w.add("bad_value", "%s.type" % path,
              "the corpus prints %r as a %s token" % (name, kind),
              token=value.get("type"), expected=(kind,), cite="CR:179")
    allowed = {"name", "type", "might", "keywords", "tags", "text", "state"}
    for key in sorted(value):
        if key not in allowed:
            w.add("unexpected_field", "%s.%s" % (path, key), "not a field of a token spec",
                  token=key, expected=allowed)
    if kind == "unit" and not _is_int(value.get("might")):
        w.add("missing_field", "%s.might" % path, "a unit token prints a Might",
              expected=("might",), cite="CR:179")
    for i, kw in enumerate(value.get("keywords") or []):
        _keyword(kw, "%s.keywords[%d]" % (path, i), w)
    if "state" in value:
        _enum(value["state"], "state", "%s.state" % path, w)
    w.atom("token", name)
    w.atom("primitive", "create_token")


def _keyword(value, path, w):
    """A keyword reference: a name, or a name with its numeric parameter."""
    if isinstance(value, dict):
        name, param = value.get("keyword"), value.get("value")
        for key in sorted(value):
            if key not in ("keyword", "value", "cost", "cites", "note"):
                w.add("unexpected_field", "%s.%s" % (path, key),
                      "not a field of a keyword reference", token=key,
                      expected=("keyword", "value", "cost", "cites", "note"))
        if "cost" in value:
            # `[Repeat] {2}` and `[Accelerate] {1}{R}` print a cost beside the
            # keyword: the keyword says what happens, the card says for how much.
            _costs(value["cost"], "%s.cost" % path, w)
    else:
        name, param = value, None
    if name in NOT_KEYWORDS:
        cite, why = NOT_KEYWORDS[name]
        w.add("not_a_keyword", path,
              "%r is bracketed in the corpus and is not in CR 805-829: %s" % (name, why),
              token=name, expected=sorted(KEYWORDS), cite=cite)
        return
    if name not in KEYWORDS:
        w.add("unknown_keyword", path, "no such keyword in CR 805-829", token=name,
              expected=sorted(KEYWORDS), cite="CR:800")
        return
    cite, kind, takes_param = KEYWORDS[name]
    if takes_param and param is None:
        w.add("keyword_parameter", path, "[%s N] takes a numeric parameter" % name,
              token=name, cite=cite)
    if not takes_param and param is not None:
        w.add("keyword_parameter", path, "[%s] takes no parameter" % name,
              token=repr(param), cite=cite)
    if param is not None and not _is_int(param):
        w.add("wrong_type", "%s.value" % path, "a keyword parameter is a number",
              token=repr(param))
    if isinstance(value, dict):
        _cites(value, cite, path, w, required=False)
    w.atom("keyword", name)


def _events(value, path, w):
    if not isinstance(value, list) or not value:
        w.add("bad_value", path, "a trigger names at least one event",
              token=repr(value), expected=_active(TRIGGERS))
        return
    for i, name in enumerate(value):
        _enum_atom(name, TRIGGERS, "trigger", "%s[%d]" % (path, i), w)


def _frequency(value, path, w):
    """CR 383.1.b's "the first time ... each turn" and 383.3.e's "once each turn".

    Both are modifiers on an event, not events, which is why the census's
    `nth_time` and `frequency_only` rows land here instead of in `events`.
    """
    if not isinstance(value, dict):
        w.add("wrong_type", path, "expected a frequency", token=repr(value),
              expected=("nth", "limit", "per"))
        return
    named = [k for k in ("nth", "limit") if k in value]
    if len(named) != 1:
        w.add("bad_value", path, "a frequency is exactly one of `nth` or `limit`",
              token=json.dumps(value, sort_keys=True), expected=("nth", "limit"),
              cite="CR:383")
        return
    for key in sorted(value):
        if key not in ("nth", "limit", "per"):
            w.add("unexpected_field", "%s.%s" % (path, key), "not a field of a frequency",
                  token=key, expected=("nth", "limit", "per"))
    if not _is_int(value[named[0]]) or value[named[0]] < 1:
        w.add("bad_value", "%s.%s" % (path, named[0]), "expected a positive integer",
              token=repr(value[named[0]]))
    if value.get("per") not in ("turn", "game", "combat"):
        w.add("unknown_atom", "%s.per" % path, "not a frequency window",
              token=value.get("per"), expected=("turn", "game", "combat"))
    w.atom("trigger", "nth_time" if named[0] == "nth" else "frequency_only")


def _selector(value, path, w):
    if not isinstance(value, dict) or not value:
        w.add("wrong_type", path, "expected a selector with at least one axis",
              token=repr(value), expected=sorted(_SELECTOR_FIELDS))
        return
    for key in sorted(value):
        checker = _SELECTOR_FIELDS.get(key)
        if checker is None:
            w.add("unexpected_field", "%s.%s" % (path, key),
                  "not a selector axis", token=key, expected=sorted(_SELECTOR_FIELDS))
            continue
        _field(value[key], checker, "%s.%s" % (path, key), w)
        atom = _SELECTOR_ATOM_OF.get(key)
        if atom is not None:
            _atom_or_reserved(atom, SELECTORS, "selector", "%s.%s" % (path, key), w)
    if value.get("count") is not None and value["count"] >= 2:
        _atom_or_reserved("count:two_plus", SELECTORS, "selector", "%s.count" % path, w)


def _condition(value, path, w):
    if not isinstance(value, dict):
        w.add("wrong_type", path, "expected a condition", token=repr(value),
              expected=_active(CONDITIONS))
        return
    name = value.get("cond")
    if name is None:
        w.add("missing_field", "%s.cond" % path, "a condition names its atom",
              expected=_active(CONDITIONS))
        return
    if not _atom_or_reserved(name, CONDITIONS, "condition", "%s.cond" % path, w):
        return
    spec = _CONDITIONS[name]
    _keys(value, spec, path, w, "cond")
    for key, checker in list(spec["req"].items()) + list(spec["opt"].items()):
        if key in value:
            _field(value[key], checker, "%s.%s" % (path, key), w)


def _costs(value, path, w):
    if not isinstance(value, list) or not value:
        w.add("bad_value", path, "a cost is a non-empty list — a free one says so",
              token=repr(value), expected=_active(COSTS))
        return
    for i, node in enumerate(value):
        _cost(node, "%s[%d]" % (path, i), w)


def _cost(value, path, w):
    if not isinstance(value, dict):
        w.add("wrong_type", path, "expected a cost node", token=repr(value),
              expected=_active(COSTS))
        return
    name = value.get("cost")
    if name is None:
        w.add("missing_field", "%s.cost" % path, "a cost node names its form",
              expected=_active(COSTS))
        return
    if not _atom_or_reserved(name, COSTS, "cost", "%s.cost" % path, w):
        return
    spec = _COST_NODES[name]
    _keys(value, spec, path, w, "cost")
    _cites(value, COSTS[name].cite, path, w, required=False)
    for key, checker in list(spec["req"].items()) + list(spec["opt"].items()):
        if key in value:
            _field(value[key], checker, "%s.%s" % (path, key), w)
    # Seven of the thirteen cost forms are a game action in a cost position
    # (CR 355.10.c.1), so paying one exercises that action's primitive too.
    for form, primitive in (("exhaust_self", "exhaust"), ("recycle_cost", "recycle"),
                            ("discard_cost", "discard"), ("banish_cost", "banish"),
                            ("sacrifice", "kill")):
        if name == form:
            w.atom("primitive", primitive)


def _effects(value, path, w):
    if not isinstance(value, list) or not value:
        w.add("bad_value", path, "an effect is a non-empty list of nodes",
              token=repr(value))
        return
    for i, node in enumerate(value):
        _effect(node, "%s[%d]" % (path, i), w)


def _effect(node, path, w):
    if not isinstance(node, dict):
        w.add("wrong_type", path, "expected an effect node", token=repr(node),
              expected=_active(PRIMITIVES))
        return
    w.node_paths.add(path)
    if "choice" in node:
        _choice(node, path, w)
        return
    if "kind" in node and "op" not in node:
        # An ability inside an effect list is an ability CREATED there. CR 389.1
        # and 392: a Delayed Ability is made by a resolving effect and is not
        # associated with the permanent that made it; CR 386-387 say the same of
        # a Reflexive Trigger ("Then do this:"). Writing them here rather than
        # inventing an `install` primitive keeps the vocabulary at the census's
        # size and puts the ability where the card prints it.
        _ability(node, path, w)
        return
    name = node.get("op")
    if name is None:
        w.add("missing_field", "%s.op" % path,
              "an effect node is an `op` or a `choice`", expected=_active(PRIMITIVES))
        return
    if name in ENGINE_ONLY:
        cite, why = ENGINE_ONLY[name]
        w.add("engine_only_atom", "%s.op" % path,
              "%r is a game action no card's text names — %s" % (name, why),
              token=name, expected=_active(PRIMITIVES), cite=cite)
        return
    if not _atom_or_reserved(name, PRIMITIVES, "primitive", "%s.op" % path, w):
        return
    if name not in _EFFECTS:
        w.add("unknown_atom", "%s.op" % path,
              "%r is an active census atom with no node type in this schema" % name,
              token=name, expected=sorted(_EFFECTS))
        return
    spec = _EFFECTS[name]
    _keys(node, spec, path, w, "op")
    _cites(node, PRIMITIVES[name].cite, path, w)
    for key, checker in list(spec["req"].items()) + list(spec["opt"].items()):
        if key in node:
            _field(node[key], checker, "%s.%s" % (path, key), w)
    if "when" in node:
        _condition(node["when"], "%s.when" % path, w)
    _effect_extras(name, node, path, w)


def _effect_extras(name, node, path, w):
    """The per-primitive rules that a field table cannot say."""
    if name == "play" and "enters" in node:
        # "Play a Gold gear token exhausted" is a replacement in the census's
        # count and an argument in the script's: one clause, one node, both
        # atoms credited. The continuous form ("Friendly units enter ready this
        # turn") is the `enters_modified` ABILITY, which is a different thing.
        _atom_or_reserved("enters_modified", REPLACEMENTS, "replacement",
                          "%s.enters" % path, w)
        _atom_or_reserved("enter", PRIMITIVES, "primitive", "%s.enters" % path, w)
    if name == "play" and "ignoring" in node:
        _atom_or_reserved("ignoring_cost", REPLACEMENTS, "replacement",
                          "%s.ignoring" % path, w)
        _atom_or_reserved("ignore", PRIMITIVES, "primitive", "%s.ignoring" % path, w)
        _atom_or_reserved("free", COSTS, "cost", "%s.ignoring" % path, w)
    if name == "buff":
        # CR 701-703: a Buff is a counter on a unit worth +1 Might, and it stays
        # until the unit leaves play. The census reads the word "buff" as the
        # `permanent` duration for exactly this reason, so buffing is how a
        # script says it.
        _atom_or_reserved("permanent", DURATIONS, "duration", path, w)
    if name == "move":
        named = [k for k in ("to", "swap_with") if k in node]
        if len(named) != 1:
            w.add("bad_value", path,
                  "a Move states exactly one destination: a location, or the object "
                  "whose place is being taken", token=json.dumps(sorted(node.keys())),
                  expected=("to", "swap_with"), cite="CR:447")
    if name == "add":
        named = [k for k in ("power", "token") if k in node]
        if len(named) != 1:
            w.add("bad_value", path,
                  "Add puts exactly one of a Power (CR 429) or a token (CR 179) into play",
                  token=json.dumps(sorted(node.keys())), expected=("power", "token"),
                  cite="CR:429")
    if name == "modify_cost" and node.get("delta", 0) < 0 and "min" not in node:
        # The prior engine's gap audit lists min-clamped modifiers among its
        # documented failures, and "to a minimum of {1}" is printed in the same
        # breath as the reduction it bounds. A reduction with no floor is
        # therefore a claim, and has to be made on purpose.
        w.add("missing_field", "%s.min" % path,
              "a cost reduction states its floor: printed reductions come with "
              "'to a minimum of', and an unclamped one must say `min: 0`",
              expected=("min",), cite="CR:356")
    if (name in ("give_might", "grant_keyword") and node.get("until") == "while_state"
            and "state" not in node and not w.gated):
        w.add("missing_field", "%s.state" % path,
              "a `while_state` duration names the state it lasts for, unless the "
              "ability is keyword-gated and takes it from the gate",
              expected=("state",), cite="CR:477")
    if name == "reveal" and "until_find" in node:
        # CR 369.1's "until" — the census reads this clause's `until` as the
        # `until_event` duration, and it is the only shape in the gauntlet where
        # the ending event is a card being found rather than a phase arriving.
        _atom_or_reserved("until_event", DURATIONS, "duration", "%s.until_find" % path, w)
    for key in ("until",):
        if node.get(key) == "until_event" and "event" not in node:
            w.add("missing_field", "%s.event" % path,
                  "an `until_event` duration names the event that ends it",
                  expected=("event",), cite="CR:477")


def _choice(node, path, w):
    name = node.get("choice")
    if not _atom_or_reserved(name, CHOICES, "choice", "%s.choice" % path, w):
        return
    spec = _CHOICE_NODES[name]
    _keys(node, spec, path, w, "choice")
    _cites(node, CHOICES[name].cite, path, w, required=False)
    for key, checker in list(spec["req"].items()) + list(spec["opt"].items()):
        if key in node:
            _field(node[key], checker, "%s.%s" % (path, key), w)
    if "when" in node:
        _condition(node["when"], "%s.when" % path, w)
    # `choose_object` and `up_to` are the printed word "choose", which the
    # census counts in BOTH the choice table and the primitive table.
    if name in ("choose_object", "up_to"):
        w.atom("primitive", "choose")
    if name == "up_to":
        _atom_or_reserved("up_to_n", SELECTORS, "selector", path, w)
    if "cost" in node:
        w.atom("primitive", "pay")
    # CR 355.10 is two pages of exceptions deciding whether a game object named
    # in card text is a TARGET: `Kill a unit at a battlefield` targets the unit,
    # `Kill all units at a battlefield` targets the battlefield. One selector
    # shape apart here, a different legality check apart in the engine — so the
    # answer is a required field rather than something inferred from the shape.
    if name == "choose_object" and "targets" not in node:
        w.add("missing_field", "%s.targets" % path,
              "CR 355.10 decides per clause whether the chosen object is a Target; "
              "the script says which rather than leaving it to be inferred",
              expected=("targets",), cite="CR:355")


def _trigger(value, path, w):
    if not isinstance(value, dict):
        w.add("wrong_type", path, "expected a trigger", token=repr(value),
              expected=sorted(_TRIGGER_FIELDS))
        return
    if "events" not in value:
        w.add("missing_field", "%s.events" % path, "a trigger names its events",
              expected=sorted(_TRIGGER_FIELDS), cite="CR:383")
    if "who" not in value:
        w.add("missing_field", "%s.who" % path,
              "CR 383.4.c.2/383.4.d.2 make `When I conquer` and `When you conquer` "
              "different subscriptions; the script says which",
              expected=WHO, cite="CR:383")
    for key in sorted(value):
        checker = _TRIGGER_FIELDS.get(key)
        if checker is None:
            w.add("unexpected_field", "%s.%s" % (path, key), "not a field of a trigger",
                  token=key, expected=sorted(_TRIGGER_FIELDS))
            continue
        _field(value[key], checker, "%s.%s" % (path, key), w)


def _cites(node, canonical, path, w, required=True):
    """Every node carries the rule that defines what it does (ADR 0009).

    Checked against `SECTIONS`, and required to include the construct's own
    rule: a citation that is merely well-formed is the failure mode ADR 0002
    exists to prevent, one layer down.

    Required on effect and ability nodes — the ones that DO something, and the
    ones a reviewer has to check against a rule. Optional on costs and choices,
    where every node would cite CR:444 or CR:355 and the citation would carry no
    information; still checked when present.
    """
    cites = node.get("cites")
    if cites is None:
        if required:
            w.add("missing_citation", "%s.cites" % path,
                  "every node carries the rule that defines it", expected=(canonical,),
                  cite=canonical)
        return
    if not isinstance(cites, list) or not cites:
        w.add("wrong_type", "%s.cites" % path, "expected a non-empty list of citations",
              token=repr(cites), expected=(canonical,))
        return
    for i, cite in enumerate(cites):
        m = _CITE_RE.match(cite) if isinstance(cite, str) else None
        if m is None:
            w.add("bad_citation", "%s.cites[%d]" % (path, i),
                  "a citation is CR: plus a rule number, e.g. CR:413 or CR:383.4.d.2",
                  token=cite)
            continue
        if m.group(1) not in SECTIONS:
            w.add("bad_citation", "%s.cites[%d]" % (path, i),
                  "CR %s is not a section this schema can cite — add it to "
                  "`SECTIONS` with its title if the rule is real" % m.group(1),
                  token=cite, expected=sorted(SECTIONS))
    heads = set(c.split(".")[0] for c in cites if isinstance(c, str))
    if canonical not in heads:
        w.add("wrong_citation", "%s.cites" % path,
              "this construct is defined by %s (%s) and must cite it"
              % (canonical, SECTIONS.get(canonical.split(":")[-1], "?")),
              token=", ".join(str(c) for c in cites), expected=(canonical,),
              cite=canonical)


def _ability(node, path, w):
    if not isinstance(node, dict):
        w.add("wrong_type", path, "expected an ability", token=repr(node),
              expected=sorted(_ABILITIES))
        return
    kind = node.get("kind")
    if kind not in _ABILITIES:
        w.add("unknown_atom", "%s.kind" % path, "not an ability kind", token=kind,
              expected=sorted(_ABILITIES), cite="CR:360")
        return
    w.node_paths.add(path)
    spec = _ABILITIES[kind]
    allowed = set(spec["req"]) | set(spec["opt"]) | {"kind", "cites", "note", "id",
                                                     "gate", "when"}
    for key in sorted(node):
        if key not in allowed:
            w.add("unexpected_field", "%s.%s" % (path, key),
                  "%r is not a field of a %s ability" % (key, kind), token=key,
                  expected=sorted(allowed))
    for key in sorted(spec["req"]):
        if key not in node:
            w.add("missing_field", "%s.%s" % (path, key),
                  "a %s ability requires %r" % (kind, key), expected=sorted(spec["req"]))
    if "gate" in node:
        w.gated += 1
    try:
        for key, checker in list(spec["req"].items()) + list(spec["opt"].items()):
            if key in node:
                _field(node[key], checker, "%s.%s" % (path, key), w)
    finally:
        if "gate" in node:
            w.gated -= 1
    if "when" in node:
        _condition(node["when"], "%s.when" % path, w)
    _cites(node, _ABILITY_CITE[kind], path, w)
    for category, atom in _ABILITY_ATOMS.get(kind, ()):
        table = {"replacement": REPLACEMENTS, "primitive": PRIMITIVES,
                 "trigger": TRIGGERS, "condition": CONDITIONS}[category]
        _atom_or_reserved(atom, table, category, path, w)
    if "gate" in node:
        _gate(node["gate"], "%s.gate" % path, w)
    if "keyword" in node:
        _ability_keyword(kind, node, path, w)
    if "timing" in node:
        _timing(node["timing"], "%s.timing" % path, w)


_ABILITY_CITE = {
    "passive": "CR:363",
    "activated": "CR:376",
    "triggered": "CR:382",
    "reflexive": "CR:386",
    "delayed": "CR:389",
    "cost_replacement": "CR:367",
    "enters_modified": "CR:367",
    "instead": "CR:369",
    "would": "CR:369",
    "as_enters": "CR:367",
    "ignoring_cost": "CR:367",
}


def _gate(value, path, w):
    """CR 135.2.e.7: `[Empowered][>]`, `[Level 6][>]`, `[Legion] —`.

    67 gauntlet clauses, 5% of all of them, over 9 distinct gating keywords.
    These are the "ongoing conditional passives" the prior C++ engine's gap
    audit flagged, so the binder is a first-class node and not a condition that
    happens to mention a keyword.
    """
    if not isinstance(value, dict):
        w.add("wrong_type", path, "expected a keyword gate", token=repr(value),
              expected=("keyword", "value"))
        return
    for key in sorted(value):
        if key not in ("keyword", "value", "cites", "note"):
            w.add("unexpected_field", "%s.%s" % (path, key), "not a field of a gate",
                  token=key, expected=("keyword", "value", "cites", "note"))
    _keyword(value, path, w)
    name = value.get("keyword")
    if name in KEYWORDS and KEYWORDS[name][1] != "dependent":
        w.add("keyword_kind", "%s.keyword" % path,
              "[%s] is a %s keyword; only a dependent keyword gates an ability "
              "(CR 135.2.e.7.b)" % (name, KEYWORDS[name][1]),
              token=name,
              expected=[k for k, v in KEYWORDS.items() if v[1] == "dependent"],
              cite=KEYWORDS[name][0])
    w.atom("modifier", "keyword_gate")


#: Which keyword kinds may introduce which ability kind. The rules' own
#: classification (CR 805-829) decides this, which is the point of carrying the
#: kind at all: `[Deathknell]` cannot introduce an activated ability and
#: `[Equip]` cannot introduce a trigger, and neither mistake is a typo a spell
#: checker would catch.
_KEYWORD_MAY_INTRODUCE = {
    "triggered": ("triggered",),
    "reflexive": ("triggered",),
    "delayed": ("triggered",),
    "activated": ("activated", "optional_additional_cost"),
    "passive": ("passive", "dependent"),
}


def _timing(value, path, w):
    """`[Action][>]` / `[Reaction][>]` — when an ability may be used (CR 135.2.e.7)."""
    _keyword(value, path, w)
    name = value.get("keyword") if isinstance(value, dict) else value
    if name in KEYWORDS and KEYWORDS[name][1] != "permissive":
        w.add("keyword_kind", path,
              "[%s] is a %s keyword; timing comes from a permissive one"
              % (name, KEYWORDS[name][1]), token=name,
              expected=[k for k, v in KEYWORDS.items() if v[1] == "permissive"],
              cite=KEYWORDS[name][0])


def _ability_keyword(kind, node, path, w):
    """The keyword that introduces an ability must be of a matching kind."""
    ref = node["keyword"]
    name = ref.get("keyword") if isinstance(ref, dict) else ref
    if name not in KEYWORDS:
        return                                   # `_keyword` already said so
    kw_kind = KEYWORDS[name][1]
    wanted = _KEYWORD_MAY_INTRODUCE.get(kind)
    if wanted and kw_kind not in wanted:
        w.add("keyword_kind", "%s.keyword" % path,
              "[%s] is a %s keyword and cannot introduce a %s ability"
              % (name, kw_kind, kind), token=name,
              expected=[k for k, v in KEYWORDS.items() if v[1] in wanted],
              cite=KEYWORDS[name][0])
        return
    if kind == "triggered" and name in KEYWORD_TRIGGERS:
        events = set(node.get("trigger", {}).get("events") or [])
        expected = set(KEYWORD_TRIGGERS[name])
        if not (events & expected):
            w.add("keyword_kind", "%s.trigger.events" % path,
                  "[%s] triggers on %s (%s); this ability listens for %s"
                  % (name, " or ".join(sorted(expected)), KEYWORDS[name][0],
                     ", ".join(sorted(events)) or "nothing"),
                  token=name, expected=expected, cite=KEYWORDS[name][0])


# ---------------------------------------------------------------------------
# Clauses, tests, version
# ---------------------------------------------------------------------------

_WORD = re.compile(r"[a-z0-9']+")
_REMINDER = re.compile(r"\([^)]*\)")
_SYMBOL = re.compile(r":rb_[a-z0-9_]+:|\{[^}]*\}|\[[^\]]*\]")


def words(text):
    """The word sequence of some card text, with everything unstable removed.

    Reminder text goes (CR 135.2.d.3: its presence, absence and wording have no
    effect on game function), symbols go — the corpus writes
    `:rb_energy_1::rb_rune_chaos:` where Riot's errata writes `[1][P]` for the
    same cost — and punctuation goes. What is left is what a clause has to be a
    run of, and it is stable across both notations.
    """
    text = _REMINDER.sub(" ", _SYMBOL.sub(" ", text or ""))
    return _WORD.findall(text.lower())


def _is_run(needle, haystack):
    if not needle:
        return False
    for i in range(len(haystack) - len(needle) + 1):
        if haystack[i:i + len(needle)] == needle:
            return True
    return False


def _squash(text):
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def quotes_printed_text(clause_text, printed_text):
    """Is this clause a run of the card's printed text?

    A coverage mark on text nobody printed is not coverage, so the mark is
    checked against the corpus rather than trusted. The comparison is over word
    sequences with reminder text and symbols removed, because the corpus and
    Riot's errata articles write the same cost two different ways and a literal
    comparison would make 52 errata'd cards unscriptable.

    A clause that is nothing BUT a keyword — `[Assault 2]`, `[Tank]` — has no
    words left after normalisation, and falls back to a literal substring: the
    bracketed form is stable in both notations.
    """
    needle = words(clause_text)
    if needle:
        return _is_run(needle, words(printed_text))
    return bool(_squash(clause_text)) and _squash(clause_text) in _squash(printed_text)


def _clauses(doc, card, w):
    clauses = doc.get("clauses")
    if not isinstance(clauses, list) or not clauses:
        w.add("missing_field", "clauses",
              "a script splits the printed text into clauses and marks each one: "
              '"cards with a script" is the metric that let 41% of the prior '
              "engine's cards ship with a real gap", expected=("clauses",))
        return
    printed = (card.get("text") or "") if card else ""
    for i, clause in enumerate(clauses):
        path = "clauses[%d]" % i
        if not isinstance(clause, dict):
            w.add("wrong_type", path, "expected a clause record", token=repr(clause))
            continue
        for key in sorted(clause):
            if key not in ("text", "status", "node", "reason"):
                w.add("unexpected_field", "%s.%s" % (path, key), "not a field of a clause",
                      token=key, expected=("text", "status", "node", "reason"))
        status = clause.get("status")
        if status not in CLAUSE_STATUS:
            w.add("unknown_atom", "%s.status" % path, "not a coverage mark",
                  token=status, expected=CLAUSE_STATUS)
        text = clause.get("text")
        if not isinstance(text, str) or not text.strip():
            w.add("missing_field", "%s.text" % path, "a clause quotes the printed text",
                  expected=("text",))
        elif printed and not quotes_printed_text(text, printed):
            w.add("clause_not_in_text", "%s.text" % path,
                  "this clause is not a run of words in the card's printed text — "
                  "coverage measured against text nobody printed is not coverage",
                  token=text)
        if status == "implemented" and not clause.get("node"):
            w.add("missing_field", "%s.node" % path,
                  "an implemented clause names the node that implements it",
                  expected=("node",))
        if status in ("approx", "unsupported") and not clause.get("reason"):
            w.add("missing_field", "%s.reason" % path,
                  "an %s clause says why, or the mark is a shrug" % status,
                  expected=("reason",))
        node = clause.get("node")
        if node and node not in w.node_paths and not any(
                p.startswith(node) for p in w.node_paths):
            w.add("bad_clause_ref", "%s.node" % path,
                  "no node at this path — a clause cannot be implemented by "
                  "something that is not there", token=node,
                  expected=sorted(w.node_paths))


def _tests(doc, w):
    tests = doc.get("tests")
    if not isinstance(tests, list):
        w.add("missing_field", "tests", "a script carries its scenario tests",
              expected=("tests",))
        return
    if not 2 <= len(tests) <= 4:
        w.add("bad_test", "tests",
              "2 to 4 scenario tests per script (plan §4.3 step 2); this has %d"
              % len(tests), token=str(len(tests)))
    for i, test in enumerate(tests):
        _test(test, "tests[%d]" % i, w)


def _test(test, path, w):
    if not isinstance(test, dict):
        w.add("wrong_type", path, "expected a scenario test", token=repr(test))
        return
    allowed = {"name", "given", "when", "choices", "then"}
    for key in sorted(test):
        if key not in allowed:
            w.add("unexpected_field", "%s.%s" % (path, key), "not a field of a test",
                  token=key, expected=allowed)
    for key in ("name", "given", "when", "then"):
        if key not in test:
            w.add("missing_field", "%s.%s" % (path, key), "a test needs %r" % key,
                  expected=sorted(allowed))
    given = test.get("given")
    if given is not None:
        _fixture(given, "%s.given" % path, w)
    when = test.get("when")
    if isinstance(when, dict):
        if when.get("do") not in TEST_ACTIONS:
            w.add("bad_test", "%s.when.do" % path, "not something a test can do",
                  token=when.get("do"), expected=TEST_ACTIONS)
        for key in sorted(when):
            if key not in ("do", "card", "seat", "to", "ability", "target", "at", "n"):
                w.add("unexpected_field", "%s.when.%s" % (path, key),
                      "not a field of a test action", token=key,
                      expected=("do", "card", "seat", "to", "ability", "target", "at", "n"))
    elif when is not None:
        w.add("wrong_type", "%s.when" % path, "expected a test action", token=repr(when))
    then = test.get("then")
    if not isinstance(then, list) or not then:
        w.add("bad_test", "%s.then" % path,
              "a test with no expectation cannot fail, and a test that cannot fail "
              "is not a test", token=repr(then))
        return
    for i, expectation in enumerate(then):
        _expectation(expectation, "%s.then[%d]" % (path, i), w)


def _fixture(given, path, w):
    if not isinstance(given, dict):
        w.add("wrong_type", path, "expected a fixture", token=repr(given))
        return
    allowed = {"turn_player", "phase", "seats", "battlefields", "note"}
    for key in sorted(given):
        if key not in allowed:
            w.add("unexpected_field", "%s.%s" % (path, key), "not a field of a fixture",
                  token=key, expected=sorted(allowed))
    seats = given.get("seats")
    if not isinstance(seats, list) or not seats:
        w.add("bad_test", "%s.seats" % path,
              "a fixture describes at least one seat", token=repr(seats))
        return
    seat_fields = {"seat", "hand", "board", "trash", "deck", "banished", "champion",
                   "energy", "power", "points", "xp", "runes"}
    for i, seat in enumerate(seats):
        if not isinstance(seat, dict):
            w.add("wrong_type", "%s.seats[%d]" % (path, i), "expected a seat",
                  token=repr(seat))
            continue
        for key in sorted(seat):
            if key not in seat_fields:
                w.add("unexpected_field", "%s.seats[%d].%s" % (path, i, key),
                      "not a field of a seat", token=key, expected=sorted(seat_fields))
        if seat.get("seat") not in (0, 1):
            w.add("bad_test", "%s.seats[%d].seat" % (path, i), "seat is 0 or 1",
                  token=repr(seat.get("seat")), expected=("0", "1"))
        for j, unit in enumerate(seat.get("board") or []):
            here = "%s.seats[%d].board[%d]" % (path, i, j)
            if not isinstance(unit, dict) or "card" not in unit:
                w.add("bad_test", here, "a board entry names a card", token=repr(unit))
                continue
            for key in sorted(unit):
                if key not in ("card", "at", "exhausted", "damage", "buffs", "state",
                               "attached", "token"):
                    w.add("unexpected_field", "%s.%s" % (here, key),
                          "not a field of a board entry", token=key)


def _expectation(node, path, w):
    if not isinstance(node, dict):
        w.add("wrong_type", path, "expected an expectation", token=repr(node))
        return
    kind = node.get("expect")
    if kind not in TEST_EXPECTATIONS:
        w.add("bad_test", "%s.expect" % path, "not something a test can assert",
              token=kind, expected=TEST_EXPECTATIONS)
        return
    allowed = {"expect", "seat", "zone", "card", "n", "at", "is", "domain",
               "keyword", "reason", "value"}
    for key in sorted(node):
        if key not in allowed:
            w.add("unexpected_field", "%s.%s" % (path, key),
                  "not a field of an expectation", token=key, expected=sorted(allowed))
    if kind in ("zone_count", "zone_has", "zone_lacks") and node.get("zone") not in ZONES:
        w.add("bad_test", "%s.zone" % path, "not a zone", token=node.get("zone"),
              expected=ZONES)
    if kind in ("zone_count", "board_count", "might", "damage", "buffs", "points",
                "xp", "energy", "power", "chain", "cost") and not _is_int(node.get("n")):
        w.add("bad_test", "%s.n" % path, "this expectation asserts a number",
              token=repr(node.get("n")))
    if kind == "state" and node.get("is") not in STATES:
        w.add("bad_test", "%s.is" % path, "not a state", token=node.get("is"),
              expected=STATES)


# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------

#: What the version hash covers: the executable body, and nothing else. Editing
#: a scenario test or a coverage mark does not change how a card plays, and a
#: version that moved when they did would make the hash in a game log useless
#: for the one question it answers — "was this game played with this script?".
BODY_FIELDS = ("schema", "card", "keywords", "abilities")


def body(doc):
    return dict((k, doc[k]) for k in BODY_FIELDS if k in doc)


def body_hash(doc):
    payload = json.dumps(body(doc), sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def stamp(doc):
    """Set `version` from the body. Returns the document."""
    doc["version"] = body_hash(doc)
    return doc


# ---------------------------------------------------------------------------
# The entry point
# ---------------------------------------------------------------------------

def validate(doc, lookup=None):
    """Every error in one script, as records. Never raises on a bad script.

    `lookup` resolves a card name to the vendored pool entry; the default is the
    deck lab's own index, so the card a script claims to implement has to exist
    and its printed text is what the clause marks are checked against.
    """
    lookup = cards.find if lookup is None else lookup
    w = _Walk(lookup)
    if not isinstance(doc, dict):
        w.add("wrong_type", "", "a script is a JSON object", token=repr(doc)[:80])
        return w.errors
    if doc.get("schema") != SCHEMA:
        w.add("schema_not_recognised", "schema",
              "this validator implements %r" % SCHEMA, token=doc.get("schema"),
              expected=(SCHEMA,))
        return w.errors

    allowed = {"schema", "card", "source", "version", "keywords", "abilities",
               "clauses", "tests", "notes"}
    for key in sorted(doc):
        if key not in allowed:
            w.add("unexpected_field", key, "not a field of a script", token=key,
                  expected=sorted(allowed))
    for key in ("card", "source", "version", "abilities", "clauses", "tests"):
        if key not in doc:
            w.add("missing_field", key, "a script needs %r" % key, expected=sorted(allowed))

    if doc.get("source") not in SOURCES:
        w.add("unknown_atom", "source", "not a provenance", token=doc.get("source"),
              expected=SOURCES)

    card = None
    name = doc.get("card")
    if isinstance(name, str):
        card = w.lookup(name)
        if card is None:
            w.add("unknown_card", "card",
                  "no card by that name in the vendored pool — a script for a card "
                  "nobody can play is a script nobody can test", token=name,
                  expected=cards.candidates(name) or None)
        elif card.get("name") != name:
            w.add("unknown_card", "card",
                  "use the card's own name, not an alias the index resolves",
                  token=name, expected=(card["name"],))

    for i, kw in enumerate(doc.get("keywords") or []):
        w.node_paths.add("keywords[%d]" % i)
        _keyword(kw, "keywords[%d]" % i, w)

    abilities = doc.get("abilities")
    if abilities is None:
        pass
    elif not isinstance(abilities, list):
        w.add("wrong_type", "abilities", "expected a list of abilities",
              token=repr(abilities)[:60])
    else:
        for i, ability in enumerate(abilities):
            _ability(ability, "abilities[%d]" % i, w)

    _clauses(doc, card, w)
    _tests(doc, w)

    if "version" in doc and isinstance(doc.get("version"), str):
        want = body_hash(doc)
        if doc["version"] != want:
            w.add("version_stale", "version",
                  "the version is a hash of the executable body; this one is stale, "
                  "so a game log quoting it would name a script that no longer exists",
                  token=doc["version"], expected=(want,))
    return w.errors


def atoms_of(doc):
    """Which census atoms this script exercises, as `category:name` strings."""
    w = _Walk(cards.find)
    if not isinstance(doc, dict):
        return set()
    for i, kw in enumerate(doc.get("keywords") or []):
        _keyword(kw, "keywords[%d]" % i, w)
    for i, ability in enumerate(doc.get("abilities") or []):
        _ability(ability, "abilities[%d]" % i, w)
    return w.atoms


#: Every atom this vocabulary is trying to exercise, as `category:name`. The
#: coverage report is measured against this and not against "the atoms some
#: script happened to use", which would be a target that moves to wherever the
#: scripts already are.
def active_atoms():
    out = set()
    for category, table in (("primitive", PRIMITIVES), ("trigger", TRIGGERS),
                            ("selector", SELECTORS), ("condition", CONDITIONS),
                            ("choice", CHOICES), ("cost", COSTS),
                            ("replacement", REPLACEMENTS), ("duration", DURATIONS)):
        for name in _active(table):
            out.add("%s:%s" % (category, name))
    for name in KEYWORDS:
        out.add("keyword:%s" % name)
    for name, (_, gauntlet, _pool) in TOKENS.items():
        if gauntlet:
            out.add("token:%s" % name)
    out.add("modifier:for_each")
    out.add("modifier:keyword_gate")
    return out


def vocabulary_size():
    """The construct count, beside the census's atom count. Both, or neither."""
    return {
        "primitives": len(_active(PRIMITIVES)),
        "triggers": len(_active(TRIGGERS)),
        "selectors": len(_active(SELECTORS)),
        "conditions": len(_active(CONDITIONS)),
        "choices": len(_active(CHOICES)),
        "costs": len(_active(COSTS)),
        "replacements": len(_active(REPLACEMENTS)),
        "durations": len(_active(DURATIONS)),
        "keywords": len(KEYWORDS),
        "tokens": sum(1 for spec in TOKENS.values() if spec[1]),
        "declared": sum(len(t) for t in (PRIMITIVES, TRIGGERS, SELECTORS, CONDITIONS,
                                         CHOICES, COSTS, REPLACEMENTS, DURATIONS)),
    }

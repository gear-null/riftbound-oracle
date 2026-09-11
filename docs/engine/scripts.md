# Card scripts

A card script is a JSON program over a closed vocabulary, stored in
`.claude/skills/deck-lab/data/scripts/<card>.json`. It is **data**: cited per
node, marked clause by clause, tested by scenario, and hashed
([ADR 0009](../adr/0009-the-engine-plays.md) decision 2).

This page is the schema. The validator that enforces it is
[`lib/engine/dsl/schema.py`](../../.claude/skills/deck-lab/lib/engine/dsl/schema.py);
the committed library and its coverage arithmetic are in `library.py`; the
checks are in `dsl/selftest.py` and run inside `deck_cli.py selftest`.

**This half does not execute anything.** The interpreter is
[#25](https://github.com/gear-null/riftbound-oracle/issues/25) and will be a
client of this schema rather than a second opinion about it.

```
python3 deck_cli.py scripts                 # the library, validation, coverage
python3 deck_cli.py scripts --card "Sun Disc"   # one script's error records, as JSON
python3 deck_cli.py check <deck>            # ... plus engine readiness for a deck
python3 deck_cli.py selftest                # the checks
```

## Where the vocabulary comes from

Every construct below earns its place with a count from
[the vocabulary census](vocabulary-census.md), which measured the committed
corpus rather than borrowing Forge's numbers. At the 95% line of 1,224 gauntlet
clauses: **33 effect primitives, 20 trigger events, 25 selector atoms, 17
condition atoms, 4 choice forms, 10 cost forms, 6 replacement kinds, 5
durations**, plus all 25 CR keywords and 10 token specs. That cut is the floor,
not the whole of it — see the next section.

Every atom the census found anywhere in the 954-card pool is **declared** —
56 / 39 / 38 / 23 / 8 / 13 / 9 / 6 — and a script that reaches for a
declared-but-inactive one gets its own error code, that atom's census count, and
an instruction to mark the clause `unsupported` instead. The same discipline
`decisions.py` uses for decision kinds, for the same reason: a vocabulary with a
known edge beats one with a silent edge.

The closure is the lever, not an aesthetic. LLM generation against a fat
per-card API (XMage's 2,712 symbols) measured **5.3% exact accuracy**; the DSL
exists to make the target small enough to hit.

## Closed under composition

The 95% cut is not the active vocabulary on its own, because **the cut is not
closed**. It was taken per table — the 33 commonest primitives, the 25 commonest
selectors, each ranked alone — and nothing made those rankings agree with each
other. So it arrived with holes straddling them: `look_at` made the cut and the
top of the deck it looks at did not; the `[Empower]` and `[Equip]` keywords made
it and the game actions they perform did not; `empty` made it and the only card
in the gauntlet that prints it needs two selectors that did not.

A clause then reads `approx` for a reason that is an artefact of where a line
was drawn, not of anything a card does — which makes the coverage number a
measure of the cut rather than of the DSL. So **fourteen atoms are promoted by
composition**: outside the cut, active anyway, because an atom inside the cut
cannot say what a gauntlet card says without them.

| promoted atom | gauntlet / pool | needed by |
|---|---|---|
| `primitive:empower` | 4 / 16 | `[Empower]` (CR 827, 17 references) performs it |
| `primitive:attach` | 4 / 14 | `[Equip]` (CR 818, 19) and `[Quick-Draw]` (CR 819, 3) perform it |
| `primitive:disempower` | 3 / 7 | the `[Empowered]` branch of a clause whose condition is active |
| `primitive:become_copy` | 2 / 6 | a token an active `play` made is then copied onto |
| `trigger:score_trigger` | 1 / 2 | the other half of a multi-event trigger with `play_self` |
| `trigger:become_empowered` | 1 / 3 | the event `[Empower]` causes; `become_state` cannot name it |
| `trigger:frequency_only` | 1 / 3 | CR 383.3.e's "once each turn", a modifier on an active event |
| `selector:zone:top_of_deck` | 12 / 19 | where `look_at` (8) and `reveal` (13) look |
| `selector:at:location` | 10 / 17 | where `move` (29) moves something to |
| `selector:negated` | 6 / 9 | the "non-token" / "non-Recruit" half of an active trigger |
| `selector:type:champion` | 2 / 2 | what `return_to` returns, on the only card `empty` appears on |
| `selector:zone:champion` | 2 / 2 | where it returns to, on that same card |
| `condition:played_from` | 1 / 1 | which zone an active `play` played from |
| `condition:zone_of_object` | 0 / 6 | where the subject of an active trigger is standing |

The active vocabulary is therefore **37 primitives, 23 triggers, 30 selectors,
19 conditions**, plus the cut's 4 choice forms, 10 cost forms, 6 replacement
kinds and 5 durations. Every promotion names the construct that needed it; a
promotion with no such reason is a vocabulary growing for its own sake, and the
selftest refuses one.

Closure is then **checked**, three ways, because there are three ways to leave a
hole:

1. **Nothing writable is reserved.** Every value a script may put in a `zone`,
   `at`, `type` or `side` field is an active atom. Values nothing needs —
   `at:showdown`, `type:ability`, `type:legend`, `zone:board`,
   `zone:banishment` — are *absent* from those enums rather than
   reserved-but-writable, so the closure holds without the vocabulary growing to
   hold them.
2. **Nothing composed is reserved.** Every atom an active construct reaches
   through another construct — the `COMPOSED` table, the ability-kind table, the
   events each keyword triggers on — is active too.
3. **No shipped clause still blames one.** No `approx` or `unsupported` reason in
   `data/scripts/` names a reserved atom.

What is left over after that is the honest residue: **two clauses**, neither of
them an atom problem. Draven - Audacious chooses an opponent and the census found
no player selector anywhere in the corpus to size one from; Smoke and Mirrors
asks whether "at least one of them" has a keyword, and the census found no
condition combinator. Those are constructs the corpus does not contain, not
constructs a cut left out.

## The document

```json
{
 "schema": "riftbound-card-script/1",
 "card": "First Mate",
 "source": "manual",
 "keywords": [],
 "abilities": [ … ],
 "clauses": [ … ],
 "tests": [ … ],
 "version": "sha256:5991e492ec2c6c3a"
}
```

| field | |
|---|---|
| `schema` | the vocabulary version. A script written against another one is refused, not half-understood |
| `card` | the card's own name, as the vendored pool spells it. An alias is refused so two scripts cannot claim one card |
| `source` | `manual` or `compiled` — where the script came from |
| `keywords` | keyword references the card carries on its own (CR 800-829) |
| `abilities` | the card's abilities, several per card |
| `clauses` | the printed text, split, each clause marked and pointed at the node that implements it |
| `tests` | 2-4 scenario tests, as data |
| `version` | `sha256:` + 16 hex of the **executable body** |

The file name is derived from the card name (`slug()`), so two people scripting
one card collide in git rather than shipping two scripts for it. The name is
**canonicalised first**: the corpus spells a subtitled card two ways — Riftcodex
writes `Irelia - Fervent`, decklist sites write `Irelia, Fervent` — and both
forms appear in the committed gauntlet, so slugging the raw string made a deck
naming the other form report the card unscripted with its script sitting right
there.

---

# One worked example per construct

## Keyword references

A keyword is a **parameterised reference**, never 25 more primitives. The rules
classify each keyword into a kind, and the kind *is* the construct: eight
passives, six triggered abilities, three dependent, two permissive, two
activated, two optional additional costs, one action prerequisite, one deck
constraint.

```json
"keywords": [
  {"keyword": "Tank", "cites": ["CR:815"]},
  {"keyword": "Assault", "value": 2, "cites": ["CR:807"]},
  {"keyword": "Flow", "cites": ["CR:829"],
   "cost": [{"cost": "energy", "n": 2}, {"cost": "power_any", "n": 1},
            {"cost": "banish_cost", "what": {"self": true}}]}
]
```

Five keywords take a numeric parameter (`Assault`, `Deflect`, `Shield`, `Hunt`,
`Level`) and must carry one — printed `[Assault]` with no number is `"value": 1`
(CR 807), said out loud rather than left to a default. `cost` is for the price a
card prints beside a keyword (`[Repeat] {2}`, `[Empower] — Discard 1`).

**`Mighty` is not a keyword.** It is bracketed on ten cards, set in the keyword
font, and CR 805-829 does not define it — CR 706-711 do, as a derived *state*.
A keyword table built by scanning brackets invents a 26th keyword; this one
refuses it and points at the state.

## Abilities

`abilities` is a list. Several per card is the normal case, not the corner: once
the six triggered-ability keywords are counted as what the rules say they are,
15 gauntlet cards have more than one trigger.

### `passive` (CR 363)

```json
{"kind": "passive", "cites": ["CR:363"],
 "effect": [{"op": "give_might", "n": 2, "until": "permanent", "cites": ["CR:477"],
             "what": {"type": "unit", "side": "friendly", "another": true}}]}
```

In a passive, `until: "permanent"` means "as long as the ability applies" — CR
477 recomputes the layers, so the value follows the board instead of snapshotting.

### `activated` (CR 376-377)

```json
{"kind": "activated", "cites": ["CR:376"],
 "cost": [{"cost": "exhaust_self", "cites": ["CR:414"]}],
 "effect": [{"op": "buff", "n": 1, "cites": ["CR:426", "CR:701"],
             "what": {"type": "unit", "side": "friendly", "state": "exhausted",
                      "targets": true}}]}
```

`timing` carries a permissive keyword (`[Action][>]`, `[Reaction][>]`);
`frequency` carries "once each turn"; `keyword` names the keyword that
introduces the ability (`[Equip]`, `[Empower]`).

### `triggered` (CR 382-383)

```json
{"kind": "triggered", "cites": ["CR:382", "CR:383"],
 "trigger": {"events": ["attack", "defend"], "who": "me"},
 "effect": [{"op": "give_might", "n": -2, "min": 1, "until": "this_turn",
             "cites": ["CR:477"],
             "what": {"type": "unit", "side": "enemy", "at": "here",
                      "targets": true}}]}
```

`events` is a **list**: 18 of the 184 gauntlet trigger clauses name more than one
event, and taking the first comma as the trigger's end drops the rest.

`who` is **required**. CR 383.4.d.2 and 383.4.c.2 make `When I hold` and `When
you hold` the same words and a different subscription — the first fires only
from a unit present at the battlefield, the second from anything referencing the
player. The census counts the event; only the rules say who is listening, so the
script says which rather than leaving it to a convention.

`frequency` is a modifier on the event and not an event of its own — and it
lives on the **ability**, not inside the trigger. It had two homes once, and two
homes for one fact is two places for it to disagree; CR 383.1.b and 383.3.e bound
how often the *ability* fires, not how the event is recognised. A `frequency`
inside a trigger is refused with a record saying where it belongs.

```json
{"kind": "triggered", "frequency": {"nth": 1, "per": "turn"},
 "trigger": {"events": ["win_combat"], "who": "me"}, …}
```

`{"nth": N}` is CR 383.1.b's "the first time … each turn"; `{"limit": N}` is CR
383.3.e's "once each turn" (declared, currently outside the active cut).

A keyword-introduced trigger names its keyword, and the events must be the ones
the rules give that keyword:

```json
{"kind": "triggered", "keyword": {"keyword": "Hunt", "value": 2},
 "trigger": {"events": ["conquer", "hold"], "who": "me",
             "keyword": {"keyword": "Hunt", "value": 2}},
 "effect": [{"op": "gain_xp", "n": 2, "seat": "you", "cites": ["CR:728"]}],
 "cites": ["CR:382", "CR:823"]}
```

**`linked` is not an ability kind.** CR 393-396 make a Linked Ability a *set* of
abilities that reference each other, not a kind of one — so linkage is a relation
between the entries in `abilities`, and a card with two abilities is never
ambiguous about which of them it is.

### `reflexive` (CR 386-387) — "Then do this:"

```json
{"kind": "reflexive", "cites": ["CR:386"],
 "effect": [{"op": "grant_keyword", "until": "permanent",
             "keyword": {"keyword": "Temporary"}, "cites": ["CR:800", "CR:816"],
             "what": {"type": "token", "side": "friendly", "at": "here"}}]}
```

### `delayed` (CR 389-392) — "The next … this turn"

A delayed ability says what it **waits for**. `delayed_next` is the census's name
for the *window*, not for an event: `{"events": ["delayed_next"]}` names the
delay and not the thing delayed, and an interpreter reading it would have nothing
to subscribe to. So the ability carries `until` (a real event), `what`, `window`
and `frequency` — the same move `nth_time` made when it stopped being an event
and became a frequency. Writing `delayed_next`, `nth_time` or `frequency_only` in
a trigger's `events` is refused, with the construct to use instead.

```json
{"kind": "delayed", "cites": ["CR:389"],
 "until": "play_other", "who": "you", "window": "this_turn",
 "what": {"type": "unit", "side": "friendly", "bind": "next"},
 "frequency": {"nth": 1, "per": "turn"},
 "effect": [{"kind": "enters_modified", "cites": ["CR:367"],
             "applies_to": {"ref": "next"}, "enters": "ready"}]}
```

**An ability written inside an effect list is an ability *created* there.** CR
389.1 and 392 say a Delayed Ability is made by a resolving effect and is not
associated with the permanent that made it; CR 386-387 say the same of a
Reflexive Trigger. Writing them where the card prints them keeps the vocabulary
at the census's size instead of inventing an `install` primitive.

## Replacement kinds — six node types

15% of gauntlet cards with text carry at least one replacement clause, so the
layer is real. The distribution says how big it has to be: the two commonest
kinds are not general machinery at all — a cost reduction is arithmetic in the
cost calculation and `enters ready` is a flag set as a permanent arrives. Only
`would` and `instead` have to intercept an event, and those are 22 gauntlet
clauses across 16 cards.

### `cost_replacement` (19) — CR 367 / 356

```json
{"kind": "cost_replacement", "cites": ["CR:367", "CR:356"],
 "applies_to": {"self": true}, "delta": -2, "min": 0, "affects": "energy",
 "when": {"cond": "score_threshold", "seat": "opponent", "within": 3}}
```

### `enters_modified` (17) — CR 367

```json
{"kind": "enters_modified", "cites": ["CR:367"], "applies_to": {"self": true},
 "enters": "ready",
 "when": {"cond": "paid_additional_cost", "keyword": "Accelerate"}}
```

### `instead` (15) — CR 369

`event` is optional here. With no event named, the replaced thing is the sibling
instruction the clause just gave — "Give a unit +2 {M}. If it's [Empowered],
give it +4 {M} **instead**": the +4 replaces the +2 and does not stack with it.

```json
{"kind": "instead", "cites": ["CR:369"], "applies_to": {"ref": "it"},
 "when": {"cond": "state_of_object", "what": {"ref": "it"}, "state": "empowered"},
 "do": [{"op": "give_might", "what": {"ref": "it"}, "n": 4,
         "until": "this_turn", "cites": ["CR:477"]}]}
```

### `would` (7) — CR 369.1

```json
{"kind": "would", "cites": ["CR:369"], "event": "die",
 "applies_to": {"ref": "saved"}, "until": "this_turn",
 "frequency": {"nth": 1, "per": "turn"},
 "do": [{"op": "heal", "what": {"ref": "saved"}, "cites": ["CR:418"]},
        {"op": "exhaust", "what": {"ref": "saved"}, "cites": ["CR:414"]},
        {"op": "recall", "what": {"ref": "saved"}, "cites": ["CR:455"]}]}
```

A `would` ability replaces the event it intercepts, which is the word the cards
print: every gauntlet `would` clause also says "instead".

### `as_enters` (3) — CR 367

```json
{"kind": "as_enters", "cites": ["CR:367"],
 "do": [{"op": "pay", "seat": "you", "cites": ["CR:444"],
         "cost": [{"cost": "additional_cost", "optional": true,
                   "pay": [{"cost": "energy", "n": 1}]}]}]}
```

### `ignoring_cost` (8) — CR 367

```json
{"kind": "ignoring_cost", "cites": ["CR:367"],
 "applies_to": {"self": true}, "affects": "energy"}
```

A card that plays *something else* for free says so on the `play` node instead
(`"ignoring": "total"`), which is the same three atoms in one node.

## The keyword gate — `[Empowered][>]`, `[Level 6][>]`, `[Legion] —`

67 gauntlet clauses, 5% of all of them, over 9 distinct gating keywords. These
are the "ongoing conditional passives" the prior C++ engine's gap audit flagged;
they are mainstream, so the binder (CR 135.2.e.7) is a first-class field and not
a condition that happens to mention a keyword.

```json
{"kind": "passive", "cites": ["CR:363"],
 "gate": {"keyword": "Level", "value": 6, "cites": ["CR:824"]},
 "effect": [{"op": "grant_keyword", "what": {"self": true}, "until": "while_state",
             "keyword": {"keyword": "Ganking"}, "cites": ["CR:800", "CR:810"]}]}
```

Only a **dependent** keyword may gate (`Empowered`, `Legion`, `Level`); anything
else is refused with `keyword_kind`. Inside a gated ability a `while_state`
duration takes its state from the gate rather than repeating it — the card says
it once, and so does the script.

## Effect nodes

One node per active primitive, `op` plus its arguments plus `cites`. Thirty-six
of the 37 are `op` nodes; `create_token` rides inside a selector and `choose` is
reached through the choice forms. The 33 from the cut:

| node | shape |
|---|---|
| `draw` | `{"op":"draw","n":1,"seat":"you","cites":["CR:413"]}` |
| `exhaust` / `ready` / `stun` / `heal` / `kill` / `banish` / `recall` | `{"op":"ready","what":<selector>,"cites":["CR:415"]}` |
| `recycle` | `{"op":"recycle","n":3,"what":<selector>,"cites":["CR:416"]}` |
| `deal` | `{"op":"deal","n":3,"to":<selector>,"source":<selector>,"split":true,"cites":["CR:417"]}` |
| `play` | `{"op":"play","what":<selector>,"n":2,"to":"base","from":"trash","enters":"exhausted","ignoring":"total","cites":["CR:419"]}` |
| `move` | `{"op":"move","what":<selector>,"to":"base"}` or `{"op":"move","what":<selector>,"swap_with":<selector>}` — exactly one |
| `discard` | `{"op":"discard","n":1,"seat":"you","cites":["CR:422"]}` |
| `reveal` | `{"op":"reveal","from":"deck","position":"top","until_find":<selector>,"bind":"seen","cites":["CR:424"]}` |
| `counter` | `{"op":"counter","what":<selector>,"unless":<condition>,"cites":["CR:425"]}` |
| `buff` | `{"op":"buff","what":<selector>,"n":1,"cites":["CR:426","CR:701"]}` — a Buff is a permanent counter |
| `add` | `{"op":"add","power":"Order","n":1,"cites":["CR:429"]}` or `{"op":"add","token":<token>}` — exactly one |
| `channel` | `{"op":"channel","n":1,"exhausted":true,"seat":"you","cites":["CR:430"]}` |
| `pay` | `{"op":"pay","cost":[<cost>…],"seat":"controller","cites":["CR:444"]}` |
| `give_might` | `{"op":"give_might","what":<selector>,"n":-2,"min":1,"until":"this_turn","cites":["CR:477"]}` |
| `grant_keyword` | `{"op":"grant_keyword","what":<selector>,"keyword":{"keyword":"Shield","value":2},"until":"this_combat","cites":["CR:800","CR:814"]}` |
| `modify_cost` | `{"op":"modify_cost","what":<selector>,"delta":-1,"min":1,"affects":"energy","cites":["CR:356"]}` |
| `restriction` | `{"op":"restriction","who":<selector>,"cant":"be_chosen_by_enemy","unless":<condition>,"cites":["CR:364"]}` |
| `permission` | `{"op":"permission","who":<selector>,"may":"play_to_occupied_battlefield","when":<condition>,"cites":["CR:364"]}` |
| `return_to` | `{"op":"return_to","what":<selector>,"to":"hand","seat":"owner","cites":["CR:108"]}` |
| `put` | `{"op":"put","what":<selector>,"to":"trash","cites":["CR:108"]}` |
| `look_at` | `{"op":"look_at","n":3,"from":"deck","position":"top","bind":"seen","cites":["CR:128"]}` |
| `gain_xp` / `score` | `{"op":"score","n":1,"seat":"you","cites":["CR:467"]}` |
| `enter` | `{"op":"enter","where":"battlefield","what":{"self":true},"cites":["CR:355"]}` |
| `ignore` | `{"op":"ignore","affects":"energy","of":<selector>,"cites":["CR:357"]}` |
| `choose` | reached through the choice forms below; the census counts the printed word "choose" in both tables |
| `create_token` | reached through a token spec inside a selector — see below |

A **cost reduction with no floor is refused**. Printed reductions come with "to
a minimum of" in the same breath, the prior engine's audit lists min-clamped
modifiers among its documented failures, and an unclamped one has to say
`"min": 0` on purpose.

## Selectors

Four independent axes plus `self`, which is what keeps the count at 38 rather
than one selector per printed phrase.

```json
{"side": "friendly", "type": "unit", "at": "here", "zone": "trash",
 "state": "exhausted", "tag": "Sand Soldier", "cost": {"op": "<=", "n": 3},
 "another": true, "all": true, "count": 2, "up_to": 2, "owner": "controller",
 "position": "top", "rest": true, "targets": true,
 "bind": "it", "ref": "it",
 "token": {"name": "Gold", "type": "gear"}}
```

- **side** `friendly` · `enemy` · `any`
- **type** `unit` · `gear` · `spell` · `rune` · `battlefield` · `token` · `card` · `champion`
- **place** `here` · `base` · `battlefield` · `location`
- **zone** `hand` · `trash` · `deck` · `top_of_deck` · `champion`
- **predicate** `state` · `tag` · `cost` · `power` · `not` (plus `might`, `keyword`, declared)
- **quantity** `all` · `another` · `count` · `up_to`
- `bind` names the chosen object; `ref` refers back to one. `rest` is "the rest".

`position` is **not** a selector axis. The top of the deck is its own census
selector atom, so a selector says it as a zone (`zone: "top_of_deck"`);
`position` belongs to the primitives that look at or put a card at one end of a
deck. One way to say it in each place.

Inside a `not`, a token spec names a **kind** and creates nothing — `another
non-Recruit unit` filters by what a Recruit is — so it needs no Might and does
not credit `create_token`. A filter reporting itself as token creation would be
the coverage number lying about what a script does.

`targets` answers CR 355.10 for this selector. It is *required* on
`choose_object`, where the question bites hardest: `Kill a unit at a battlefield`
targets the unit, `Kill all units at a battlefield` targets the battlefield.
Those two clauses are one selector shape apart here and a different legality
check apart in the engine, so the script says which.

## Values

An integer, or one of three count-scaled forms:

```json
{"for_each": {"type": "battlefield", "side": "friendly", "another": true}}
{"might_of": {"ref": "fallen"}}
{"cost_of":  {"ref": "spell"}}
```

`for_each` is the census's count-scaled modifier — 15 gauntlet clauses.

## Conditions

`{"cond": "<atom>", …}`, one atom per condition, no combinators (the census
found none in the corpus). All 17 active:

```json
{"cond": "controls", "what": {"side": "friendly", "type": "gear", "count": 2}, "op": ">=", "n": 2}
{"cond": "state_of_object", "what": {"ref": "it"}, "state": "empowered", "negated": true}
{"cond": "state_of_self", "state": "in_combat"}
{"cond": "alone", "what": {"type": "unit", "side": "enemy"}, "where": "here"}
{"cond": "if_you_do"}
{"cond": "paid_additional_cost", "keyword": "Accelerate"}
{"cond": "would_event", "event": "die", "what": {"ref": "it"}}
{"cond": "is_type", "what": {"ref": "seen"}, "type": "spell", "negated": true}
{"cond": "already", "what": {"token": {"name": "Baron Pit", "type": "battlefield"}}, "negated": true}
{"cond": "cant"}
{"cond": "score_threshold", "seat": "opponent", "within": 3}
{"cond": "unless_pays", "seat": "controller", "cost": [{"cost": "energy", "n": 2}]}
{"cond": "comparison", "left": {"might_of": …}, "op": ">=", "right": 5}
{"cond": "has_played", "what": {"type": "gear", "side": "friendly", "tag": "Equipment"}, "this_turn": true}
{"cond": "count_threshold", "what": {"type": "rune", "side": "friendly"}, "op": ">=", "n": 7}
{"cond": "empty", "zone": "champion", "seat": "you"}
{"cond": "has_keyword", "what": {"ref": "first"}, "keyword": "Temporary"}
```

`alone` at 7 gauntlet occurrences is the surprise — more common than
`count_threshold`, and no general condition language falls out of it.

## Choice forms

Four active, each a wrapper around an effect list. `cost` on a choice is CR
355.10.c.1's `[do X] to [do Y]` — the price of taking the option.

```json
{"choice": "may", "cost": [{"cost": "exhaust_self"}],
 "do": [{"op": "channel", "n": 1, "exhausted": true, "cites": ["CR:430"]}]}

{"choice": "choose_object", "targets": true, "bind": "it",
 "what": {"type": "unit", "side": "friendly"},
 "do": [{"op": "ready", "what": {"ref": "it"}, "cites": ["CR:415"]}]}

{"choice": "up_to", "n": 2, "bind": "chosen", "targets": false,
 "what": {"type": "rune", "side": "friendly", "state": "exhausted"},
 "do": [{"op": "ready", "what": {"ref": "chosen"}, "cites": ["CR:415"]}]}

{"choice": "opponent_picks", "seat": "each", "bind": "picked",
 "what": {"type": "gear", "side": "any", "owner": "controller"},
 "do": [{"op": "kill", "what": {"ref": "picked"}, "cites": ["CR:428"]}]}
```

`opponent_picks` is the one that matters architecturally: it is a decision
request routed to the **other** seat, which is an engine question and not a
syntax one.

## Costs

Ten active forms. Seven of the thirteen the census found are **a game action
used as a cost**, and they cite the same rule the action does — CR 355.10.c.1
says a cost *is* an instruction, in a cost position, so there is no second
vocabulary for them.

```json
[{"cost": "energy", "n": 1},
 {"cost": "power_domain", "domain": "Calm", "n": 1},
 {"cost": "power_any", "n": 1},
 {"cost": "exhaust_self"},
 {"cost": "recycle_cost", "n": 1, "what": {"type": "card", "zone": "trash"}},
 {"cost": "discard_cost", "n": 1},
 {"cost": "banish_cost", "what": {"self": true}},
 {"cost": "sacrifice", "what": {"self": true}},
 {"cost": "free"},
 {"cost": "additional_cost", "optional": true, "pay": [{"cost": "energy", "n": 1}]}]
```

## Durations

`this_turn` · `permanent` · `while_state` · `until_event` · `this_combat`
(`next_turn` declared). `while_state` names its state unless a gate supplies it;
`until_event` names the event that ends it.

## Token specs

Closed, at eleven: a token that is not in this table is one the corpus never
prints, and a compiler inventing one would be inventing a card. A token spec
lives **inside a selector**, because the census counts "Play three 1 {M} Recruit
unit tokens into your base" as both `play` and `create_token` and a script
should not have to say it twice.

```json
{"op": "play", "n": 2, "to": "base", "cites": ["CR:419", "CR:179"],
 "what": {"token": {"name": "Mech", "type": "unit", "might": 3}}}
```

Unit tokens print a Might; a token may carry `keywords`, `tags`, a `state` —
and **`abilities`**, in the same schema a card's use. CR 184.3 lets the creating
effect grant a token abilities, and the corpus prints them: the Gold token's
`[Reaction][>] Kill this, [E]: [Add] [A]`, the Shadow Clone's attack trigger, the
Baron Pit's "Units can move here from anywhere". A free-text `text` field was
there first, and it was where those abilities went to be forgotten — a clause
marked `implemented` on the strength of a string nothing reads.

**Inside a token's abilities, `self` is the TOKEN.** The Gold's "Kill this" kills
the Gold, not the card that minted it.

```json
{"op": "play", "enters": "exhausted", "cites": ["CR:419", "CR:179"],
 "what": {"token": {
   "name": "Gold", "type": "gear",
   "abilities": [
     {"kind": "activated", "timing": {"keyword": "Reaction"}, "cites": ["CR:376"],
      "cost": [{"cost": "sacrifice", "what": {"self": true}},
               {"cost": "exhaust_self"}],
      "effect": [{"op": "add", "power": "any", "n": 1, "cites": ["CR:429"]}]}]}}}
```

A token spec means two different things depending on where it stands. In a
**creating** position — the `what` of a `play`, the `token` of an `add` — it
makes one, prints a Might, and credits `create_token`. Anywhere else it **names a
kind and makes nothing**: `another non-Recruit unit` and `your Sand Soldiers` are
filters, and crediting them as token creation would have the coverage number
report a filter as a thing built.

---

# Clause coverage

Progress is reported as **clauses implemented of clauses total**, never as
"cards with a script" — the metric under which the prior C++ Riftbound engine
reported near-complete coverage while its own audit found 325 of 787 cards (41%)
with a real gap ([ADR 0009](../adr/0009-the-engine-plays.md) decision 3).

```json
"clauses": [
 {"text": "[Assault 2]", "status": "implemented", "node": "keywords[0]"},
 {"text": "When you play me, discard 1.", "status": "implemented", "node": "abilities[0]"},
 {"text": "If you played this from your hand, draw 1.", "status": "unsupported",
  "reason": "the condition is `played_from` (CR 419), 1 gauntlet clause and outside the active cut"}
]
```

- `implemented` — names the node that implements it
- `approx` — implemented differently; `reason` says how the script and the card differ
- `unsupported` — not implemented; `reason` says what is missing

**The clauses must PARTITION the printed text**: their words, in order, are the
card's words. Without that rule the ratio inflates two ways — delete an
`unsupported` clause and it rises, invent an implemented one and it rises again —
because the script chooses its own denominator. Partitioning makes the
denominator the card.

Splitting is the half a partition cannot catch: cut one implemented clause in
two and the words are identical while the clause count rises. Two things bound
it. The report carries a **word ratio** beside the clause ratio, and splitting
does not move it. And `data/clause-counts.json` vendors the **census splitter's**
clause count per card — `engine-train/census.py` cannot be imported from inside
the skill (ADR 0004), so its number is vendored — as a bound: no script may claim
more clauses than the splitter found. It is a bound rather than an equality
because the two granularities differ on purpose: the splitter cuts a sentence
into its trigger condition, its gating conditions and its instructions, where a
clause here is the readable span a person marks. The splitter is finer on 56 of
67 cards and never coarser.

Two more mechanical checks stand behind the marks:

1. **The clause has to be in the printed text.** Its word sequence must be a run
   of the card's, after reminder text and symbols are removed — CR 135.2.d.3
   says reminder text has no game function, and the corpus and Riot's errata
   articles write one cost two ways (`:rb_energy_1:` / `[1]`), so a literal
   comparison would make 52 errata'd cards unscriptable. A clause that is
   nothing but a keyword falls back to the bracketed form.
2. **`node` has to point at a node that exists.** A clause cannot be implemented
   by something that is not there.

## Scenario tests

2 to 4 per script, as data the interpreter will execute (plan §4.3 step 2). The
shape is validated now, so a test written against a guess is caught before
anything can run it.

```json
{"name": "readies an exhausted ally when played",
 "given": {"turn_player": 0, "phase": "main", "battlefields": ["Minefield"],
           "seats": [{"seat": 0, "hand": ["First Mate"], "energy": 3,
                      "board": [{"card": "Sunlit Guardian", "at": "base",
                                 "exhausted": true}]},
                     {"seat": 1}]},
 "when": {"do": "play", "card": "First Mate", "seat": 0, "to": "base"},
 "choices": ["Sunlit Guardian"],
 "then": [{"expect": "state", "card": "Sunlit Guardian", "seat": 0, "is": "ready"}]}
```

A fixture can state the precondition its clause actually needs, and has to:
`given` carries `chain` (what is on the Chain to be countered), `played_this_turn`
(the history "if you've played an Equipment this turn" reads) and per-seat
`hidden` alongside the zones. Pinning "played an Equipment this turn" with an
Equipment *on the board* is the kind of fixture an implementation that reads the
board instead of the history also passes.

`when.do` is one of `play · activate · trigger · move · standard_move ·
begin_turn · end_turn · combat · showdown · score · conquer · hold · discard ·
kill · resolve · attack · defend`.

`then` expectations: `zone_count · zone_has · zone_lacks · board_count · state ·
might · damage · buffs · points · xp · energy · power · chain · cost · keyword ·
refused`. A test with no expectation cannot fail, and is refused.

## The version hash

`version` is `sha256:` + 16 hex of the **executable body** — `schema`, `card`,
`keywords`, `abilities` — canonicalised with sorted keys.

It deliberately does **not** cover `tests`, `clauses` or `notes`. The hash
answers one question, recorded in every game log it touches: *was this game
played with this script?* Editing a scenario test or a coverage mark does not
change how a card plays, and a version that moved when they did would make the
hash useless for the only thing it is for.

`python3 deck_cli.py scripts --stamp` recomputes stale hashes. It is a
formatter, not a fix: nothing calls it automatically, because a version that
re-stamped itself on read would be answering its own question.

---

# Error records

Validation returns a **list of records**, never a raised message: the compiler's
repair loop needs every error in a script, and it needs them as data (plan §4.3
step 1). `deck_cli.py scripts --card X` prints exactly what the repair loop sees.

**`validate()` never raises, for any JSON value.** That is a contract, not an
aspiration, and it did not hold at first: a fuzz sweep of ~107k hostile inputs —
every value in every script swapped for a `None`, a list, a dict, a float, at
every path — found **3,570 raising inputs across fourteen sites**, every one a
table lookup, an iteration or a comparison against something the schema had
assumed was a string. `{"op": ["ready"]}` is JSON a model can emit, and
`["ready"] in PRIMITIVES` raises `TypeError` rather than reporting anything. One
such file in `data/scripts/` took `library.load_all` down for all sixty-seven.

Three things hold it now, and the fuzz check in the selftest re-runs the sweep:

- every table lookup goes through `_named`, every iteration through `_as_list`,
  every numeric comparison through `_is_int`;
- a **depth guard** turns a cycle or an absurd nest into a `too_deep` record
  rather than a `RecursionError`;
- a backstop turns anything still unforeseen into an `internal_error` record —
  and the fuzz check asserts the backstop **never fires**, so if it ever does it
  is a bug report rather than a shrug.

`library.check` is isolated the same way: one hostile file is one bad row.

```json
{"code": "reserved_atom",
 "path": "abilities[0].effect[0].op",
 "message": "'hide' is a census atom (3 gauntlet clause(s), 8 across the pool) but is outside this vocabulary's active cut — mark the clause `unsupported` rather than reaching for it",
 "token": "hide",
 "expected": ["add", "banish", "buff", …],
 "cite": "CR:421"}
```

| field | |
|---|---|
| `code` | one of the codes below. The repair loop switches on it |
| `path` | the JSON path into the document |
| `message` | for a person |
| `token` | the offending value, when there is one |
| `expected` | the closed set the token should have come from — the field that makes automated repair possible |
| `cite` | the rule that decides the matter, where the rules decide it |

| code | when |
|---|---|
| `schema_not_recognised` | wrong or missing `schema` |
| `missing_field` | a required key is absent |
| `unexpected_field` | a key the schema does not define |
| `wrong_type` | right key, wrong JSON type |
| `unknown_atom` | a token no census table contains |
| `reserved_atom` | a **real** census atom outside the active cut, with its count |
| `engine_only_atom` | `burn_out` or `create` — performed constantly, printed never |
| `not_a_keyword` | bracketed in the corpus, not in CR 805-829 (`Mighty`, `[Add]`, `[Stun]`) |
| `unknown_keyword` | not a keyword at all |
| `keyword_kind` | a keyword in the wrong kind of position |
| `keyword_parameter` | a number on a keyword that takes none, or none on one that does |
| `bad_citation` | malformed, or a section not in `SECTIONS` |
| `missing_citation` | a node with no `cites` |
| `wrong_citation` | `cites` omits the construct's own rule |
| `bad_value` | out of range, empty, or contradictory |
| `unknown_card` | not a card in the vendored pool |
| `clause_not_in_text` | a clause whose words are not in the printed text |
| `bad_clause_ref` | a clause pointing at a node that does not exist |
| `version_stale` | `version` is not the hash of the body |
| `bad_test` | a scenario test the interpreter could not run |
| `filename_mismatch` | the file is not named after the card it scripts |
| `unreadable` | the file is not JSON at all |
| `clauses_not_a_partition` | the clauses do not reconstruct the printed text |
| `contradictory_selector` | two selector axes that cannot both hold |
| `duplicate_id` | two abilities claiming one id |
| `unknown_ref` | a `ref` to a bind nothing establishes |
| `too_deep` | nested past the walker's limit |
| `internal_error` | the backstop: a walk that raised anyway |

`dsl/selftest.py` produces every one of these from a deliberately broken script
and asserts the record field by field. A code no broken script can produce is a
branch of the repair loop that would never be taken and never tested.

`unknown_atom` and `reserved_atom` are different on purpose: `smite` is a typo,
`hide` is a real thing cards say that this vocabulary version has not taken on,
and a repair loop must not treat them alike.

---

# The census-to-construct mapping

Where a census atom does not become a node of the same name, it is listed here.
Everything not listed maps one-to-one.

| census atom | construct | why |
|---|---|---|
| `create_token` (primitive) | a `token` spec inside a selector | the census counts "play a Gold gear token" in both the `play` and `create_token` tables; one clause, one node, both atoms credited |
| `choose` (primitive) | the `choose_object` / `up_to` choice forms | the printed word "choose" is counted in the primitive table and the choice table, and it is one construct |
| `nth_time`, `frequency_only` (triggers) | `ability.frequency` | CR 383.1.b and 383.3.e bound how often the ABILITY fires; they are not events, and modelling them as such would be 40 more trigger rows |
| `delayed_next` (trigger) | the `delayed` ability kind | the atom names the WINDOW ("the next unit you play this turn"), not an event; the ability says what it waits for in `until` |
| `zone:top_of_deck` (selector) | `zone: "top_of_deck"` on a selector | a census SELECTOR atom, so a selector says it; `position` stays on the primitives that look at or put a card at one end of a deck |
| `up_to_n` (selector) | the `up_to` choice form | the quantity and the choice are the same construct |
| `enters_modified` (replacement) | `play.enters`, or the ability kind | the instruction form ("play a Gold token exhausted") and the continuous form ("Friendly units enter ready this turn") are different things |
| `ignoring_cost` (replacement) | `play.ignoring`, or the ability kind | same split. Either credits `ignoring_cost`, `ignore` and the `free` cost form, which is how the census counts "ignoring its cost" |
| `instead` (replacement) | the `instead` kind, and any `would` ability | every gauntlet `would` clause also prints "instead" |
| `would_event` (condition) | any `would` ability | the census counts the word "would" in both the replacement and the condition table |
| `permanent` (duration) | the `buff` primitive, or `until: "permanent"` | the census reads the word "buff" as this duration; CR 701-703 agree — a Buff is a counter that stays |
| `until_event` (duration) | `reveal.until_find`, or `until: "until_event"` | "reveal … until you reveal a unit" is the gauntlet's only shape where the ending event is a card being found |
| `by_state` (selector) | `selector.state` | one atom over a vocabulary of states read from the rules |
| `for_each` (modifier) | `{"for_each": <selector>}` as a value | a scaled value, not an instruction |
| keyword gate (modifier) | `ability.gate` | CR 135.2.e.7's binder |

## Atoms no script reaches

`deck_cli.py scripts` prints these, and the selftest names them rather than
rounding them away. As of this writing there are none: **171 of 171**.

It did not start that way. `condition:empty` sat unreachable — one occurrence in
the whole gauntlet, on Hallowed Tomb, a card that also needed `zone:champion` and
`type:champion`, both outside the cut. Closing the vocabulary under composition
is what let that card be written and that atom be reached, which is the clearest
statement of what the closure buys.

---

# Working on scripts

**To add a card.** Write `data/scripts/<slug>.json`, run
`python3 deck_cli.py scripts --card "<name>"` until the error list is empty, run
`--stamp`, then `selftest`. Split the printed text into clauses first: the marks
are what the coverage number is made of, and a clause you cannot implement is
information, not failure.

**To cite a new rule.** Add it to `SECTIONS` in `schema.py` with its title.
Closed on purpose, like the vocabulary: a citation is checked against that table
and nothing looser, so `CR:4133` and `CR:999` are refused rather than carried.
The table was verified against the `rules-report` corpus at authoring time —
re-check it with `python3 rules_cli.py rule <id>` after a rules update.

**To activate a reserved atom.** Change its `active` flag, add its node shape,
add a row to `PROMOTED` naming the active construct that needed it, and add a
script that exercises it. All four are checked: the counts are pinned as "the
census cut plus its promotions", every promotion must carry a reason, and every
active atom must be exercised by some script. A vocabulary that drifts from the
measurement still validates every script and just stops being the thing that was
measured, which is why the drift is what goes red rather than the scripts.

**Never** add a construct the census does not show. The size of this vocabulary
is the whole mechanism.

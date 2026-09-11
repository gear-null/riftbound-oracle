# How the kernel is tested

A win rate cannot tell you the engine is right. A mis-implemented rule produces
a *plausible* finished game and a *plausible* number, and the number is what
every deck verdict is computed from — so the instruments have to be the kind
that fail loudly on a change nobody intended.

Four of them come from chess and card-engine practice, two from this repo's own
discipline, and one — the differential harness against `table.py` — from having a
second implementation of the same rules lying around. All seven run on every
commit.

    python3 deck_cli.py selftest        # the suite: table + engine, ~4s
    python3 deck_cli.py mutants         # proves the suite can fail, ~30 min
    python3 deck_cli.py engine perft    # the deeper perft depths
    python3 deck_cli.py engine golden   # replay the recorded playthroughs
    python3 deck_cli.py engine soak --games 1000
    python3 deck_cli.py engine soak --games 1000 --abilities
    python3 deck_cli.py engine bench    # clones, decisions and games per second

## 1. Legal-action perft

`perft(d)` counts the leaves of the decision tree `d` decisions deep from a
fixed board. It says nothing about playing well and everything about whether the
engine enumerates the right moves: add an illegal option, drop a legal one, or
let a rule fire a step early and the count moves.

The shuffle is fixed by the seed, so what is counted is the **decision** tree,
not the game tree — which is the branching factor a policy actually faces.

Three canonical boards, in `engine/perft.py`:

| board | decks | seed | first | advanced by | what it covers |
|---|---|---|---|---|---|
| `opening` | Irelia vs Viktor | 7 | seat 0 | nothing — the game's first decision | the opening mulligan |
| `midgame` | Irelia vs Viktor | 11 | seat 1 | 24 decisions of a seeded random policy | plays and moves out of an empty board |
| `contested` | Viktor vs Kennen | 5 | seat 0 | 36 decisions of a seeded random policy | both battlefields controlled, units deployed at them |

A midgame position is reproducible because it is *derived*: a deck pair, a seed
and a number of decisions taken by a named policy, rather than a board someone
wrote down by hand. `contested` is tuned to earn its name — a board called
contested that is not contested is a fixture lying about what it covers.

**The decks are named once**, in `engine/fixtures.py`, and they are the
`*-core-meta` gauntlet lists rather than tournament results. Tournament lists
come and go with the meta: while this kernel was being written another PR
deleted one of them as a duplicate, and three separate fixtures here named it.
`engine_setup` now asserts every fixture deck still resolves to a legal deck, so
the next removal fails with a sentence naming the deck rather than with a
`KeyError` six frames down.

```
python3 deck_cli.py engine perft
python3 deck_cli.py engine perft --board midgame --depth 3 --divide
```

`--divide` prints `perft(d-1)` under each option at the root, which is how a
mismatch is bisected: the subtree whose count moved is one command away instead
of a hand-bisect through the rules. The golden counts live in
`engine/goldens/perft.json`; the selftest checks the first four depths (a
quarter of a second) and the CLI checks all six.

## 2. Golden playthroughs

The primary artifact. Each golden is a deck pair, a seed and a policy seed, and
records **every decision the engine asked**, the answer it was given, the state
hash after each one, and the whole log. Replaying it asserts far more than a
final score: it asserts the engine asked the same questions in the same order,
which is where a rules change actually shows up.

Two kinds of mismatch are reported differently on purpose:

- a **state** mismatch — a step hash moved — means a rule changed;
- a **log** mismatch with the hashes intact means only the wording moved.

The second is usually deliberate, and the message says so instead of sending
someone hunting for a rules bug in a reworded sentence.

Three goldens (`engine/goldens/playthroughs.json`, ~90KB): one ordinary game,
the same pair seated the other way round, and a different archetype pair. Their
decks come from `engine/fixtures.py` too.

## 2b. The ability soak

`engine soak --abilities` is the only instrument that plays **whole games with
card text in them**. It attaches `engine/demo.py`'s eight hand-built abilities to
real fixture cards — a Play Effect with a "you may", a `[Legion]`-gated passive,
an activated ability with an exhaust cost, a Deathknell-shaped `die` trigger, an
`enters_modified`, a Conquer Effect that creates a Delayed Ability, a
`cost_replacement` and a once-each-turn `would` — and plays a thousand random
games with them. Every one must still end by a named rule.

Why it earns a place beside the plain soak: a framework that deadlocks, loops, or
leaves a Pending Item on the Chain produces no wrong *answer* for a golden or a
perft to catch. It produces a game that does not finish, and only a run of whole
games finds that.

Abilities live in a module-global registry, which is card data shared by every
clone. The soak, and every check that attaches one, therefore detaches in a
`finally` — a fixture left behind moves every perft and golden run after it, and
a check asserts the detach actually happened.

## 3. Conservation invariants

Cheap properties no legal sequence of decisions can break, checked after every
mandatory operation when a game is created with `invariants=True`:

- every card a seat brought is in exactly one of that seat's zones — Main Deck
  cards and Rune Deck cards counted separately, because 416 sends a recycled
  rune to a different deck from a recycled card, and an Ability on the Chain is
  not counted at all because 401.1 gives it no card to represent it;
- **the layered traits are exactly what a fresh recomputation produces** (476).
  `setm`, `mod` and `kw` are caches, and a cache nobody checks is a second source
  of truth. This one earned its keep on the day it was written: run across 120
  ability-soak games it reported 78 stale positions, all the same defect — a
  keyword gate that opened when a card was finalized stayed shut until the next
  Cleanup, so a `[Legion]` passive was off for one FEPR step. 476 now runs at
  every 319 board change. The check runs on a COPY, so an invariant cannot
  repair what it is checking;
- points are monotone and never past the Victory Score (303.2 forbids
  simultaneous actions, so the first seat to reach it wins there);
- no id answers for two objects;
- the Chain is LIFO — a finalized item never sits above a pending one, or 340.1
  would resolve the wrong one;
- every permanent is at a location the board has;
- the four states of 310 agree with the board.

`engine soak --check` runs them across a whole soak; the selftest runs a game
with them on.

## 4. The perfect-symmetry test

The sharpest instrument here, and the cheapest. Same deck on both seats,
mirrored shuffle streams, first player swapped, and **the same deterministic
policy stream per seat**. The property is that the two games are **exact
mirrors** — the same events in the same order with the seats relabelled — and
the suite compares the logs entry by entry.

The paired score is a consequence of that, not a measurement of it, and the
difference is worth saying plainly. The suite runs **two seeds, mirrored, so
four games**, and the score reads **2-2**. "Exactly 50.00%" sounds like a
balance result and is not one: a fair coin gives 2-2 over four games about
three times in eight, so at this n the percentage would be just as green on an
engine that was merely unbiased rather than symmetric. What rules that out is
the log comparison — 2-2 here is arithmetic, because each pair is one game and
its relabelled self, so a win for seat 0 in one is a win for seat 1 in the
other and the score cannot come out any other way while the mirror holds.

Anything that is not symmetric breaks it, and most asymmetries are real bugs
rather than noise — a loop over `range(2)` instead of turn order, a rule keyed to
seat 0, an extra-rune bonus tied to a seat number instead of to "not the first
player". Two of the engine's design choices exist only because this test
demands them, and both are recorded in
[`spec.md`](spec.md#deliberate-divergences-from-tablepy).

Because the two games are compared **event for event**, the failure names the
first log entry that differs rather than reporting a win rate that is slightly
off — which is the difference between a bug you can find in a minute and one you
argue about for a day.

## 5. The differential harness against the table

The table (ADR 0007) and the engine (ADR 0009) are two independent
implementations of the same Core Rules. A kernel that agrees with a thousand of
its own games agrees with its own bugs; agreeing with the older tool is evidence
of a different kind, and it is free.

`engine/parity.py` takes a scenario — a deck pair, a seed and **an answer for
every decision**, generated the way a golden is — drives the engine through it,
translates each decision into the table's own verbs, and diffs the two states
after every step on:

| | |
|---|---|
| zones | both hands, both Main and Rune Decks, trashes, banishments, Champion Zones |
| the board | every unit's id, name, controller, location, exhausted, damage and **Might** |
| runes | id, name, controller, exhausted |
| battlefields | control, Contested and who applied it, and who has Scored there this turn |
| points | both seats |

Each field carries the rule that decides it, so a mismatch reports `465 combat
damage, 428 kill, 144/446 movement, 359.2 entering` rather than two large lists.

Two things make it a real comparison rather than a copy:

* **The deal is transplanted once, and nothing else is.** Two shuffles of one
  decklist by two generators are two different games, so the engine's dealt
  position is copied onto the table at the first decision. After that only the
  ORDER of the face-down decks is re-aligned, and only while both hold the same
  cards — copying across a real difference is the one way a differential harness
  can be made to agree with anything.
* **The assignment is compared, not shared.** The table is given the damage the
  engine actually assigned, so what the diff sees is the RESOLUTION. 465.2.c
  itself is checked by asking each tool for its own lethal-first assignment on
  the same board and requiring the same dict — without that, a wrong assignment
  would be copied over and agree with itself. A mutant that inflates the damage
  pool by one is caught by exactly this and by nothing else in the harness. Once
  per SIDE of each combat, not once per combat: keyed on "is this the first
  assignment decision here" it compared the Attacker's and never the Defender's,
  and the swap branch that exists for the Defender was dead code.

**Where they are compared: at every Main Phase decision, and at the end**
(`parity.comparable`). Those are the states the table can be in. It has no
Chain, no Focus and no Steps of Combat, so between "play this card" and "it is
on the board" the engine passes through positions the table has no way to hold,
and comparing there would be comparing the engine against a tool that does not
model the thing compared.

**Three numbers, because they measure three things.** Across the three scenarios
the harness feeds the engine **354 scripted answers**, makes **159 state
comparisons** — the Main Phase decisions and the ends, about 45% of the answers —
and compares **14 damage assignments**, one for each side of each of the seven
combats. Reporting the answer count alone, which is what it used to do, claims
a little over twice the state coverage it has.

**What cannot be mapped** is `parity.UNMAPPED`, and it is two lists. Engine
decisions with no table verb: the Execute window of 338.1 and the Focus window of
347 (the table has no Chain and no Showdown State), and the 323.12/323.13 choice
of which battlefield opens (its reader calls `resolve_combat` at the one they
mean). Table verbs with no engine option: `combat_preview`, which puts card text
in front of a person before they assign damage; and `set_target`, `banish`,
`discard`, `recycle_card` and attached Gear, all of which are reachable only from
card text this slice does not execute.

**Where they legitimately disagree** is `parity.DIVERGENCES`, by name, from
[`spec.md`](spec.md#deliberate-divergences-from-tablepy). Two are neutralised at
the call site (a unit enters exhausted; battlefields are indexed in turn order),
one is invisible to a state diff (turn-order loops — the mirror test is what
pins that), and one is compared only at the end (victory is decided at a Cleanup
here and immediately there, and both agree once the game is actually over). A
harness that does not know its own expected differences reports them as failures
and gets muted.

## 6. The table's checks, ported and accounted for

The table's suite is 209 checks that took a 54-defect review to earn. Every one
is a question the second implementation has to be asked again, and "we ported the
ones that seemed relevant" is exactly the silent partial coverage this project
exists to avoid.

So `engine/ported.py` is a MAP: every table check name to either the exact name
of an engine check, or `N/A:` with a reason, or `SHARED:` with a reason.
`engine_ported` then checks the map against what actually ran — every table check
is a key, no key is stale, every ported value resolves against the suite's own
registry of names, and every excused value says why in a sentence. A check
renamed on either side breaks this instead of quietly losing its cover.

`SHARED` is the honest third answer: `cards.py`, `deckfile.py` and `importer.py`
are one implementation used by both tools, so the table's checks over them
already cover the engine.

The counts print in the suite. The suite's other 8 checks are `proven_ratio`,
which reports on this whole suite — the engine's half included — and is therefore
not a rule the engine has to re-implement.

## 7. The mutation battery

This repo's own rule: *a check nobody has watched fail is not yet a check.* The
battery in `lib/mutants.py` reintroduces each defect the suite claims to catch,
runs the suite against a throwaway copy of the skill folder, and asserts the
right check goes red. A mutant that SURVIVES is a check that is lying.

The kernel's mutants are the last blocks of `MUTANTS` and reintroduce, among
others: dropping the going-second extra rune, resolving the Chain FIFO, skipping
the final-point rule, iterating players by seat number instead of turn order,
letting a unit enter ready, and determinizing without redealing the opponent's
hand. The combat block adds the defects that leave a plausible finished game
behind — never designating a unit, reading a combat's sides by who is standing
where, assigning the whole pool to one unit, ignoring Tank or Backline, applying
Assault to a defender, keeping the Tasks 465.3 cancels, and ending combat without
removing the designations.

The ability block adds the defects a framework hides best, because each produces
a game that finishes: a keyword gate that never closes, `[Legion]` satisfied by
the card's own play, a `me` listener that hears every object's event, a "you may"
performed without asking, a declined trigger performed anyway, simultaneous
triggers ordered by seat number, a delayed ability that dies with its source, a
linked component that can touch the whole board, a replacement applied twice to
one event, "can't" losing to "can", a Might assignment that wins over the
arithmetic layer, the layers run backwards, decreases applied before increases,
and a Timestamp kept while its text is Inactive.

**What it found on this branch is the argument for it.** Of the 43 ability
mutants, six were not caught on the first full run, and every one was a check
that was not checking what its name said:

| the mutant | what the check was really doing |
|---|---|
| ignore a triggered ability's once-each-turn limit | the second trigger never ran: `step()` returns the PENDING decision before it runs anything, so a second `drive()` handed back the same Main Phase decision instantly. The check triggered once and called that "not twice" |
| offer an activated ability on the opponent's turn | the board had no unit of the opponent's carrying the ability, so "not offered to them" was true whatever 381 said |
| a Might assignment wipes the arithmetic layer | the mutant wrote a field the reading order made irrelevant. The defect a reader would actually write is "the assignment wins", and the mutant now writes that, in `state.might_of` |
| apply Might decreases before increases | the check re-implemented the engine's sort and compared the engine against itself. It now calls `layers.ordered` |
| finalize a triggered ability whose cost cannot be paid | paying an impossible cost raises, and the raise took the suite down instead of failing the check. The check now runs through `survives()` |
| apply a replacement effect to an event more than once | three test fixtures and one demo ability relied on 370.2 to stop applying. Removing 370.2 span them against the 32-application bound and killed the suite. Each fixture's `applies` now describes a condition the replacement actually changes — "I enter ready" says nothing about an entry that is already ready |

All six PASSED on the correct engine, and all six passed for reasons that had
nothing to do with the rule they name. That is exactly the failure the battery
exists to find, and not one of them is visible by reading the check.

Three anchors in the existing battery had to be re-pointed because this branch
moved the lines they name (`_copy_choice`'s loop, which is now shared word for
word with `_copy_effect`; `resolve_newest`'s `put_into_play`, which now keeps the
unit so a Play Effect can name it; and `damage_pool`, which now skips Stunned
units). A stale anchor is reported as STALE and tests nothing, which is why the
battery refuses to pass with one.

A mutant that is caught **by a different check from the one it names** is not
caught. Something went red, but the check whose coverage the mutant claims to
prove is still one nobody has watched fail, and recording it as proven is the
stale credit the whole battery exists to prevent. The battery reports those as
`[MISNAMED]` and exits non-zero: point `expect` at the check that actually
reddens, or tighten the mutant until the named one does.

`mutants.py` writes `proven-checks.json`, which `selftest` reads to print how
much of itself has been tested. **Commit the record in the same commit as the
check and the mutant** — CI fails if a battery run leaves the tree dirty.

**Where that guard sits in CI is the guard.** It compares the committed records
against what a run produces, so it has to come *after everything that writes
one*. It has been in the wrong place twice: first in the `package` job, which
runs no battery at all (the file could not change, so the guard could not fire),
and then between the two batteries, where it could see rules-report's record and
not deck-lab's — which is to say it could not fail for the skill this kernel
lives in. It now runs once, after both.

The record is keyed by check NAME, and the battery reads those names out of the
suite's own output. `check()` introduces a check's detail with two spaces, an em
dash and a space; the battery anchors on exactly that, and `proven_ratio`
asserts no check name contains the sequence. A looser anchor (it used to be
`\s+—`) silently truncated any name with an em dash inside it, so the name never
matched on the way back and the check lost its credit for good.

## Regenerating a golden

Only ever because a rule deliberately changed. Read the diff before committing:
a golden that moved for a reason nobody can name is the thing these files exist
to catch.

```
python3 deck_cli.py engine golden --write     # playthroughs.json
python3 deck_cli.py engine perft --write      # perft.json
python3 engine/vendor_primers.py              # chain-transitions.json (maintainer-only)
```

Issue #24 moved the playthroughs and left perft and the vendored transitions
alone. The reason: the state now carries the ability framework's records (XP,
what each seat has played this turn, continuous effects, delayed abilities,
queued triggers, the Timestamp counter) and five new per-unit fields, so every
state hash moved — while no vanilla decision tree changed, which is exactly what
perft holding still says.

Issue #23 moved all three, and the reason is in that commit: a combat now asks
between one and several `assign_damage` questions, sums Might over the units that
hold the designation rather than over the units standing there, and resolves over
three Tasks with a window between each. The decision tree from the `contested`
perft board is a different tree — the other two boards did not move, which is
what one would expect from a change confined to combat.

`vendor_primers.py` copies the chain, showdown and combat transitions out of
rules-report's verified primers. The kernel cannot read them at runtime —
copying the deck-lab folder has to be the whole install (ADR 0004) — so they are
vendored, with the primer's corpus stamp recorded beside them. Run it after a
rules update; `selftest` compares the vendored table against the primers
whenever rules-report happens to be installed next door, and always asserts that
every transition in the table is either covered by a named check or declared
unreachable with a reason.

## Throughput

`engine bench` reports the numbers gate G4 reads. On one core of an M-series
laptop, at the kernel's first slice:

Measured **interleaved** — base and branch alternating on the same machine,
nine rounds — because a number from one process and a number from another an
hour later measure the laptop as much as the engine. The figure quoted is the
**best of the nine**, not the median: contention only ever subtracts
throughput, so under load the fastest round is the closest estimate of what
the code can do, while the median mostly measures whatever else was running.
These nine ran under heavy external load and the spread was wide (base
self-play ranged 47-183 games/s); the top three rounds per side sat within 2%
of each other, which is what makes the best-of readable at all.

| | base (#59) | with the ability framework | |
|---|---|---|---|
| clones/second | 285,300 | 242,500 | -15.0%; the state grew by the registry and the stamps |
| decisions/second | 12,347 | 10,697 | **-13.4%** |
| games/second (random self-play) | 183.3 | 158.8 | **-13.4%** |
| games/second (auditable: a hash per log entry) | 50.9 | 43.7 | -14.1% |
| decisions per game | 67.4 | 67.4 | unchanged — the framework adds no decisions to a vanilla game |
| games/second, abilities attached | — | 30.8 | the cost of asking the layers a real question |

Measured on the fixture pair, not on whatever sorts first in the gauntlet, so
the number does not move when someone adds a decklist. Rigorous combat (issue
#23) cost nothing measurable: a game asks about one more question than it did
(the `assign_damage` decisions, most of which have a single legal target), and
the state hash grew by the designation and the six keyword fields per unit,
which is where the auditable rate moved.

**The ability framework costs about 13% of the vanilla throughput**, and it is
all in one place: 476's recomputation now runs at every 319 board change, because
a keyword gate has to close in the step it stops holding rather than at the next
Cleanup. A vanilla game takes the fast path — no stored effects and no registered
abilities means the printed traits are the answer and one sequence reaches it —
which is why the number moved by an eighth and not by a half.

**A game WITH abilities attached runs at 30.8 games/s**, five times slower, and
that is the honest cost of asking the layers a real question: every board change
walks every ability, re-derives what each active passive contributes, refreshes
the Timestamps (480.1), and recurs the sequence until nothing more applies. It is
the number to watch when the interpreter lands, because a real deck will have
abilities on most of its cards rather than on eight of them, and a search that
needs thousands of positions per decision cannot pay it. Two obvious levers are
untouched on purpose: the recomputation is not incremental (476 is written as a
full re-derivation and making it incremental before anything measures it is
optimising a guess), and `refresh_stamps` and `passive_effects` each re-walk
every zone rather than sharing an index.

For comparison, the table measures ~9,000 snapshot+restore/s, ~890 deepcopies/s
and ~70 turn cycles/s. The clone rate is the one that matters for search, and it
is 300x the table's because the state is flat and the generator is a single
integer rather than a 625-word Mersenne Twister (`engine/rng.py`,
`engine/state.py`).

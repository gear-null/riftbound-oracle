# How the kernel is tested

A win rate cannot tell you the engine is right. A mis-implemented rule produces
a *plausible* finished game and a *plausible* number, and the number is what
every deck verdict is computed from — so the instruments have to be the kind
that fail loudly on a change nobody intended.

Four of them come from chess and card-engine practice, two from this repo's own
discipline, and one — the differential harness against `table.py` — from having a
second implementation of the same rules lying around. All seven run on every
commit.

    python3 deck_cli.py selftest        # the suite: table + engine, ~2s
    python3 deck_cli.py mutants         # proves the suite can fail, ~25 min
    python3 deck_cli.py engine perft    # the deeper perft depths
    python3 deck_cli.py engine golden   # replay the recorded playthroughs
    python3 deck_cli.py engine soak --games 1000
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

## 3. Conservation invariants

Cheap properties no legal sequence of decisions can break, checked after every
mandatory operation when a game is created with `invariants=True`:

- every card a seat brought is in exactly one of that seat's zones — Main Deck
  cards and Rune Deck cards counted separately, because 416 sends a recycled
  rune to a different deck from a recycled card;
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
policy stream per seat**. The two games must be exact mirrors: the same events
in the same order with the seats relabelled, and therefore a paired result of
exactly 50.00%.

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

| | |
|---|---|
| clones/second | ~200,000 (noisy: 185k-290k across runs) |
| decisions/second | ~12,000 |
| games/second (random self-play) | ~186 |
| games/second (with a state hash per log entry) | ~48 |
| decisions per game | ~67 |

Measured on the fixture pair, not on whatever sorts first in the gauntlet, so
the number does not move when someone adds a decklist. Rigorous combat (issue
#23) cost nothing measurable: a game asks about one more question than it did
(the `assign_damage` decisions, most of which have a single legal target), and
the state hash grew by the designation and the six keyword fields per unit,
which is where the auditable rate moved.

For comparison, the table measures ~9,000 snapshot+restore/s, ~890 deepcopies/s
and ~70 turn cycles/s. The clone rate is the one that matters for search, and it
is 300x the table's because the state is flat and the generator is a single
integer rather than a 625-word Mersenne Twister (`engine/rng.py`,
`engine/state.py`).

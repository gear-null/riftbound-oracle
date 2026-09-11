# How the kernel is tested

A win rate cannot tell you the engine is right. A mis-implemented rule produces
a *plausible* finished game and a *plausible* number, and the number is what
every deck verdict is computed from — so the instruments have to be the kind
that fail loudly on a change nobody intended.

Four of them come from chess and card-engine practice, one from this repo's own
discipline. All five run on every commit.

    python3 deck_cli.py selftest        # the suite: table + engine, ~1.2s
    python3 deck_cli.py mutants         # proves the suite can fail, ~2 min
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

## 5. The mutation battery

This repo's own rule: *a check nobody has watched fail is not yet a check.* The
battery in `lib/mutants.py` reintroduces each defect the suite claims to catch,
runs the suite against a throwaway copy of the skill folder, and asserts the
right check goes red. A mutant that SURVIVES is a check that is lying.

The kernel's mutants are the last block of `MUTANTS` and reintroduce, among
others: dropping the going-second extra rune, resolving the Chain FIFO, skipping
the final-point rule, iterating players by seat number instead of turn order,
letting a unit enter ready, closing a Showdown on one pass, and determinizing
without redealing the opponent's hand.

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

`vendor_primers.py` copies the chain and showdown transitions out of
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
| games/second (with a state hash per log entry) | ~53 |
| decisions per game | ~66 |

Measured on the fixture pair, not on whatever sorts first in the gauntlet, so
the number does not move when someone adds a decklist.

For comparison, the table measures ~9,000 snapshot+restore/s, ~890 deepcopies/s
and ~70 turn cycles/s. The clone rate is the one that matters for search, and it
is 300x the table's because the state is flat and the generator is a single
integer rather than a 625-word Mersenne Twister (`engine/rng.py`,
`engine/state.py`).

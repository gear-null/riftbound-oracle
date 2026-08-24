---
name: deck-lab
description: Build and test a Riftbound deck against real tournament decks — deck legality (103), shuffle math over 100k hands, and a game table that holds board state while you play games out move by move. Use whenever the user wants to build, tune, critique or test a Riftbound deck, asks whether a card or a ratio is worth running, wants to know how a deck plays against the current meta, or wants to play out a game or a matchup.
---

# Riftbound deck lab

A **table**, not a player. The engine does everything that must not be imagined —
shuffle order, what you drew, whose turn it is, what a rune pool holds, what a combat
assigns, who scored and when. You do everything that requires reading a card and making
a choice.

That split is the whole design. If you guess what you drew, the game is worthless.
If code tries to read 1,037 cards' text, it is wrong in ways nobody notices.

## What is decided by code

Setup and shuffles · draws and channels · zone contents · hidden information ·
phase order and the mandatory steps inside it (ready-all, hold-scoring, channel 2,
draw 1, pool emptying, healing) · cost payment and what it exhausts · legal move
destinations · combat damage sums and lethal-first assignment · control, Conquer,
Hold, once-per-battlefield-per-turn, the final-point restriction · victory ·
deck construction legality · the shuffle math in the report.

## What is decided by you

Every play. Every target. **Every word of card text.** The table moves the card and
prints what it says; you apply the effect through explicit actions, so the log ends up
a record of physical operations that can be audited afterwards.

## Before you start

Requires Python 3.9+. No third-party packages, no network. Run from `lib/`:

    python3 deck_cli.py <command>

`python3 deck_cli.py help` lists every command and every action.

## Play from this, not from lookups

Everything a normal turn needs is here. **Do not open the rulebook to take a
turn** — a game is expensive enough without a research step per decision. The
rules corpus is for a genuine dispute, or for a card whose interaction you cannot
settle from its text.

**The turn.** `beginturn <seat>` runs all of it: ready everything you control →
Hold-score every battlefield you control (a point each) → channel 2 runes (3 for
the player going second, on their first turn only) → draw 1 → empty both rune
pools → Main Phase. `endturn` runs: heal all units → expire "this turn" effects →
empty both pools → pass. You never perform those by hand.

**Resources.** A rune pays *either* 1 Energy (exhaust it) *or* 1 Power of its
domain (recycle it to the Rune Deck) — never both. So a card costing 3 Energy
and 1 Power needs four runes, one of them matching a domain. `cast` works this
out and tells you when it cannot. Pools empty entering the Main Phase and again
at end of turn; nothing carries.

**Moving.** A unit's Standard Move exhausts it and goes base↔battlefield only —
never battlefield to battlefield unless the unit has Ganking. Arriving at a
battlefield you do not control Contests it, and *the player who contested is the
Attacker* for whatever combat follows.

**Combat.** Both sides deal damage equal to their summed Might, simultaneously.
Damage is assigned lethal-first: a unit must be given its full minimum-lethal
amount before any goes to another, and a 0-Might unit's minimum lethal is 1, not
0. Lethal is non-zero damage equalling or exceeding Might. If both sides still
have units afterwards the attackers are recalled to base. Whoever is left alone
at the battlefield takes control of it.

**Scoring.** Taking a battlefield you did not already hold is a Conquer; holding
one at the start of your turn is a Hold. Either scores once per battlefield per
turn. First to 8 points wins — unless a card changed that number, in which case
`target <n>`. At 7, a Conquer only wins if you scored *every* battlefield that
turn; otherwise you draw a card instead.

**Running out of cards** shuffles your trash into your deck and gives your
opponent a point. With an empty trash too, that repeats until they win.

The table enforces all of the above and cites the rule when it refuses you.
**Read the refusal rather than working around it** — it is the cheapest rules
lookup available.

## Building or critiquing a deck

1. **`decks`** — see what is in `gauntlet/` (real tournament lists) and `decks/` (yours).
2. **`check <deck>`** — legality against rule 103. Fix errors before anything else; an
   illegal deck does not fail loudly during a game, it just quietly plays a card it
   should not have.
3. **`analyze <deck>`** — shuffle math at 20k+ hands. Read it for:
   - `has a play` below ~90% on turns 1-2 → the curve is too high to function.
   - `stranded in hand` staying high → cards the deck cannot deploy.
   - `blocked on power` → a fixing problem, not a curve problem. Different fix:
     change the rune split, not the spells.
   - a domain below ~90% by turn 3 → the split cannot support the cards that need it.
4. **`card <name>`** — printed text and stats. Use it rather than recalling a card;
   names collide (six different Master Yi units) and text is errata'd.
5. **`report <deck>`** — the same as a self-contained HTML page, plus whatever games
   have been recorded.

## Playing a game

    new <deckA> <deckB> --seed 42 --first 0 --name irelia-vs-yi

Seat 0 is `deckA`. The seed makes the game replayable — **always record it**, because a
finding that cannot be reproduced is an anecdote.

Then, per seat:

    state --seat 0            # what seat 0 can see: its hand, the board, a count
                              # for the opponent's hand. Never look at --full mid-game.
    do 'beginturn 0; cast 0 "Stellacorn Herder" base:0; smove u9 bf:0' --seat 0

`do` takes several actions separated by `;` and applies them in order. **Batch a whole
turn** — the round trip is the dominant cost of playing at all, and `do` prints the
resulting table, so one call usually replaces a `state` and several actions.

An action either happens or it does not: a refused action rolls the table back, and
nothing after it is applied. So a batch that ends in a refusal costs you the refusal
message and nothing else — read it, fix that one action, and resend from there.

`--seat N` renders the result from that seat and records in the log which seat was
acting.

**A card's printed text is shown once**, the first time you see the card. It is not
repeated on later renders — that was about half the output of every turn. Use
`card <name>` to see it again, or `--verbose` to re-print everything.

### The rules of playing honestly

- **Decide from the seat view.** `state --seat N` and `do --seat N` show only what that
  seat knows: its own hand, the board, and a count for the opponent's. The log redacts
  the cards another seat drew, and records which seat each batch of actions was declared
  from. Nothing verifies the declaration was honest and nothing can — a mind holding both
  hands cannot be made to forget one. The redaction removes the excuse, not the
  possibility.
- **Never invent a draw.** `draw` tells you what came off the deck. If you find
  yourself writing what a card "would" be, stop.
- **Always run `precombat <bf>` before `combat <bf>`.** It prints every involved unit's
  printed text and the damage assignment that would be made, and changes nothing.
  Combat is the one step whose mistakes are irreversible: apply Might changes with
  `buff` first, then resolve. Lethal is damage *equalling* or exceeding Might, so +1 on
  a 2-Might unit facing 3 damage saves nothing.
- **Apply card text as actions.** A card reading "draw 2 and channel 1 exhausted"
  becomes `draw 0 2; channel 0 1 exhausted`. Add a `note` saying which card caused it.
- **Battlefield text is live from turn one.** It is printed once at setup. If it changes
  the points needed to win, `target <n>` — otherwise the table declares a winner early.
- **When the table refuses you, it is usually right.** Read the rule number it cites
  before working around it.

At the end: `record --note "what actually decided it"`.

## The iteration loop

1. `analyze` the deck — fix anything the shuffle math condemns. This is free and exact;
   do it before spending a single game.
2. Pick 3-4 gauntlet decks that are actually different from each other, not four
   versions of the same archetype.
3. Play each matchup at least twice, **swapping who goes first** — the extra rune
   (485.7) matters, and one game on the play tells you nothing about the other side.
4. After each game, write down the turn the game was decided and what decided it. That
   sentence is worth more than the win/loss.
5. Change **one thing**, re-`analyze`, replay the same seeds. Same seed plus one changed
   card is the only clean comparison available at this sample size.
6. `report` to collect it.

## Reporting results honestly

Played games are expensive, so samples are small, and small samples lie confidently.

- **Always state `n`.** "3-1 across 4 games" — never "75% win rate".
- The report prints a Wilson interval next to every rate. At n=4 it spans 30-95%. Quote
  it; do not quietly drop it because it is embarrassing.
- Below about 20 games per matchup, the interval is wider than nearly any difference
  worth acting on. **The game logs are the finding; the percentage is decoration.**
- Say which cards were never drawn. A card that did not appear was not tested.

## Refreshing the gauntlet

From the repo root (maintainer side, needs network):

    npm run oracle decks pull

Pulls current tournament lists into `output/decks/` and this skill's `gauntlet/`.
Run it on demand, never on a schedule — see `docs/content-and-licensing.md`.

Some pulled decks have no `chosen_champion`, because the list legally runs two champion
units of the legend's tag and only the pilot knows which one sat in the Champion Zone.
Those decks fail `check` until the field is filled in by hand. Pick one, and say in the
report which one you picked.

## Known limits — say these out loud rather than around

- **The Chain is not modelled.** Reactions, counters and the FEPR process are yours to
  narrate; `note` them. The table tracks no priority.
- **Showdowns are not modelled as a window.** A non-combat showdown resolves at the next
  cleanup, where whoever is alone at a contested battlefield takes it.
- **Card text is never executed.** In a typical tournament deck ~100% of shuffled cards
  have rules text, so almost every card in a game is applied by hand.
- **Power cost splits are approximate** for cards with two domains and a power cost —
  the data carries a count and a domain list, not one domain per printed symbol. The
  table is permissive there and `analyze` names the affected cards.
- **`analyze` measures availability, not quality.** It counts a card as castable, never
  as good, and nothing is ever spent, so late-turn "castable in hand" only rises.
- **One mind playing both seats is not two players.** Seat views redact, but they cannot
  make you forget. Treat every result as a structured way to find out how a deck fails,
  not as evidence about a matchup.

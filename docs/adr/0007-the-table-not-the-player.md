# ADR 0007 — Simulate the table, not the player

**Status:** accepted · **Date:** 2026-08

## Context

Deck design needs games. Playing games needs two things that pull in opposite
directions: **randomness and hidden information nobody may fudge**, and **judgement
about what every card does**.

The obvious build is a full rules engine — zones, phases, and a scripted effect for each
card, the way a digital client works. The pool is 1,037 cards. Measured across the 24
tournament decks pulled into `gauntlet/`, **every shuffled card in a typical list has
rules text**: the Irelia list is 39 of 39. So "script the cards" is not a long tail after
a vanilla core, it is the entire deck. That is an engine on the scale of a commercial
client, and it would be wrong in ways nobody notices, because a subtly mis-scripted card
produces a plausible game.

The opposite build — an agent narrating games in prose — fails faster and worse. An agent
asked what it drew will produce a card that suits its plan. Not dishonestly; it has no
deck order to consult, so there is nothing else it can do. Every number that comes out of
such a game is an artefact of the narrator.

## Decision

Split on **what must not be imagined** rather than on what is hard.

Code owns the table: shuffles, draws, zone contents, hidden information, phase order and
the mandatory steps inside it, cost payment, legal move destinations, combat damage sums
and lethal-first assignment, control and scoring and victory, deck legality.

The reader owns the play: every decision, every target, and **every word of card text**.
The table moves the card and prints exactly what it says; the effect is applied through
the same primitive actions the rules define (413-444).

The log therefore records physical operations, not intentions, and can be audited move by
move afterwards.

## Consequences

- **Card text is never executed, so it can never be executed wrongly.** The failure mode
  moves from silent to visible: a misread card is in the log, in the reader's own actions.
- **Games are expensive.** Every decision is a reasoning step, so a matchup is measured in
  tens of games, not hundreds. This is why the deck report is split in two: shuffle math
  at 50,000 trials, because it needs no decisions, and played games with `n` and a Wilson
  interval printed beside every rate. Merging them into one win-rate would launder a 3-1
  into a number that looks like the 50,000-trial one.
- **The table must refuse rather than assume.** `can_pay` says why a cost cannot be met;
  a Standard Move from battlefield to battlefield is refused by name (144.4.c); a second
  Score on one battlefield in a turn is refused (470). A permissive table is worse than
  no table, because it produces confident wrong games.
- **Where the data is thin, be permissive and say so.** Card data carries a Power count
  and a domain list, not one domain per printed symbol, so for the 41 cards with two
  domains and a Power cost the exact split is unrecoverable. Those are payable from any
  of the card's domains — too permissive rather than too strict, and named in the report,
  because a table that refuses a legal play is the failure that stops the tool being used.
- **One mind playing both seats is not two players.** Seat views redact the opponent's
  hand and neither deck's order, which is the most that can be done; it cannot induce
  forgetting. Results are a structured way to find out how a deck fails, not evidence
  about a matchup.
- **The Chain is not modelled.** Reactions, counters and the FEPR process are narrated
  through `note`. Modelling priority without modelling card text would add ceremony
  without adding correctness.

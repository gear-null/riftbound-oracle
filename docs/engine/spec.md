# The kernel, rule by rule

What the engine implements, what it simplifies, and what it does not touch yet.
One row per Core Rules area; the status column is the honest one, because the
failure mode this whole project is trying to avoid is **silent partial
coverage** — a rule that looks handled because nothing crashes.

Legend: **implemented** means the rule is executed and a named check pins it.
**simplified** means something is executed but not all of it, and the row says
what is missing. **out of scope** means this slice does not touch it at all and
names the issue that will.

Scope of this slice (issue #22): two decks of **vanilla** cards — real gauntlet
decklists, but no card text is executed. Units are bodies with Might and a cost;
spells and gear are played (cost paid, Chain used) and do nothing; battlefields
and legends have no abilities. Everything about *structure* is meant to be right.

## Setup, zones and objects

| CR | module | tests | status |
|---|---|---|---|
| 104-109 spaces and zones | `state` | `engine_setup` | implemented — bases, battlefields, hand, main deck, rune deck, trash, banishment, champion zone, the Chain |
| 110-118 the setup process | `turn.setup` | `engine_setup` | implemented — separate shuffles per seat, one battlefield each from three, four cards, mulligans in turn order |
| 112 the Chosen Champion | `turn.setup`, `game._ask_main` | `engine_setup` | implemented — set aside into the Champion Zone (not shuffled in) and playable from there |
| 115 turn order | `state.turn_order` | `engine_setup`, `engine_instruments` | implemented — drawn from the shared stream; every loop over both players goes in turn order (303.2.a) |
| 119-187 object properties | `state.new_unit` | `engine_combat` | simplified — id, name, controller, owner, location, exhausted, damage, buffs, Might. Statuses beyond exhausted, and attachment, are out of scope (#23 onwards) |
| 188-192 control and Contested | `turn.cleanup_once`, `actions.apply_contested` | `engine_movement`, `engine_showdowns` | implemented — 190.3.a.1 application, 190.4.a maintenance, 190.4.c loss, 323.11 removal and 323.11.a re-application |
| 193-196 winning | `actions.check_victory` | `engine_scoring` | implemented |

## The turn

| CR | module | tests | status |
|---|---|---|---|
| 300-306 the turn | `turn` | `engine_turn` | implemented |
| 307-310 the four states | `state.turn_state` | `engine_chain`, `invariants` | implemented — neutral/showdown x open/closed |
| 311-313 priority and focus | `chain`, `state` | `engine_chain`, `engine_showdowns` | implemented for the transitions the vanilla game reaches. Priority in the Main Phase is implicit (the Turn Player is asked), not stored |
| 314-317 the phases | `turn.enter_phase`, `turn.run_task` | `engine_turn` | implemented — Awaken, Beginning (Scoring Step), Channel, Draw, Main, Ending (Ending + Expiration Steps) |
| 317.2.f return to the start of the Expiration Step | — | — | **declared gap**. Nothing in the vanilla slice can put an item on the Chain during the Expiration Step — a card would have to be played, and 331.1 closes the state to that — so the loop has no way to run once. Written down rather than written: speculative machinery for a path nothing reaches is machinery nobody can watch fail |
| 315.2.b.2 the Scoring Step Holds ALL | `scoring.hold_all` | `engine_scoring` | implemented, and it does not stop early. 472 decides the win "when a cleanup occurs", so a Turn Player one point short who controls both battlefields Holds both and finishes the step PAST the Victory Score. Deciding the win inside the Score instead made the second Hold unreachable — a Score the rules say happens, skipped, and invisible because the game is won either way |
| 318-324 cleanups | `turn.cleanup_once`, `turn.run_cleanup` | every group | implemented — all ten numbered tasks **in the order 323 numbers them**, repeated until the state settles (322), with the Special Cleanup inserts of 466.1.a and 317.2 (324). Task 9 before task 10 is load-bearing: both need a Neutral Open State and opening either leaves it, so a Showdown staged at one battlefield opens *instead of* a Combat staged at another, which waits for a later cleanup |
| 323.2 Attacker/Defender designations per unit | — | — | **out of scope** — nothing reads a per-unit designation without card text. The battlefield-level designation combat needs is `contested_by` (464.2.c.1). Issue #23 |
| 323.4 Deathknell triggers | — | — | out of scope — triggered abilities are card text |

## The Chain and Showdowns

The spec here is `rules-report`'s two verified primers. Their transitions are
vendored into `lib/engine/goldens/chain-transitions.json`, and `selftest`
refuses to pass unless every one of them is either covered by a named check or
declared unreachable with a reason.

| CR | module | tests | status |
|---|---|---|---|
| 325-331 the Chain | `chain`, `state` | `engine_chain` | implemented |
| 332-336 tasks, HOT | `game._tick`, `state.tasks` | every group | implemented — outstanding Tasks are handled before FEPR (334), and a Task incurred partway through goes to the front of the queue (334.2.a) |
| 337-340 FEPR | `chain.fepr_step` and friends | `engine_chain` | implemented. 6 of the 20 primer transitions are unreachable until card text lands (they all need something with Reaction, or a second pending item); `selftest.TRANSITION_COVER` names each one |
| 341-348 showdowns | `turn.open_showdown`, `chain.showdown_step` | `engine_showdowns` | implemented except 346 — a Chain cannot open inside a vanilla Showdown, so there is no code for the Focus pass that follows one closing. Written as a gap rather than as speculative machinery, because 346.1 needs to know WHY the Chain opened and nothing yet does |
| 349-359 playing cards | `chain.play_card`, `chain.finalize_one` | `engine_chain` | simplified — steps 1, 2 (location only), 3-4 (printed cost only), 5 (location and cost), 6. Cost modification (356.1-356.5), additional costs, and non-standard costs are out of scope |
| 360-406 abilities | — | — | **out of scope** — the whole of card text. Issues #25 onwards |

## Actions, movement, combat, scoring

| CR | module | tests | status |
|---|---|---|---|
| 413 draw, 416 recycle, 422 discard, 427 banish, 428 trash, 429 add, 430 channel | `actions` | `engine_scoring`, `engine_turn` | implemented |
| 431 burn out | `actions.burn_out` | `engine_scoring` | implemented — including 431.3's repeat, which is the only way a game between two empty decks ends |
| 407-444 the other named game actions | — | — | out of scope until the DSL needs them (issue #25) |
| 445-453 movement | `actions.move`, `actions.standard_move_legal` | `engine_movement` | implemented for 1v1 — 144.4's two legal shapes, 450's Contested, 453's cleanup. 447.2.a/447.2.b are multiplayer and team rules with no effect in Duel |
| 454-458 recalls | `actions.recall` | `engine_movement`, `engine_combat` | implemented |
| 459-462 combat staging | `turn.cleanup_once` | `engine_showdowns` | implemented |
| 463-464 the Combat Showdown Step | `turn.open_showdown` | `engine_showdowns` | implemented at the battlefield level; per-unit designations are out of scope |
| 465 the Damage Step | `combat.damage_step` | `engine_combat` | simplified — summed Might, lethal-first assignment computed by the engine (465.2.c.3, 465.2.c.4, 142.4.b), dealt simultaneously. The assignment is not yet a **decision**: the `assign_damage` kind exists and is not emitted. Issue #23 |
| 466 the Resolution Step | `combat.resolution_step` | `engine_combat` | simplified — run as one Task rather than three with a FEPR window between each, because no vanilla item can reach the Chain in between. 466.3.d.1's re-stage is written and unreachable |
| 467-472 scoring | `scoring` | `engine_scoring` | implemented — Hold (469.2), Conquer (469.1), once per battlefield per turn (470), the final-point rule (471.1.b.1) and its non-Conquer exemption (471.1.a.1), victory (472) |
| 471.2 Score abilities | — | — | out of scope — battlefield text is card text |
| 473-480 layers | — | — | **out of scope**. Issue #26 |
| 701-765 buffs, keywords, misc | — | — | **out of scope**. `buffs` is carried on a unit and added to Might (703); nothing sets it |
| 800-829 the 25 keywords | — | — | **out of scope**. Issues #27 onwards |
| 481-486 modes of play | `deckfile.MODE` | `engine_setup` | 1v1 Duel only: 8 points, 2 battlefields, 4-card opening hand, 2 runes a turn, and 485.7's extra rune for the player going second |

## Deliberate divergences from `table.py`

The table (ADR 0007) is a different tool and the two disagree in three places on
purpose. All three are engine behaviour that the table leaves to its reader.

1. **A unit enters the board exhausted** (359.2.c). `table.put_into_play`
   defaults to ready and lets the reader exhaust it. The engine cannot leave
   that to anyone, and a unit that enters ready can move the turn it is played,
   which changes every tempo line in the game.
2. **Battlefields are placed in turn order**, index 0 to the player going first.
   The table appends them by seat number. 485.5 places them "simultaneously" and
   says nothing about order, so the order is the implementation's to choose;
   turn order is the choice under which a mirrored game keeps its battlefield
   indices, and the perfect-symmetry test depends on that.
3. **Every loop over both players goes in turn order** (303.2.a), including the
   setup draws and the Main Phase pool emptying. The table's loops are over seat
   numbers, which is invisible to a reader playing one game and fatal to a
   mirror test.

## Known simplifications, collected

So they are one list rather than scattered through the table above:

- The `assign_damage`, `cost`, `modal`, `optional`, `order` and
  `resolve_manually` decision kinds exist in the API and are **not yet emitted**.
  `decisions.EMITTED` is the set that is, and a check asserts a vanilla game
  never emits anything outside it.
- Per-unit Attacker/Defender designations (323.2, 464.2.c.3) are not modelled.
- The Resolution Step (466) runs as one Task; its three FEPR windows are not
  separate.
- Cost modification (356.1-356.5) is not implemented: a card costs what it says.
- A card with two domains and one Power symbol has its requirement widened to
  "any of the card's domains", because the card data carries a Power count and a
  domain list rather than a domain per symbol. Inherited from the table, and
  permissive on purpose.
- 331/343's "by default" is read as "always" in this slice: nothing is legally
  timed in a Closed or Showdown State, because Reaction is card text.
- 317.2.f's "return to the start of the Expiration Step" has no code: nothing
  vanilla reaches the Chain during that step.
- Points are **not** capped at the Victory Score. 315.2.b.2 Holds every
  battlefield and 472 decides the win at the following cleanup, so a game can
  finish 9-4. `invariants._points` asserts the property that actually matters —
  a position meeting 472 always has a Cleanup outstanding to notice it.

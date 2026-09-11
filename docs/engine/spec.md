# The kernel, rule by rule

What the engine implements, what it simplifies, and what it does not touch yet.
One row per Core Rules area; the status column is the honest one, because the
failure mode this whole project is trying to avoid is **silent partial
coverage** — a rule that looks handled because nothing crashes.

Legend: **implemented** means the rule is executed and a named check pins it.
**simplified** means something is executed but not all of it, and the row says
what is missing. **out of scope** means this slice does not touch it at all and
names the issue that will.

Scope so far: two decks of **vanilla** cards — real gauntlet decklists, but no
card text is executed. Units are bodies with Might and a cost; spells and gear
are played (cost paid, Chain used) and do nothing; battlefields and legends have
no abilities. Everything about *structure* is meant to be right.

Issue #22 built the kernel; issue #23 made combat, damage assignment, scoring and
victory rigorous. The **combat keywords are hooks**: Tank, Backline, Assault,
Shield, Deflect and Bonus Damage are fields on a unit, every rule that consumes
them is implemented and tested, and nothing sets them yet because setting them is
reading card text (issue #27).

## Setup, zones and objects

| CR | module | tests | status |
|---|---|---|---|
| 104-109 spaces and zones | `state` | `engine_setup` | implemented — bases, battlefields, hand, main deck, rune deck, trash, banishment, champion zone, the Chain |
| 110-118 the setup process | `turn.setup` | `engine_setup` | implemented — separate shuffles per seat, one battlefield each from three, four cards, mulligans in turn order |
| 112 the Chosen Champion | `turn.setup`, `game._ask_main` | `engine_setup` | implemented — set aside into the Champion Zone (not shuffled in) and playable from there |
| 115 turn order | `state.turn_order` | `engine_setup`, `engine_instruments` | implemented — drawn from the shared stream; every loop over both players goes in turn order (303.2.a) |
| 119-187 object properties | `state.new_unit` | `engine_combat`, `engine_keywords` | simplified — id, name, controller, owner, location, exhausted, damage, buffs, Might, the Attacker/Defender designation, and the six combat keyword fields (`tank`, `backline`, `assault`, `shield`, `deflect`, `bonus`). Statuses beyond exhausted, and attachment, are out of scope (#27 onwards) |
| 142.4.b lethal damage | `combat.minimum_lethal` | `engine_combat`, `engine_assignment` | implemented — lethal is a NON-ZERO amount at or above Might, so a 0-Might unit's minimum lethal is 1 |
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
| 323.2 Attacker/Defender designations per unit | `combat.apply_designations`, `turn.cleanup_once` | `engine_designations` | implemented — all three clauses as one loop: a Unit here without a designation gains its controller's (323.2.a), one with the wrong one swaps (323.2.b), one anywhere else loses it (323.2.c). This is what 464.2.c.3.a defers to, and `invariants._designations` refuses a position where any of it is out of step |
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
| 454-458 recalls | `actions.recall` | `engine_movement`, `engine_combat` | implemented — 455's relocation, 456's "not a Move", 458.1's damage and statuses surviving it. 466.1.a.2's attacker recall is what exercises it |
| 459-462 combat staging | `turn.cleanup_once` | `engine_showdowns`, `engine_combat_steps` | implemented — 460's four conditions, 461's definition of Staged, 461.2's "stops being Staged before the steps start, so nothing is resolved", 461.3's Combat Showdown. 462.1-462.3 are multiplayer rules with no effect in Duel |
| 463-464 the Combat Showdown Step | `turn.open_showdown`, `combat.designate` | `engine_showdowns`, `engine_designations` | implemented — 464.2.c.1's Attacker (whoever's unit applied Contested, not the Turn Player), 464.2.c.2's Defender, 464.2.c.3's per-unit designations, 464.2.c.3.a's deferral to the next Cleanup, 464.2.c.1.a's Focus on opening and 464.2.c.1.b's "a Showdown already ongoing keeps whoever has Focus". 464.2.e's triggered abilities and 464.2.f's Combat Chain need card text |
| 465 the Damage Step | `combat.damage_step`, `combat.assign_damage` | `engine_assignment`, `engine_combat_steps` | implemented — 465.1's skip when one side is gone, Might summed over the units that HOLD the designation (465.2.a-b), the assignment as an **`assign_damage` decision** asked one target at a time (465.2.c), lethal-first (465.2.c.3) and minimum-lethal (465.2.c.4, 142.4.b), dealt simultaneously (465.2.c.1.a, 465.2.d), and 465.3's cancellation of the Tasks the Showdown left outstanding |
| 465.2.c.5-c.10 assignment corner cases | `combat.validate_assignment` | `engine_assignment` | simplified — c.5 (replacement applies to the assignment) is where Bonus Damage lands; c.6's "obey every restriction if able" is the validator; c.7's free order within a priority is why every eligible unit is an option. **c.8 and c.9** — the player's choice of which exclusionary requirement applies to a unit carrying two — are a declared gap: a unit with both Tank and Backline is assigned as a Tank. **c.10** (a unit that cannot be dealt damage) needs an effect no vanilla card has |
| 466 the Resolution Step | `combat.result_step`, `combat.control_step`, `combat.end_step`, `combat.fepr_window` | `engine_combat_steps` | implemented — 466.1's Combat Special Cleanup, then 466.3, 466.5 and 466.7 as three separate Tasks with 466.2 / 466.4 / 466.6's window between each. 466.3.d.1's re-stage is written and unreachable (see below) |
| 466.5 establishing control | `combat.control_step` | `engine_combat_steps` | implemented, and **narrower than it reads**. 466.1's Combat Cleanup re-runs 323.8, so a battlefield the winning ATTACKER still occupies is Contested by a player with units present and therefore has a Showdown staged — which makes 466.5's "if no Showdown or Combat is staged at this location" false. Control is then settled one cleanup later by 348.2.a, with the same Conquer. 466.5 fires when the attackers were repelled or wiped, which is 466.5.e's case. Both paths score the point; only the rule id differs, and the checks say which |
| 467-472 scoring | `scoring` | `engine_scoring` | implemented — Hold (469.2), Conquer (469.1), once per battlefield per turn (470), the final-point rule (471.1.b.1) and its non-Conquer exemption (471.1.a.1), victory (472) |
| 471.2 Score abilities | — | — | out of scope — battlefield text is card text |
| 701-705 buffs | `state.might_of` | `engine_keywords` | implemented — 703's +1 Might each. 702.3's one-buff-per-unit cap is not enforced because nothing adds a buff yet |
| 706-711 Mighty | `state.is_mighty` | `engine_keywords` | implemented — 708's threshold read off CURRENT Might (710). 711's printed-Might reading for non-Board zones has nowhere to apply: no rule this kernel executes asks about a unit in a zone |
| 712-715 Bonus Damage | `combat.bonus_damage`, `combat.damage_pool` | `engine_keywords` | implemented as a hook — 714 sums every instance and applies it once, 714.1/714.2 clamp a negative total to none, and it lands on the ASSIGNMENT rather than the dealt amount because 465.2.c.5 says a modification of the resulting damage applies to the assignment instead. 715.2/715.3's multi-target and split cases need card text |
| 807 Assault, 814 Shield | `state.might_of` | `engine_keywords` | implemented — conditional on the DESIGNATION (807.1.d, 814.1.d), not on which side of the battlefield the unit stands. Nothing grants them yet |
| 809 Deflect | `actions.deflect_surcharge` | `engine_keywords` | hook only — the surcharge and who pays it (809.1.c) are implemented; nothing targets anything yet, so no play goes through it |
| 815 Tank, 826 Backline | `combat.eligible_targets`, `combat.validate_assignment` | `engine_keywords` | implemented as assignment-order restrictions: Tank before plain before Backline, with 465.2.c.7's free order inside each priority |
| 473-480 layers | — | — | **out of scope**. Issue #26 |
| 716-765 the rest of the keyword machinery | — | — | **out of scope**. Issues #27 onwards |
| 800-829 the 25 keywords | `state`, `combat` | `engine_keywords` | the six combat-relevant ones are hooks with their consuming rules implemented (807, 809, 814, 815, 826, and 706's Mighty). The other nineteen are out of scope. Issues #27 onwards |
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
4. **Victory is decided at a Cleanup** (472, 323.1), not inside the Score. The
   table checks immediately, which is right for a tool a person drives and wrong
   for one that plays: deciding it inside the Score made 315.2.b.2 unfinishable,
   because a Turn Player on 7 controlling both battlefields would win on the
   first Hold and never take the second. Both agree on WHO wins; they differ on
   when it is noticed, and `engine/parity.py` knows that by name.

## Known simplifications, collected

So they are one list rather than scattered through the table above:

- The `cost`, `modal`, `optional`, `order` and `resolve_manually` decision kinds
  exist in the API and are **not yet emitted**. `decisions.EMITTED` is the set
  that is — `assign_damage` joined it with issue #23 — and a check asserts a
  vanilla game never emits anything outside it.
- 465.2.c.8 and 465.2.c.9's choice of which exclusionary assignment requirement
  applies to a unit carrying two: a unit with both Tank and Backline is assigned
  as a Tank, and the choice is not offered.
- 465.2.c.10's "a unit that cannot be dealt damage" is not modelled; nothing
  vanilla can make a unit undamageable.
- The keyword fields on a unit are never set by anything. Every rule that reads
  them is implemented and checked against a hand-built board.
- 702.3 (one buff per unit) is not enforced, because nothing adds one.
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

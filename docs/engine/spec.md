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
card text is *parsed*. Units are bodies with Might and a cost; spells and gear
are played (cost paid, Chain used) and do nothing unless an ability is attached
to them by hand. Everything about *structure* is meant to be right.

Issue #22 built the kernel; issue #23 made combat, damage assignment, scoring and
victory rigorous; issue #24 built the **ability framework** — the machinery a card
script will be compiled into. An `Ability` carries Python callables, the suite and
`engine/demo.py` hand-build them, and the interpreter (#26) will supply
script-driven ones. So "no card text is executed" has become "no card text is
*read*": the executing half is here and exercised.

The **combat keywords are hooks**: Tank, Backline, Assault, Shield, Deflect and
Bonus Damage are fields on a unit, every rule that consumes them is implemented
and tested, and nothing prints them yet because printing them is reading card
text (issue #27). A layer-2 grant can now put them there (477.2).

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
| 323.4 Deathknell triggers | `actions.to_trash`, `abilities.emit` | `engine_abilities` | implemented as the `die` event. 383.2.c.1 is the awkward half and it is handled: the object is gone by the time the event exists, so its own abilities are read from the copy that left rather than from a zone |

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
| 349-359 playing cards | `chain.play_card`, `chain.finalize_one` | `engine_chain` | simplified — steps 1, 2 (location, and 355.1's "as I am played" as an event), 3-4, 5 (location and cost), 6. 356.1.b's ignoring and 356.3/356.4's increases and discounts arrive through a Replacement Effect (see below); 355.3's modes, 355.14's splitting and non-standard costs on a CARD are out of scope |
| 360-366 passive abilities and presence | `abilities` | `engine_abilities` | implemented — 363/364's statements of fact as a `modifier` that contributes to the layers, 364.3's conditional passives as a keyword gate, and presence (365.1, 366.1) as a zone list on the ABILITY rather than on the card, so 366.2.a's cost-altering passive functions from the hand |
| 367-375 replacement effects | `replacements` | `engine_replacements` | implemented for the six shapes the census counted — see the section below |
| 376-381 activated abilities | `abilities.activatable`, `abilities.activate` | `engine_abilities` | implemented — 377.3.a's declaration, 378's "the controlling player chooses when", 380's Board-only default, 381's own-turn-and-Open-State timing, and 402.3's refusal to offer one whose cost cannot be paid |
| 382-388 triggered and reflexive | `abilities.emit`, `abilities.put_triggers_on_chain` | `engine_abilities` | implemented — 383.2.c's evaluation after the inciting event, 383.3's pending → finalizing, 383.3.a's "you may" as an `optional` decision at finalization, 383.3.d's `order` decision and 383.3.d.1's Turn Order across seats, 383.3.e/383.1.b's frequency, 383.2.c.1's trigger from an object that has already left the Board (808), and 387/388's Reflexive Triggers |
| 389-392 delayed abilities | `abilities.delay`, `abilities.retire_delayed` | `engine_abilities` | implemented — kept on the STATE, because 392 makes a Delayed Ability fire whether or not its source is still on the board. 390.2's windows are a closed list (`next`, `this_turn`, `end_of_turn`) and 317.2.d retires the ones that were this turn's |
| 393-397 linked abilities | `abilities.link_record`, `abilities.linked_objects` | `engine_abilities` | implemented as a relation over a SET, not as a kind — 396 says "Linked Abilities can contain component Abilities of any type", so `Ability.link` is a name two abilities on one source share. 397's bound is enforced: a component sees exactly the objects the set affected |
| 398-406 playing an ability | `abilities.finalize`, `chain.finalize_one` | `engine_abilities` | implemented — 401's Pending Item with no card behind it, 402.1's "you may", 402.4/404.2's removal without being countered, 403/404's cost, 405's legality and 406. 400.2's Add ability resolves the moment it is finalized |
| 201-212 costs | `abilities.Cost`, `actions.pay_cost` | `engine_abilities` | simplified — 204.1's base costs and 204.3's costs-within-instructions come through one `Cost`, which charges Energy, Power, an exhaust (414) and XP (730.2), and 203.3's "a cost whose game action is impossible cannot be paid" gates all of them. 204.2's **additional costs are a hook**: `Cost.extra`/`extra_can` are a pair of callables the cost calls, and nothing sets one, because what sets one is card text (#26) — so unlike the rest of this row they have no check behind them. 204.4's Applied Costs and counters other than Buffs are out of scope |
| 473-480 layers | `layers` | `engine_layers` | implemented — see the section below |
| 720-725 Inactive | `abilities.active` | `engine_abilities` | implemented as far as gates need it — 721.2's "do not trigger, do not apply, cannot be activated" and 722.1's "the keyword is still there to be referenced". 724's Effect Text on an unattached card has nothing to apply to: attachment is out of scope (#27) |
| 726-727 dependent keywords | `abilities.Gate` | `engine_abilities` | implemented for all three the CR defines — [Legion] (812.1.c), [Level N] (824.1.c/824.1.d) and [Empowered] (828.1.c) — evaluated continuously and never latched, so a gate that closes mid-turn stops its passive mid-turn |
| 728-733 XP | `actions.gain_xp`, `actions.spend_xp` | `engine_abilities` | implemented — 730's gain and spend, 729.2's Public Information. It exists because 824 gates on it |

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
| 466.5 establishing control | `combat.control_step`, `combat.restaged` | `engine_combat_steps` | implemented — the side left standing takes the battlefield inside the Resolution Step, and that is a Conquer (466.5.d), whether it attacked or defended (466.5.e). **"If no Showdown or Combat is staged at this location" is read as 466.3.d.1 and nothing else**, because 466.3.d.1 is the only thing that stages anything here during the step. Reading the `sd_staged`/`cb_staged` flags instead was wrong: 466.1's Combat Cleanup re-runs 323.8, so a battlefield the winning ATTACKER still occupied was marked staged, 466.5 stood down, and control arrived a Cleanup later through a Showdown the rules never open — two Focus windows nobody is entitled to, and a real Combat staged elsewhere delayed behind it. The flags are bookkeeping that 466.5.a invalidates one line later. The combat primer does not contradict this: its s4 exits are 466.3.d.1's re-stage and 466.7's settle, and settling inside the step is the second of those |
| 467-472 scoring | `scoring` | `engine_scoring` | implemented — Hold (469.2), Conquer (469.1), once per battlefield per turn (470), the final-point rule (471.1.b.1) and its non-Conquer exemption (471.1.a.1), victory (472) |
| 471.2 Score abilities | `scoring._score_triggers` | `engine_abilities` | implemented as the `conquer` and `hold` events, raised AT the battlefield that Scored. 383.4.c.2.c and 383.4.d.2.c are honoured: a point withheld by 471.1.b.1 still triggers them |
| 701-705 buffs | `actions.buff`, `actions.spend_buff`, `state.might_of` | `engine_keywords`, `engine_layers` | implemented — 703's +1 Might each, 702.3.a's refusal to place a second (with 426.1.c keeping the unit a legal choice anyway), 702.2.b's spend and 702.2.b.1's refusal to spend from a unit with none. 705 falls out of the object going with the unit |
| 706-711 Mighty | `state.is_mighty` | `engine_keywords` | implemented — 708's threshold read off CURRENT Might (710). 711's printed-Might reading for non-Board zones has nowhere to apply: no rule this kernel executes asks about a unit in a zone |
| 712-715 Bonus Damage | `combat.bonus_damage`, `combat.damage_pool` | `engine_keywords` | implemented as a hook — 714 sums every instance and applies it once, 714.1/714.2 clamp a negative total to none, and it lands on the ASSIGNMENT rather than the dealt amount because 465.2.c.5 says a modification of the resulting damage applies to the assignment instead. 715.2/715.3's multi-target and split cases need card text |
| 807 Assault, 814 Shield | `state.might_of`, `layers` | `engine_keywords`, `engine_layers` | implemented — conditional on the DESIGNATION (807.1.d, 814.1.d), not on which side of the battlefield the unit stands, and 807.2's summing of granted instances onto the printed one is what a layer-2 `grant` now produces. No card PRINTS one yet (#27) |
| 809 Deflect | `actions.deflect_surcharge` | `engine_keywords` | hook only — the surcharge and who pays it (809.1.c) are implemented; nothing targets anything yet, so no play goes through it |
| 815 Tank, 826 Backline | `combat.eligible_targets`, `combat.validate_assignment` | `engine_keywords` | implemented as assignment-order restrictions: Tank before plain before Backline, with 465.2.c.7's free order inside each priority |
| 423 Stun, 441 Empower, 424 Reveal | `actions` | `engine_layers`, `engine_abilities` | implemented — 423.1.b's "no Might to the Damage Step", 423.1.c's "still needs its full Might to die", 423.1.a.2's loss at the end-of-turn cleanup, and both states as trigger events |
| 716-765 the rest of the keyword machinery | — | — | **out of scope**. Issues #27 onwards |
| 800-829 the 25 keywords | `state`, `combat` | `engine_keywords` | the six combat-relevant ones are hooks with their consuming rules implemented (807, 809, 814, 815, 826, and 706's Mighty). The other nineteen are out of scope. Issues #27 onwards |
| 481-486 modes of play | `deckfile.MODE` | `engine_setup` | 1v1 Duel only: 8 points, 2 battlefields, 4-card opening hand, 2 runes a turn, and 485.7's extra rune for the player going second |

## Replacement effects, shape by shape

The census counted them before any of this was written: **59 of 389 gauntlet
cards with text (15%)** carry one, over six kinds, and those six are **69
gauntlet clauses**. Those numbers are why the mechanism exists and why it is only
as big as it is — two of the six are not interception at all, and the two that
genuinely have to intercept an event are 22 clauses across 16 cards.

| kind | gauntlet clauses | module | status |
|---|---|---|---|
| `cost_replacement` | 19 | `replacements.cost_modifiers`, `actions.total_cost` | implemented — arithmetic inside 356, applied in 356's order: 356.1.b's zeroing first, then 356.3's increases and 356.4's discounts. Per COMPONENT, because 356.4.c applies a component discount before a total one |
| `enters_modified` | 17 | `replacements.apply` at `actions.put_into_play` | implemented — 369.3's "describing how the unit enters". The entering object's own replacements are found through `abilities.entering_sources`, because at that instant it is in no zone a walk can see (370.3) |
| `instead` | 15 | `replacements.apply` | implemented — the event does not happen and the replacement's Game Actions do (369, 370.1.b) |
| `ignoring_cost` | 8 | `replacements.cost_modifiers` | implemented — 356.1.b.1's "ignoring its cost" and 356.1.b.2's naming of one component |
| `would` | 7 | `replacements.apply` | implemented — the event happens with the replacement's changes on it (369) |
| `as_enters` | 3 | `replacements.apply` | implemented — 370.1.b.1's "the described event is replaced by that same event plus the game action" |

Around them: **370.2's once per event**, carried through the replacing events and
not reset with each one; **054.1's can't beats can**, a flag on the ability
rather than a guess from what its callable returns; and **371.1's "once each
turn"**, counted per object and kept in a different key from 383.3.e's so one
cannot spend the other's allowance.

The replaceable events are a closed set — `enter`, `die`, `damage` — and it is
exactly what some rule builds: a check scans the package both ways, so a name
with no call site is as much a failure as a call site with no name. An event
outside the set is refused rather than silently unreplaceable. A draw and a Score
are not replaceable here because nothing raises them as events; 431's burn out
and 471's point are the two that will want it first.

**Declared gap: 371.2's "may" and 372's ordering are not decisions.** 371.2 lets
the controller choose whether to apply a replacement, and 372 lets the controller
of the object being acted on choose the order when several apply. Neither is
asked. The reason is structural rather than an oversight: a replacement is
applied *inside* a mandatory operation (`to_trash`, `put_into_play`, the Damage
Step), and the decision API cannot suspend one partway through — `g.ask` records
a question and the surrounding code keeps running. Asking would mean turning
every replaceable action into a Task with its own resumption, which is the
interpreter's work (#26) and not this slice's. So the order is 373.1's own rule
— Turn Order across controllers — and then 480.3's Timestamp within one, and a
`may` replacement applies. Both are watched by checks that say what they do
rather than what the CR says.

## Layers

473-480 is a **recomputation**, not a sequence of mutations, which is what 475.1
says it is. `layers.recompute` resets the derived traits once, applies each
effect at most once (476.1), and recurs until nothing more can apply (476.2).

| CR | status |
|---|---|
| 476 the loop | implemented as written — reset once, apply-once, recur. The order the layers run in is observable in WHEN an effect becomes applicable: a layer-2 grant whose condition a layer-3 effect creates lands on the *next* sequence, and a check reads the sequence count to watch it happen |
| 477.1 trait-altering | implemented for Might assignment (477.1.a.1) and Controller (477.1.a). Name, Super Type, Type, Tags, Cost, Domain and 477.1.b's Copy effects are out of scope — nothing reads them yet |
| 477.2 ability-altering | implemented — granting and removing a keyword, and granting a whole ability by registry key. 477.2.c's Attached cards are out of scope (#27) |
| 477.3 arithmetic | implemented — increases before decreases (477.3.e.1, 477.3.e.2). 477.3.b's snapshotting falls out of 476.1's apply-once: what an effect selected when it applied is what it keeps. 477.3.c's "cannot increase by a negative amount" and 477.3.d's Attached Might Bonuses are not implemented |
| 478-479 dependency | **declared gap.** Effects in one layer are ordered by Timestamp. 476.2's recursion already produces 479.2's outcome for the reachable shape — an effect whose scope another effect widens picks the wider scope up on the next sequence, because its scope is recomputed until it applies. Where the two genuinely differ is an effect that the other DISQUALIFIES, and nothing in the census's vocabulary can yet express one |
| 480 timestamps | implemented — 480.1's monotone counter, 480.2's loss of a Timestamp when text goes Inactive and a new one when it comes back, 480.3's earliest-first within a layer and sublayer |

**A Buff is not a layer-3 effect**, and the pair is the reason `actions.buff` and
`actions.give_might` are separate. 702 makes a Buff a counter on the unit and 703
gives each one +1 Might: it survives 317.2.d's expiry and goes away only when the
unit leaves play (705), and 702.3.a refuses a second one. `give_might` is a
continuous effect with a duration (`this_turn`, `permanent`, `this_combat`,
`until_event`), stacks without limit, and expires.

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

- The `modal` and `resolve_manually` decision kinds exist in the API and are
  **not yet emitted**. `optional`, `order` and `cost` joined `EMITTED` with issue
  #24, and because a name in that tuple is a claim, the suite asserts it has
  WATCHED each of the three be emitted as well as that a vanilla game emits none
  of them.
- 371.2's "may" and 372's ordering on replacement effects are not decisions; the
  Replacement effects section above says why, and what happens instead.
- 478-479's Dependency between effects in one layer is Timestamp order; the
  Layers section above says what that does and does not cover.
- `delayed_next` and `nth_time` are census trigger rows that are **not runtime
  events**: 390.2's "the next time" is a window and 383.1.b's "the first time" is
  a frequency. `abilities.WINDOWS` and `Ability.frequency` carry them. The DSL
  currently spells `delayed_next` as the only event of a delayed ability, which
  leaves that node unable to say what is being delayed — something for the schema
  to settle before the interpreter is written.
- A `while_state` duration on a stored continuous effect is not carried. The DSL's
  own note says a gated ability's `while_state` takes its state from the gate, and
  a gated passive is re-derived on every recomputation, so the duration has nothing
  left to express.
- [Legion]'s "a card different than the one with the Legion ability" (812.1.c) is
  compared by NAME. A second copy of the same card is a different card and does
  satisfy it; this reading gets that right when two things were finalized and
  wrong when a unit on the board shares its name with the one just played.
  Getting it exact would need a permanent to remember which Chain Item put it
  there.
- 204.2's additional costs on an ability are a hook: `Cost.extra` and
  `Cost.extra_can` are called wherever a cost is checked and paid, and nothing
  sets them. They are the one thing in the ability framework with no check
  behind it, and they are here rather than absent because the shape a script
  will compile into is the part this slice is for.
- 754's re-triggering of Targeting Effects when 750's new choices name a new
  object goes through `abilities.target`, but nothing in this slice makes new
  choices, so the path has no caller yet.
- 372.1/372.2's tie-breaks (the affected PLAYER chooses, the Turn Player chooses
  for an uncontrolled battlefield) are not reachable: neither a player nor a
  battlefield is the object of a replaceable event in this slice.
- 465.2.c.8 and 465.2.c.9's choice of which exclusionary assignment requirement
  applies to a unit carrying two: a unit with both Tank and Backline is assigned
  as a Tank, and the choice is not offered.
- 465.2.c.10's "a unit that cannot be dealt damage" is not modelled; nothing
  vanilla can make a unit undamageable.
- No card PRINTS a keyword field on a unit — that is reading card text (#27).
  A layer-2 `grant` sets one, every rule that reads them is implemented, and both
  halves are checked against a hand-built board.
- `combat.validate_assignment` does not restate 465.2.c. It asks whether the
  assignment is one `legal_assignments` — the generator's own walk — produces,
  and the clause checks exist only to NAME the rule a refusal broke. A validator
  that restates the rules is a second implementation that drifts, and this one
  had: 7 Might onto a 3-Might and a 2-Might unit has two legal assignments and
  the clauses accepted six. Above `ENUMERATION_BOUND` reachable partials the
  walk gives up and the clauses decide alone, which no board the kernel builds
  comes close to.
- Cost modification is implemented only through a Replacement Effect
  (`cost_replacement`, `ignoring_cost`). 356.2's additional costs exist on an
  ABILITY's `Cost` and not on a card; 356.4.d/356.5's whole-total modifications
  and 356.4.e's per-discount minimum are not modelled.
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

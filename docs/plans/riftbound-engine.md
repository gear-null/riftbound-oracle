# The Riftbound engine — from a table to a Stockfish-style simulator

**Status:** proposal · **Date:** 2026-09-11 · **Tracked in:** epic #19 and the `engine` label on GitHub (issues #21–#50)

This plan turns deck-lab's *table* (code holds the state, an LLM plays every move and
applies every card by hand) into an *engine* (code plays the game, searches lines,
evaluates positions; LLMs are spent only where they add value). It is written to be
executed by several agent sessions over a few days, as decisions, gates and thin
vertical slices. It will not be right the first time, so every phase ends in a
measurement that makes being wrong cheap, and the two decisions most likely to be wrong
(how to search under hidden information, and whether Python is fast enough) each have
an explicit experiment in front of them.

---

## 0. What this is for

**The product is a deck-building tool.** Propose a deck, play it against the current
tournament meta, learn which cards carried it and which failed, change one thing,
repeat. Everything else in this plan exists to make those games cheap and their verdicts
trustworthy.

- **Playing well is the means; the evidence standard is the end.** "Rules enforcement"
  is not a goal. The kernel is not a judge and not a client, and it never chases corner
  cases for their own sake. Its fidelity target is: *the meta's cards correct, unknown
  cards refused, corner cases only when a puzzle or a ruling shows they change results.*
  The correctness instruments (symmetry, perft, golden games) exist to protect deck
  verdicts from engine bugs, not to referee anyone.
- **The opponent set is the current tournament meta**, i.e. the versioned gauntlet. It is
  the scripting frontier, the evaluation set and the pool the tool proposes decks from.
  Decks nobody has built yet are out of scope until the meta pool is done.
- **Pilot quality is part of every verdict.** The engine plays both seats, so a deck
  score is really *deck × pilot*. Board decks are easier to pilot than combo or control
  decks, and a weak pilot rates them unfairly. Every report carries pilot diagnostics,
  and a **meta-respect test** (known tournament lists must beat known casual lists in
  self-play) gates the tool's own credibility.
- **Two learned models, plus one statistic that needs no learning.** A *position*
  evaluator makes search deeper and cheaper; a *deck and matchup* surrogate predicts
  P(A beats B) from composition so thousands of candidate decks can be screened before
  games are spent on the promising ones; and *card-contribution statistics* (drawn vs.
  not drawn, played vs. held win-rate deltas, in the style of 17Lands) are the first
  deck-building signal the engine can give, available the day it plays its first game.
- **The deck loop is the spine and it arrives early**: `matchup` with intervals and card
  statistics right after the first fully automated game with a greedy pilot. Search and
  learned evaluation are strength multipliers layered on afterwards, each one measured
  by whether deck verdicts change and whether the meta-respect test improves.

## 1. Why: the current simulator is expensive and weak for the same reason

deck-lab is a table, not a player (ADR 0007). That split was right for the problem it
solved — *nothing that must not be imagined is imagined* — but it puts the LLM in the
loop for every decision **and every card effect**, which is where both the cost and the
quality problems come from.

**Cost, measured on the current table** (Irelia vs Viktor, seed 7):

| render | bytes | ≈ tokens |
|---|---|---|
| `state --seat 1` at setup | 2,442 | ~700 |
| one `do` (e.g. `beginturn 1`) | 1,668 | ~480 |
| one `note` | 1,654 | ~480 |

A game is roughly 2 seats × 10 turns × 6 actions ≈ **120 renders**. Output alone is
~60k tokens; the real cost is that each call re-reads the game so far, so input grows
quadratically: 120 calls × an average ~60k of context ≈ **5–8M tokens per game** before
any reasoning. A 4-game matchup is ~30M tokens, and SKILL.md correctly says a 4-game
sample has a Wilson interval of 30–95%. We pay millions of tokens for a number we are
told not to trust. (Issue *tokens* replaces this estimate with a measurement.)

**Quality**, from the same design:

- *One mind plays both seats* (ADR 0007's own caveat). Views redact; they cannot make
  the agent forget.
- *Myopic play.* Each decision is one reasoning step with no lookahead, no sampling of
  the opponent's hidden hand, no counterfactual. The research below is unambiguous that
  in card games the strength lives in the search, not in the policy: the same network
  scored 26.8% without search and 51.35% with it (§5.1).
- *Card effects applied by hand* are applied inconsistently; the log makes the error
  visible after the fact, which is not the same as not making it.
- *The chain is not modelled*, so reactions — 115 of 954 cards are `[Reaction]` — are
  narrated, not played. Every lens of the research flagged the chain as the first thing
  to build, because it is where hidden information and most card text actually live.

## 2. What: the target in one paragraph

A deterministic **rules kernel** that implements the Core Rules (turn structure,
priority and the chain, showdowns, combat, scoring, layers, keywords) and *executes card
text* from a verified **card script** per card; a **search** that scans for forced
terminal lines first, then beam-searches a turn's plans and scores each plan by its
average value across sampled opponent worlds after a one-ply reply; an **evaluation**
that starts as the book's deck-relative linear model fitted by regression on self-play
and grows into a small NNUE-style network trained maintainer-side and run in pure
Python; and an **agentic layer** where LLMs do the three things they are good at here:
compile card text into scripts with independent verification, adjudicate flagged hard
nodes as cached rulings, and explain results in the book's Strategic Quality Profile
format. Games cost zero tokens. Tokens are spent on scripting (one-off) and on analysis.

The Stockfish analogy, made exact:

| Stockfish | Riftbound engine |
|---|---|
| move generator + rules | rules kernel + card scripts; legal actions are *generated*, not validated |
| alpha-beta search | terminal scan → beam over turn plans → PIMC over ~32 sampled worlds with a one-ply reply |
| NNUE evaluation | φ(S)·w_D (the book, calibrated) → sparse card-zone features → small MLP |
| fishtest / SPRT | paired, seat-swapped games scored per pair; SPRT; a perfect-symmetry test that must read exactly 50.00% |
| perft / bench | legal-action perft, golden playthroughs, conservation invariants |
| opening book / tablebases | rulings cache (rules-report, riftboundfaq); puzzle suite as a bug detector |
| (none) | LLM compiler for card scripts; LLM adjudicator at flagged nodes; LLM explainer |

## 3. What the book gives us

*The Mathematics of Winning Positions* (Ferreira, 2026) is a strategy monograph, not an
engine design, but it states the player's evaluation as formulas it refuses to
calibrate. An engine can calibrate them. What we take:

| book object | engine object |
|---|---|
| V_D(S) = U_D(S) + γ·max_a E[V_D(S_a)] (Bellman) | search: leaf evaluation + lookahead; γ is a search parameter |
| U_D(S) = w_D·φ(S), deck-relative weights | stage-A evaluator: feature vector φ(S), weights per archetype, fitted by regression on outcomes |
| continuation range R(S\|O); Bayesian updates on passes and declines | determinization: sample hands consistent with public info; later weight them by observed deviations (§4.6: interaction instead of development is strong evidence, silence is weak) |
| Decision Space D*(S) = {a : E[V(S_a)] ≥ θ}; pressure = 1 − \|D*_opp(S_a)\|/\|D*_opp(S)\| | a by-product of search: how many plans sit within θ of the best, for both seats; reported as *pressure* |
| plan damage PD(a) = E[V_opp(S_normal)] − E[V_opp(S_forced(a))] | counterfactual: the opponent's best reply value with vs. without our plan |
| point tempo N(s) = ⌈(8−s)/2⌉ scoring steps | feature: score-clock steps, plus the 7-point final-point rule |
| threat quality min{G_ignore, G_answer} − C; first-in risk | the opponent's realistic replies are enumerated, and value is taken *after* the reply |
| bad win: locally winning, continuation losing | same: never evaluate a plan before the reply |
| **Terminal-State Priority** (§9.17): forced win / forced loss before any future comparison | Layer 0 of search, exact; the Utrecht Azir–Viktor position is the acceptance test |
| SQP: components, verdict, decisive assumption, reversal condition, confidence (§9.3, §9.14) | the *output format* of `explain`: which features carried the verdict, which sampled world flips it, how many games back it |

Two cautions the book gives, which we adopt: components overlap, so **never hand-sum
them into one index** (we fit weights from outcomes); and counterfactuals are
model-dependent, so every explanation names the sampled branch that would reverse it.

## 4. Architecture

```
.claude/skills/deck-lab/
  lib/
    engine/                 ← NEW, pure Python 3.9+, no deps (ADR 0004 still holds)
      kernel/               state, zones, turn, priority+chain, showdowns, combat,
                            scoring, layers, cleanups, keywords
      dsl/                  card-script schema + interpreter (primitives = CR 413-444)
      search/               terminal scan, turn-plan beam, world sampler, reply, budget
      eval/                 features, linear weights, tiny MLP inference (vendored weights)
      decisions.py          the decision-request API
    table.py …              the table stays; `do` becomes one client of the engine
  data/
    cards.json              (as today)
    scripts/*.json          ← NEW card scripts: citations + tests + clause coverage
    eval-weights.json       ← NEW vendored weights
engine-train/               ← NEW, maintainer side (numpy/torch allowed): self-play,
                            tuning, ladder, exploiter, the LLM compiler pipeline
```

**Placement.** The engine lives *inside the skill*, in pure Python, because the skill is
the product (ADR 0004): copying the folder must remain the whole install. Training,
tuning, the ladder and the LLM compiler are maintainer-side and only write vendored data
files, as the TypeScript pipeline writes `cards.json` today.

**Speed policy.** Three of the seven research lenses recommend a native (Rust) core from
day one; the LoCM agent's Rust engine ran 443× faster than the reference Python
environment, and the existing C++ Riftbound engine warns that plain MCTS takes "minutes
per decision". We take that seriously and still start in Python, for three reasons: the
shipped skill must be pure Python; correctness is the first risk and the repo's testing
discipline (mutation batteries, proven checks) is Python; and the search we chose does
not need millions of nodes per decision for *analysis* — it needs them for *self-play
data volume*, which is maintainer-side. So: the Python kernel is always the reference
and the product; at gate G4 (right after the first full engine game) we measure
greedy-policy self-play throughput, try PyPy first (no code changes), and start a Rust
port of the kernel inner loop *for data generation only* if the number is below the
target in §6. The port must pass differential tests against the Python reference and
never becomes what the skill ships.

### 4.1 The decision-request API

```
game = Game.new(deck_a, deck_b, seed)          # deterministic
while True:
    d = game.step()                            # runs the rules until a choice is needed
    if d.terminal: break
    game.answer(policy[d.seat](d))             # human / LLM / random / greedy / search
```

`Decision` carries `seat`, `kind` (mulligan · main-phase action · chain response ·
target · modal · optional "you may" · trigger ordering · damage assignment · cost choice ·
**resolve_manually**), the enumerated legal `options`, and the seat's information set.
Compound choices are **grouped** into consecutive decisions — which card, then which
target, then which assignment — rather than enumerated as a product; that is the proven
way to keep branching sane (§5.2). `game.clone()` is cheap; `game.log` is the same
auditable record the table writes, plus the script version behind each effect.

Two precedents shape this interface. Forge (the most complete open-source MTG engine)
routes every choice through one abstract controller that its human UI, its AI and its
scripted test harness all implement — 110 methods for MTG; Riftbound needs 20–35
variants. And Scripts of Tribute puts **determinization in the engine**: an observable
state with hidden zones collapsed, plus `apply_seed(state, seed)` returning one concrete
full-information world consistent with what the seat has observed. Search never
reimplements hidden-information sampling; Riftbound's shared deck-order RNG makes this
clean. `clone()` is the performance-critical primitive (the fastest Hearthstone engine
advertises clones per second, not rules per second), so the state is a flat structure
built to be copied.

`resolve_manually` is the bridge to today's workflow: a card without an accepted script
is played by the agent through the existing primitives, and the log says so. The engine
is usable at 30% coverage; coverage is a metric, not a prerequisite.

### 4.2 The kernel

| CR sections | module | spec we already have |
|---|---|---|
| 104–118 setup, 105–109 zones, 119–192 objects & control, 193–196 winning | `state`, `setup` | table.py (port its 195 checks) |
| 300–324 turn, states, priority & focus, phases, cleanups | `turn` | table.py |
| 325–348 chains, FEPR, showdowns | `chain` | rules-report **hot-fepr-primer**, **showdowns-primer** (verified) |
| 349–359 playing cards, 398–406 abilities, 201–212 costs | `play`, `costs` | table.py `can_pay/pay` |
| 360–397 passive, activated, triggered, reflexive, delayed, linked; 367 replacement | `abilities` | new |
| 407–444 game actions (32 named) | `actions` — **the DSL primitives** | table.py has ~15 |
| 445–458 movement & recalls | `movement` | table.py |
| 459–466 combat; 701–715 buffs, Mighty, bonus damage | `combat` | rules-report **combat-primer**, table.py |
| 467–472 scoring, 193 victory, final-point rule | `scoring` | table.py |
| 473–480 layers | `layers` | new |
| 716–765 attachment, inactive, dependent keywords, extra turns, counters, choices, untargetability, naming, ignoring | `misc` | new |
| 800–829 keywords (25) | `keywords` — DSL expansions citing their section | new |

The primary test artifact is the **golden game**: a deck pair, a seed, a scripted
answer for every decision request, and an asserted final state — Forge keeps its whole
card-behaviour suite in essentially this form, and the same artifact serves as the
differential test against the table (manabrew's parity harness: run both, diff traces,
report the first mismatch, and *fix the general rule the mismatch exposed, never the
card*) and as the mutation-testing target. Beyond that, borrowed from chess engines
(§5.7): a **legal-action perft** (reachable-state counts to depth d from canonical seeded boards, frozen as
golden numbers), **golden playthroughs** (full serialized games from fixed seeds, diffed
in CI), **conservation invariants** on every transition (card multiset conserved, chance
probabilities sum to 1, points monotone and capped, chain LIFO), and the
**perfect-symmetry test**: same deck, same deterministic policy, mirrored seeds → the
paired result must be *exactly* 50.00%. Any deviation is an asymmetry bug, not noise.

### 4.3 Card scripts: executing card text verifiably

This is what ADR 0007 refused, and its objection stands: *a subtly mis-scripted card
produces a plausible game.* The existing C++ Riftbound engine is the cautionary tale —
its own audit found 325 of 787 cards (41%) with a real gap after its earlier metric
("has a non-empty body") had reported near-complete coverage. The answer is not to avoid
execution but to make scripts **data, cited, tested at clause level, and quarantined
until proven**.

**The vocabulary is small and closed, on purpose.** Forge covers 33,697 MTG cards with
~206 effect primitives, 142 trigger events and 47 replacement kinds (a 165:1
card-to-primitive ratio, median script 8 lines); the LLM-generates-card-code line of
research that targeted XMage's 2,712-symbol per-card API topped out at **5.3% exact
accuracy** (§5.6). So the DSL targets roughly 50–90 primitives, 25–40 trigger events and
under 10 replacement kinds, derived *empirically first*: cluster the 288 gauntlet cards'
text by mechanical verb phrase and count, before freezing anything. Forty to sixty
diverse cards are hand-written before any generation — they are the DSL's acceptance
test, the few-shot corpus, and the retrieval index the compiler selects examples from.

A script is a JSON AST over that vocabulary: **primitives** = the CR's own game
actions (413–444) plus `give_might(n, until)`, `create_token(spec)`, `score`;
**selectors** (friendly/enemy/any · unit/gear/spell · at battlefield/base · cost ≤ · tag ·
another · up to N); **conditions**; **choices** (`choose`, `may`, `unless_pays`);
`for_each`; **triggers** (382–397, and *several per card*), **activated** abilities with
costs, **passives** with layers (and ongoing conditionals like `[Level N]`), **keywords**
by name with parameters. Sixteen randomly sampled gauntlet cards all fit this
vocabulary. The prior engine's gap audit is mined into DSL requirements before the DSL
is frozen: multiple triggers per card; conquer and hold as distinct events; min-clamped
Might modifiers; aura predicates as structured conditions, never text matches.

**Clause-level coverage.** Each card's printed text is split into clauses; every clause
is implemented, or marked `approx`/`unsupported` with a reason. Progress is reported as
"clauses covered of clauses total" and "gauntlet decks engine-ready", never as "cards
with a script".

**The compiler pipeline** (maintainer-side, Opus 5, batch, parallel across sessions):

1. **Compile** — text → script, with a CR citation per primitive; **strict schema
   parse** with a structured error record (path, offending token, expected set) fed
   back for repair. Expect a repair loop: the best current measurement of LLMs writing
   a real DSL is 91% parse and 55% clean first execution (§5.6). Cards with long text
   are the hard axis and are routed to a slow reasoning pass or a human.
2. **Independent test author** — sees the printed text only, never the script; writes
   2–4 scenario tests. It cannot rationalise a script it has not seen.
3. **Back-translate & judge** — script → English; a judge compares to the printed text.
4. **Engine** runs the tests; accepted only if all pass and the judge passes; otherwise
   **quarantined** with reasons.
5. **Replay validation** — the card is played in engine games and the last rounds of
   the log are shown back to a checker asking "does this match the printed text?"; this
   loop took a comparable project from 98% to 100% executability (§5.3).
6. **Mutation** — an accepted script is perturbed and at least one of its tests must go
   red. *A card test that cannot fail is not a test.*

Errata'd text (52 cards) is used instead of printed text; `ambiguous` (37) and
Equipment-band cards go to a manual queue. Riot has committed to bans rather than errata
for balance (§5.5), so a scripted corpus is a durable asset.

**Scope and order.** 288 distinct cards cover all 48 gauntlet/deck lists; script those
first, by deck. Cost is one-off: ~290 × (~2k compile + ~2k tests + ~1.5k judge) ≈
**1.6M tokens** for the meta, ~5M for the whole pool — less than one hand-played matchup
today.

### 4.4 Search

The order is the book's ordering rule, and the shape is the one that beat a champion
(§5.1).

- **Layer 0 — terminal scan (exact).** Within the current turn: any line that reaches
  the winning score, respecting the 7-point rule? Any opponent line next turn that must
  be prevented? Opponent responses are bounded by open runes and the reactions left in
  their known decklist; tapped-out means exact (the Utrecht position).
- **Layer 1 — turn-plan beam.** A plan is a sequence of decisions ending in pass. Beam
  width 24–96 over plans (the LoCM agent was still improving at 96), transposition table
  on state hash, dominance pruning, node budget. Turn-level plans are what won the LoCM
  and Hearthstone competitions (§5.2).
- **Layer 2 — PIMC over worlds.** Sample ~32 opponent worlds consistent with public
  information (open decklists: composition known, order and hand hidden; strength
  saturated at 32 worlds in LoCM). For each candidate plan and each world, let the
  opponent reply with a cheaper Layer-1 search, evaluate *after* the reply, and score the
  plan by its **mean across worlds** with a pessimistic quantile as risk. Choosing one
  plan that is good on average across worlds — rather than the best action per world —
  is what removes intra-turn strategy fusion cheaply.
- **Chain windows.** At each priority window, offer `{pass}` plus the top-k reactions by
  prior; the world sampler decides whether the opponent actually holds them. Sequential
  priority means ordinary minimax applies; a decoupled (simultaneous-move) rule is added
  only if pass-order exploitation shows up in self-play.
- **Belief.** Uniform sampling first; then weights from observed deviations — a strong
  reaction *not* played when it would have mattered lowers those worlds — and an
  archetype posterior from the deck prior. Knowing the exact decklist was worth ~9
  points in LoCM (51.4% → 60.4%), so this is real headroom.
- **Layer 3 — ablations with kill criteria.** ISMCTS, deeper trees, decoupled UCT: run
  only if the measured game properties (§6, issue *measure*) say determinization is in
  its weak regime, and keep only if they earn Elo at equal budget. ISMCTS was *not* a
  free upgrade in the literature (§5.2). CFR-family and public-belief-state methods are
  out of scope by design: their private-state requirement does not fit a 40-card deck.

Outputs: ranked plans, principal variation per plan, decision-space sizes for both seats
(pressure), and the sampled world that would flip the ranking (reversal condition).
Budgets are node counts, so results are reproducible from a seed. Actions use a flat,
fixed-size encoding from the start (play × target, move × battlefield, chain response,
pass) so the search's move list, a later policy net and any agent's action vocabulary
are the same object. Root-parallelism over seeded worlds fits 14 cores with no GPU.

### 4.5 Evaluation

- **Stage A — the book's linear model, calibrated.** φ(S): score and score-clock steps
  for both seats; control, ready/exhausted Might and Tank presence per battlefield; base
  Might and unit count; runes total/ready, domain access, next-turn energy; hand size and
  *texture* (castable next turn, reactions held); deck and trash sizes; champion in play;
  decision-space sizes from search; quiet-turn value delta as inevitability. Weights per
  archetype fitted by logistic regression on self-play outcomes (Texel-style: ~64k games
  gave ~100 Elo in chess, §5.4). Optional bootstrap: LLM-written candidate scoring
  functions selected by self-play on a *training split* of decks and reported on a
  held-out split — evolved heuristics overfit their distribution (§5.3).
- **Calibration** is phase-dependent: fit the eval→win-probability logistic with
  parameters that vary by (points, turn, runes) as Stockfish's WDL model does by
  material, and report a reliability diagram plus the Brier decomposition on a fixed
  held-out set. Expect the ceiling to be about **AUC 0.80** for mid-game win prediction
  in a TCG (§5.4); 0.78 is not broken, 0.65 is.
- **Stage B — a small network.** Sparse (card, zone, controller, ready) indicators plus
  card *properties* (cost, domain, Might, tags, keywords) so unseen cards from a new set
  have a representation (§5.4), plus φ(S), into a ≤10M-parameter MLP; data beats
  parameters. Training maintainer-side on self-play positions labelled with outcome,
  the search's value, and auxiliary targets (final score differential, battlefields
  conquered, turns to win); inference in pure Python with vendored weights, sized to
  Layer 2's leaf budget. **Search stays out of the training loop**: self-play for data
  uses a cheap policy (2 hours vs. an estimated 10.6 years for one Othello agent, §5.4);
  search is spent at analysis time, where it is free.
- **Iterate**: eval v0 → self-play → eval v1 → … Each version must beat the previous on
  the ladder and not regress the puzzle suite.
- **The deck and matchup surrogate.** A second, separate model: from two deck
  compositions (card multiset, legend, champion, battlefields, runes) to P(A beats B),
  trained on the self-play store's game outcomes with learned card embeddings; reported
  with calibration on held-out pairings and on held-out *decks*, because a surrogate
  trained on 48 lists will interpolate well and extrapolate badly. Its job is screening:
  rank thousands of mutations cheaply, then confirm the top few with paired games. Its
  embeddings double as an interpretable "what does this card do for this deck" signal.

### 4.6 The agentic layer — where tokens are spent

The literature is blunt: four standard LLM-agent scaffolds playing card games were
statistically indistinguishable from *random*, while the same model writing evaluation
code was +16 points (§5.3); an LLM inside minimax reached top 10–30% of a human ladder
and lost a third of its games on the clock, while a pure engine with a hand-written
evaluator sat far above it (§5.2). So the LLM is **banned from the per-decision loop**
(ADR 0009), and used here:

| job | who | when | cost |
|---|---|---|---|
| compile + verify card scripts | Opus 5, batch | one-off per card | ~1.6M tokens for the meta |
| propose evaluator features / heuristic code (selected by self-play, held-out reported) | Opus 5 | during stage A | small |
| adjudicate a flagged node (unscripted card, disputed interaction, search disagreement) | Fable via `rules-report` | rare, cached as a ruling *and* a test | ~50k per ruling |
| explain a result in SQP form; propose deck changes | Fable/Opus | per analysis | ~10–30k |
| propose deck mutations worth screening; read the loop's report | Fable/Opus | per exploration round | ~10–30k |
| play a game | nobody | — | 0 |

Escalation is gated on cheap disagreement (top-2 value gap, shallow-vs-deep flip), the
way *Chain-in-Tree* cut LLM tree-search cost by 75–85% by branching only at hard nodes.
The engine also becomes the **sparring partner** through `do`, and the iteration loop in
SKILL.md ("change one thing, same seeds, replay") becomes `matchup --games 500` in
minutes with intervals that mean something.

## 5. Evidence from the research sweep

Seven lenses, ~80 sources, most opened in session. Numbers below are from the sources
marked VERIFIED in the research notes; RECALLED items are omitted or flagged.

### 5.1 The blueprint exists, and it is search on top of a small net
Rubin (Sept 2026, arXiv 2609.06816) beat ByteRL — the reinforcement-learning champion
of the Legends of Code and Magic competition — 51.35% [95% CI 50.37–52.33] over 10,000
pre-registered games with: a Rust engine (443× the Python reference), PIMC over sampled
worlds (saturating at **32**), a beam over turn *plans* (width 24; still improving at
96), **one** opponent reply ply, and a 2.5M-parameter feed-forward policy/value net.
The same net without search: **26.8%**. With the exact opponent decklist known:
**60.4%**. Quadrupling data was worth +8 points at both 2.5M and 10M parameters; model
size barely mattered; deeper trees did not help. It also measured Long et al.'s three
PIMC properties and found LoCM in the regime where determinization works. Caveat: LoCM
has no chain and a much smaller board; Riftbound's per-turn branching will be higher.

### 5.2 Cheap search beat MCTS and RL for years; heuristics are a strong baseline
Depth-3 alpha-beta with hand-written heuristics (Coac) won three LoCM editions at
86–94% (arXiv 2305.11814); the 2021 winner simply simulated its own turn and the
opponent's reply. In the Hearthstone AI Competition 2020 the top three all used
"dynamic lookahead"; MCTS was the most common entry and lost. In Tales of Tribute a
tuned hand-written heuristic (63.9%) was within noise of MCTS (65.7%) and flat Monte
Carlo collapsed (21.6%). ISMCTS was *not* better than plain determinization overall in
Dou Di Zhu (42.3% vs 43.6%), and 40 shallow determinizations lost to one deep tree by
73–83% at equal budget; *move grouping* (choose card → choose target as consecutive
nodes) is how that paper kept branching tractable. Foul Play — a Rust engine with a
hand-crafted evaluator and MCTS, no learning — reached Elo 2341 on the Pokémon Showdown
ladder (top 50), far above the best LLM-in-minimax agent (projected 1300–1500). Long
et al. (AAAI 2010) give the decision rule: measure leaf correlation, bias and
disambiguation; Skat and Hearts (lc 0.8–1.0, df ≈ 0.6) lose only ~0.1/game to
equilibrium under PIMC. **Measure Riftbound's numbers before choosing** (issue *measure*).

### 5.3 LLMs: write code, never pick the play
Cardiverse (EMNLP 2025): CoT, ReAct, Reflexion and Agent-Pro playing 19 card games
scored −0.5 / +0.2 / 0.0 / +2.3 against *random*; the same LLM writing Q-function code,
selected by self-play, scored +16.3, with a replay-validation loop that reached 100%
executability. PTCG-Bench (2026): legal-action masking in the harness was worth 118
Glicko points — more than the gap between adjacent models — and none of five
self-evolution mechanisms improved monotonically. PokéChamp (ICML 2025): the LLM's
opponent-action prediction was 13–16% top-1, and a third of ladder games were lost on
the clock. RAP: LLM-as-world-model fell from 100% to 42% between 2- and 6-step
problems. LATS-style LLM tree search costs ~175k tokens per solved instance. Cicero:
the language model never chose the moves. "Beyond the Hype" (2025): LLM-evolved
heuristics overfit their evolution distribution — evolve on a training split, report
median and IQR on a held-out split.

### 5.4 Learned evaluation on one machine
Stockfish NNUE: one large sparse layer, tiny dense layers, incremental accumulator
updates (a move changes ≤4 of ~40k features); the Riftbound analogue is a
(control bucket, card, zone, owner) indicator set where every primitive action flips
1–3 features. A hobby-scale NNUE (3,240 inputs, 256 hidden, 0.6 MB) beat its
hand-crafted predecessor by ~100 Elo from ~74k games (arXiv 2412.17948). Texel tuning
(logistic regression of a linear eval on outcomes; 8.8M positions from 64k games) was
worth ~100 Elo cumulatively; the author's lesson — do not filter out the positions the
evaluator is actually asked about. Training a value function **without search in the
loop** and adding MCTS only at test time took under 2 hours on a laptop CPU where the
in-loop version was estimated at 10.6 years (arXiv 2204.13307). Jones (2021): 10× train
compute ≈ 15× test compute — buy search at analysis time, which is free for us. MiniZero:
Gumbel selection at 16 simulations reaches ~75% of the Elo of 200. KataGo: playout-cap
randomization and auxiliary targets are the cheap efficiency tricks. AAIA'17 Hearthstone
challenge: the top ten all landed at **AUC 0.796–0.802** for mid-game win prediction —
the representation mattered, the model did not. MTG representation study: property-
encoded cards predicted 55% of human picks on *completely unseen* cards.

### 5.5 The Riftbound ecosystem
- **alpharune** (github.com/chorlick/alpharune): a C++20 1v1 Riftbound engine on the
  OpenSpiel interface — FEPR chain, combat, scoring, 23 keywords, 787 card files, 855
  tests, MCTS/ISMCTS/human agents. **No licence** (all rights reserved), stale since
  2026-05-29, and its own audit reports 41% of cards with a real gap. Treat as literature:
  its gap audits are a free map of which clauses break naive engines. A one-line request
  to the author to add a licence is worth sending.
- **Riot's developer policy** for Riftbound prohibits, as conditions of API-key use,
  "automated rule enforcement", "standalone clients solely for Riftbound", and
  "retaining metagame-defining data" (play rates, win rates, matchup differentials).
  We do not use a Riot key (cards come from Riftcodex under the fan-content policy) and
  publish the engine as research; self-play tables are simulation output, framed as such.
  This is a decision for the owner (ADR 0009).
- **No game logs exist.** Riot's API is card-content only; there is no official client;
  RiftLite (the only match tracker) is closed and result-level. Self-play is the data.
- **riftboundfaq** (MIT code, CC BY-SA content, active 2026-09-09): rulings with CR
  citations — ready-made engine regression tests, share-alike on quoted fixtures.
- **Decklists are the abundant input**: Riftools tracks 152 events; rift-atlas parses
  cleanly (the repo already scrapes it); Piltover Archive and riftdecks block scripts.
- Riot's Feb 2026 State of the Game: bans, not errata, for balance — card text is stable.
- The rules hub moved to `playriftbound.com/en-us/rules-hub/` (the manifest URL 301s).

### 5.6 Rules engines and card scripting
Forge: 33,697 MTG cards as plain-text scripts, median 635 bytes, over ~206 effect
primitives / 142 triggers / 47 replacement kinds; its whole card-behaviour test suite
is a few files of scripted board states. XMage: one Java class per card, ~2.8× the
bytes per card, and new-set cards merged without tests. Card2Code (FLAIRS 2023): LLM
generation against XMage's 2,712-symbol API reached 5.3% exact (9.2% with an oracle
naming the right symbols); accuracy collapsed for text over 102 words. LAMMPS DSL study
(2026): a strict grammar + cheap execution + structured error records took 2026-class
models to 91% parse / 55% first-run — "it parses" is not "it works". Cardiverse: replay
validation by a second model added +1.3/10 consistency and reached 100% executability.
Manabrew: a Rust MTG engine that treats Forge's scripts as the contract and keeps
correctness with a same-seed parity harness against Java Forge. Scripts of Tribute: card
effects as JSON keywords, ~120–400 games/s in C#, determinization exposed by the engine
(`ApplyState(seed)`); the 2023 winner root-parallelised MCTS over 5 seeded trees.
Brimstone: 400k copy-on-write clones/s — clone/undo is the hot path. Fireplace: test
code ≈ 65% of card code by volume. Coverage stalls, not engine bugs, are what ended
SabberStone (~98% of base cards, 2019) and every hobby LoR/Snap simulator.

### 5.7 Measuring strength honestly
Fishtest scores game **pairs** on a five-outcome scale (pentanomial GSPRT), ~20%
shorter tests than per-game scoring; even Stockfish accepts a ~12% regression
pass-through at its cheap first stage. Sample sizes at α=0.05, 80% power: a 5-point
edge needs ~780 decisive games, 3 points ~2,200, 2 points ~4,900, 1 point ~19,600; at
N=1,000 the 95% CI is ±3.1 points, so a thousand games cannot see a 2% change. Paired
seeds helped by only 0.1–0.4% in most tabletop games but substantially in poker
(arXiv 2503.02686) — Riftbound is poker-like (both shuffles replayable), but the paired
vs unpaired variance ratio must be measured, not assumed. AIVAT cut hands-to-
significance by >10× in poker and we own all three ingredients (known chance events,
explicit policies, a value function). Test-position suites do not predict strength and
must never be tuned against; human-move agreement is not strength (Stockfish 41%,
Maia 53%). The perfect-symmetry self-play test is a proof, not a statistic. A strong RL
CCG agent was beaten 90.4% by a cheap best-response on a 32-deck pool and 80% at 256 —
our 48-deck gauntlet is the most exploitable regime, so a standing **exploiter** is a
second headline number, and evaluation is a round-robin (the strongest agents in Tales
of Tribute were rock-paper-scissors).

## 6. Measurement: how we know it is working

- **Pairs are the unit.** Each scenario (decks, both shuffles, rune orders,
  battlefields, coin flip) is played twice with seats swapped; scored per pair; SPRT
  over pairs. Every game record carries its seed. Report score, N, 95% CI in points and
  Elo, and per-matchup breakdown — an aggregate gain that hides a 15-point loss in one
  matchup is usually a bug.
- **Two-stage tests**: a fast-budget filter, then a full-budget confirm; refactors and
  script rewrites use non-regression bounds.
- **Kernel proofs**: perft goldens, golden playthroughs, conservation invariants, and
  the exactly-50.00% symmetry test in CI.
- **Measure the game once** (issue *measure*): leaf correlation, bias, disambiguation;
  branching per turn and per chain window; draw rate; how much the seed determines the
  outcome (paired vs unpaired variance); outcome variance under reshuffles of the same
  position. These numbers choose the search design and the sample sizes.
- **Throughput target** for maintainer-side self-play, from the sample-size arithmetic:
  ≥ ~2,000 greedy-policy games per hour on 14 cores settles a 2-point claim overnight.
  Below that, gate G4 triggers.
- **Puzzle suite as a bug detector**: provable positions only (forced lethal, unbreakable
  hold, mandatory chain response, legality), from the Utrecht case, hand-built cases,
  rules-report rulings and riftboundfaq. Pass/fail in CI; never a tuning target.
- **Calibration**: phase-dependent WDL fit, reliability diagram, Brier decomposition on a
  fixed held-out set.
- **Exploitability**: behaviour-clone the engine, fine-tune an attacker, report its win
  rate next to the gauntlet win rate.
- **Human agreement** (top-k vs reconstructed tournament lines): a dashboard smoke test
  and a position-mining filter, with a written warning that it is not an objective.
- **Token accounting**: tokens per analysis, engine vs hand-played, in the deck report.

## 7. Phases

**Phase 0 — decide (HITL).** ADR 0009: scripts are data, cited, tested at clause level,
quarantined; engine placement and speed policy; the decision-request API; no LLM in the
per-decision loop; licensing and distribution posture.

**Phase 1 — kernel.** Random-policy self-play to completion on vanilla units, with
perft/goldens/invariants/symmetry; combat and scoring with the table's checks ported;
abilities, layers, replacement/delayed/reflexive; the 25 keywords as cited expansions.

**Phase 2 — card scripts.** DSL + interpreter with clause-level coverage and 20
hand-written scripts; compiler pipeline; **first fully automated game between two real
tournament decks** and the G4 throughput measurement; four parallel scaling batches;
script mutation battery.

**Phase 2¾ — the deck loop, v0.** With a greedy pilot: `matchup` against the versioned
gauntlet with paired games and intervals; card-contribution statistics; pilot
diagnostics and the meta-respect test. This is the first moment the tool answers a
deck-building question better than the table did.

**Phase 2½ — measure the game.** PIMC properties, branching, draw rate, seed
determination. Decides the search design.

**Phase 3 — search.** Terminal scan with the Utrecht fixture; turn-plan beam with
`bestline`; PIMC over worlds + the pair-scored ladder (G3); belief weighting.

**Phase 4 — evaluation.** φ(S) + regression + calibration; self-play data pipeline
(no search in the loop); small network; puzzle suite.

**Phase 5 — the deck loop, v1.** Deck exploration (mutate, screen, confirm, with a
held-out gauntlet split); the deck and matchup surrogate; `bestline --explain` in SQP
form; engine as opponent; token accounting. The rulings bridge is a nice-to-have.

**Phase 6 — scale and harden.** PyPy/Rust gate; long-tail scripting; standing
exploiter; wider decklist scrape.

## 8. Gates

- **G1 — kernel fidelity.** Ported table checks, primer-derived tests, perft goldens,
  invariants and the symmetry test green; differential replay of the table's logs agrees
  state-for-state on the shared subset. No scripting on top of a kernel that fails this.
- **G2 — script acceptance.** First-pass acceptance below 70% on a deck means the DSL
  vocabulary or the prompts are wrong; fix them before scaling.
- **G3 — search value.** Plan-beam + PIMC must beat greedy by > 100 Elo at ≤ 2 s per
  decision on one core (paired games, SPRT). Deeper or fancier search only if it earns
  > 50 Elo per doubling of budget.
- **G4 — throughput.** Measured right after the first full engine game. Try PyPy first.
  If greedy self-play is below ~2,000 games/hour on 14 cores, start the Rust inner-loop
  port for data generation, differential-tested, maintainer-side only.
- **G5 — evaluator lift.** Stage B ships only if it beats stage A by > 50 Elo at equal
  budget, does not regress the puzzle suite, and does not lose more than it gains to the
  exploiter.
- **G-pilot — meta respect.** Before any deck verdict is published, the engine's own
  self-play must rank known tournament lists above known casual lists, and the
  going-first advantage must be measured and stable. A tool that cannot reproduce the
  meta's coarse ordering has no standing to propose changes to it.
- **G-search — determinization regime.** If the measured properties put Riftbound in
  PIMC's weak regime (low leaf correlation or mid-range disambiguation), the Layer-3
  ablations are promoted from optional to required before Phase 4.

## 9. Risks, stated plainly

- **Card scripting is the schedule risk** — and the prior engine shows the failure mode
  is silent partial coverage, not crashes. Clause-level metrics, independent test
  authors, replay validation and the manual fallback are the mitigations.
- **The chain is the correctness risk.** Verified primers as spec, mutation battery,
  differential replay, rulings → tests.
- **Python may be too slow for data volume.** Explicit gate, PyPy first, Rust port
  scoped to the inner loop and to maintainer-side use.
- **Self-play from a weak policy labels positions weakly**, and a 48-deck pool is the
  most exploitable regime. Iterate; anchor to fixed opponents; held-out deck split;
  standing exploiter; provable puzzles as ground truth.
- **Determinization is unsound** (strategy fusion, non-locality). It is also what
  produced expert Bridge, Skat and the LoCM result; the properties experiment tells us
  which case we are in, and reaction windows are handled with a local prior.
- **Distribution.** Riot's API terms prohibit exactly this class of tool for key
  holders. We hold no key, ship a research artifact, and frame self-play output as
  simulation. The owner decides the posture in ADR 0009.
- **Deck × pilot confound.** The tool's verdicts are only as good as the engine's
  piloting of *both* decks. Mitigations: pilot diagnostics per archetype, the
  meta-respect gate, exploiter probes, and stating the pilot version on every report.
- **The engine cannot generate a line it does not know.** At sampled positions an LLM
  proposes candidate plans the beam missed; if they win on the ladder they become search
  heuristics. This is the one place LLM *play* still earns tokens, and it is offline.

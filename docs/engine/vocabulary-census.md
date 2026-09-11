# Vocabulary census — what Riftbound card text actually says

**Status:** measurement, for [#26](https://github.com/gear-null/riftbound-oracle/issues/26).
Nothing here is a decision. It is the number the decision needs.

The engine plan ([`docs/plans/riftbound-engine.md`](https://github.com/gear-null/riftbound-oracle/blob/docs/engine-plan/docs/plans/riftbound-engine.md), §4.3)
sets the card-script DSL a size: roughly **50–90 effect primitives, 25–40 trigger
events, under 10 replacement kinds**. Those numbers are Forge's, scaled — Forge covers
33,697 Magic cards with ~206 primitives, 142 triggers and 47 replacement kinds. Borrowed
numbers are a hypothesis. The plan says so, and asks for the vocabulary to be derived
*empirically first*, before anything is frozen. This is that derivation.

Everything below is produced by `engine-train/census.py`, which reads the committed card
corpus and the committed gauntlet and writes nothing:

```
python3 engine-train/census.py --markdown     # this report
python3 engine-train/census.py --audit        # unclassified clauses + residue only
python3 engine-train/census.py --card "Rift Herald"   # one card, as the splitter sees it
python3 -m unittest discover -s engine-train  # 27 tests, all of them past bugs
```

## The answer in one screen

| | measured | plan's target | |
|---|---|---|---|
| effect primitives | **33** cover 95% of gauntlet clauses; **56** cover the whole 954-card pool | 50–90 | at the bottom of the range |
| trigger events | **20** cover 95%; **39** over the whole pool | 25–40 | inside, near the top |
| replacement kinds | **6** in the gauntlet, **9** over the whole pool | <10 | holds |
| selector atoms | **25** cover 95%; 38 over the pool | — | |
| condition atoms | **17** cover 95%; 23 over the pool | — | |
| choice forms | **4** cover 95%; 8 over the pool | — | |
| cost forms | **10** cover 95%; 13 over the pool | — | |
| modifier durations | **5** in the gauntlet, 6 over the pool | — | |
| keywords | **25** — the whole CR glossary, all of it in the gauntlet | — | 5 take a numeric parameter |
| token specs | 10 in the gauntlet, 11 over the pool | — | `create_token(spec)`'s argument |

A card is **3.15 clauses** on average (median 3, longest 8). The longest printed text in
the game is **60 tokens — 59 whitespace words** (Ivern - Nurturer). Nothing is over 100.

Four results are worth more than the totals:

1. **The Card2Code difficulty axis does not exist here.** That study found LLM accuracy
   collapsing for card text over 102 words, and §4.3 routes "cards with long text" to a
   slow reasoning pass. **No Riftbound card is over 100 words** — not one of the 954. The
   longest is 59, the median is 23, and only six cards in the whole pool clear 50.
   Whatever makes a Riftbound card hard to compile, length is not it, and the budget
   earmarked for long-text handling can go elsewhere.

2. **`recall` is a primitive the plan's list does not have.** The plan draws primitives
   from the CR's named game actions at 413–444. Recall lives at **CR 455**, outside that
   block, and CR 456 is explicit that *a Recall is not a Move* and cannot be stopped by
   anything that restricts Movement. Six gauntlet clauses and 13 across the pool use it.
   A DSL that spelled it `move(to=base)` would produce a plausible game and the wrong one
   — which is exactly ADR 0007's objection, arriving through the vocabulary rather than
   through the interpreter.

3. **"More than one trigger" depends on counting keywords as triggers.** Counting only
   `When …` lines gives 6 gauntlet cards with multiple triggers. Counting the six
   Triggered Ability keywords — `[Deathknell]` (CR 808), `[Temporary]` (816), `[Vision]`
   (817), `[Quick-Draw]` (819), `[Weaponmaster]` (821), `[Hunt]` (823) — as what the rules
   say they are gives **15** in the gauntlet and **32** over the pool, one of them with
   three. The plan's requirement that a card support several triggers is real, and it is
   two and a half times as common as the surface text suggests.

4. **Gating is the commonest structural feature after the trigger.** **67 gauntlet
   clauses** (193 over the pool) are gated by a keyword binder — `[Empowered]{>}`,
   `[Level 6]{>}`, `[Legion] —` — across 9 distinct gating keywords. These are the
   "ongoing conditional passives" the prior C++ engine's gap audit flagged, and they are
   not a corner case: they are 5% of all gauntlet clauses.

## How a clause is counted

Card text is normalised, split, and classified in that order.

**Normalised.** Two notations reach the corpus for the same symbols: Riftcodex sends
`:rb_energy_1::rb_rune_chaos:`, Riot's errata articles print `[1][P]` for the identical
cost. Both fold to one brace form using the shorthand the rules define themselves — CR
134.2 for the six domains, CR 135.2.e for the rest, including `[S]`, Might's retired
shorthand, which one card still carries. Errata'd text is used where Riot has issued it
(52 cards). Reminder text is removed and counted separately: CR 135.2.d.3 says its
presence, absence and wording have no effect on game function, so leaving it in would
have every `[Assault 2]` contribute a phantom "+2 Might while attacking" clause and make
the primitive counts a measure of Riot's editorial habits.

**Split.** Into keyword references, activated-ability cost lines, mode headers, and
sentences; then each sentence into its trigger condition, its gating conditions and its
instructions, including the `[do X] to [do Y]` cost-within-an-instruction that CR
355.10.c.1 names.

**Classified.** Each clause gets one *kind* and one or more *buckets*, plus annotations
that cut across kinds — selectors, choices, costs, keywords, a replacement flag, a
duration. Occurrences are counted, not clauses: a clause reading `Play three 1 {M}
Recruit unit tokens into your base` counts for both `play` and `create_token`, because
both are things a script has to be able to say.

**A clause that matches nothing lands in `unclassified` with its text, and §15 prints
them.** That bucket is the instrument. A classifier with a silent fallback reports
whatever coverage its author wants, so `test_census.py` contains a test that puts text
into the bucket on purpose — an instrument that cannot register a reading is not an
instrument.

### The second number

"0 unclassified" is the weak claim. A clause reading `draw 1 and give a unit +2 {M}` is
"classified" the moment `draw` matches, with half its meaning unexamined. So §16 audits
the **residue**: every content word inside a *classified* clause that nothing in any
lexicon accounts for. It stands at **64 of 3,233 content words in gauntlet effect clauses
— 2.0%**, and the words in it are mostly adverbs of degree (`additional`, `original`,
`exactly`). Read the two numbers together or neither of them means anything.

---

# The counts

_Generated. Regenerate with `python3 engine-train/census.py --markdown`._

- corpus: `.claude/skills/deck-lab/data/cards.json` — 954 distinct cards under 1037 lookup names (52 cards carry Riot errata; 37 bare champion names are ambiguous aliases, not ambiguous cards)
- field: `gauntlet-2026-09` (`591cd98a6510`) — 95 lists, 396 distinct cards
- generated by `engine-train/census.py`; re-run to reproduce every number below.

## 1. Scope

| scope    | cards | with text | clauses | clauses/card | median | max | unclassified | share |
|----------|-------|-----------|---------|--------------|--------|-----|--------------|-------|
| gauntlet | 396   | 389       | 1224    | 3.15         | 3      | 8   | 0            | 0.0%  |
| all      | 954   | 940       | 2943    | 3.13         | 3      | 8   | 9            | 0.3%  |

## 2. Clauses by kind

| kind         | gauntlet | all 954 |
|--------------|----------|---------|
| effect       | 621      | 1480    |
| keyword      | 268      | 608     |
| trigger      | 184      | 425     |
| condition    | 80       | 202     |
| cost         | 70       | 214     |
| mode         | 1        | 5       |
| unclassified | 0        | 9       |

## 3. Trigger events

| trigger event    | gauntlet | all 954 | example card                        |
|------------------|----------|---------|-------------------------------------|
| play_self        | 63       | 141     | Akshan - Mischievous                |
| conquer          | 29       | 50      | Adaptatron                          |
| move             | 14       | 35      | Akali, Deadly Weapon                |
| attack           | 12       | 41      | Ahri - Nine-Tailed Fox              |
| hold             | 12       | 38      | Ahri - Alluring                     |
| play_other       | 12       | 33      | Abandoned Hall                      |
| defend           | 9        | 16      | Ahri, Inquisitive                   |
| die              | 8        | 17      | Draven - Audacious                  |
| beginning_phase  | 6        | 8       | Dr. Mundo - Expert                  |
| win_combat       | 6        | 7       | Draven - Audacious                  |
| delayed_next     | 3        | 6       | Sun Disc                            |
| end_of_turn      | 3        | 6       | Annie - Dark Child                  |
| discard_trigger  | 3        | 4       | Flame Chompers                      |
| targeted         | 3        | 4       | Irelia - Blade Dancer               |
| readied          | 2        | 6       | Irelia, Fervent                     |
| stunned          | 2        | 4       | Eclipse Herald                      |
| become_state     | 2        | 3       | Fiora - Grand Duelist               |
| as_played        | 2        | 2       | Nocturne - Horrifying               |
| nth_time         | 2        | 2       | Star Spring                         |
| reveal_trigger   | 2        | 2       | Nocturne - Horrifying               |
| empower_other    | 1        | 4       | Ambessa - Matriarch of War          |
| become_empowered | 1        | 3       | Tail-Cloaked Matriarch              |
| frequency_only   | 1        | 3       | Pyke - Returned                     |
| combat_damage    | 1        | 2       | Imperial Decree                     |
| combat_ends      | 1        | 2       | Mournful Witness                    |
| equip_trigger    | 1        | 2       | Jax - Unrelenting                   |
| hide_trigger     | 1        | 2       | Ember Monk                          |
| score_trigger    | 1        | 2       | Illaoi, Prophet of the Great Kraken |
| showdown_begins  | 1        | 2       | Diana - Lunari                      |
| buffed           | 0        | 4       | Fae Dragon                          |
| banish_trigger   | 0        | 2       | Master of Shadows                   |
| kill_trigger     | 0        | 2       | Immortal Phoenix                    |
| leaves           | 0        | 2       | Ripper's Bay                        |
| recycle_trigger  | 0        | 2       | Karma - Channeler                   |
| burn_trigger     | 0        | 1       | Forgotten Relic                     |
| draw_trigger     | 0        | 1       | Frigid Jewel                        |
| phase_other      | 0        | 1       | Bottled Constellation               |
| start_of_turn    | 0        | 1       | Bottled Constellation               |
| use_ability      | 0        | 1       | Prize of Progress                   |

## 4. Effect primitives

| primitive      | CR      | gauntlet | all 954 | example card                |
|----------------|---------|----------|---------|-----------------------------|
| give_might     | —       | 89       | 189     | Abandoned Hall              |
| play           | 419     | 84       | 186     | Akshan - Mischievous        |
| draw           | 413     | 65       | 134     | Back Off                    |
| create_token   | —       | 41       | 85      | Arise!                      |
| ready          | 415     | 38       | 98      | Ambessa - Matriarch of War  |
| choose         | 355     | 36       | 93      | Alpha Strike                |
| grant_keyword  | —       | 33       | 104     | Azir - Emperor of the Sands |
| deal           | 417     | 32       | 105     | Akali, Deadly Weapon        |
| modify_cost    | —       | 29       | 75      | Ahri - Nine-Tailed Fox      |
| move           | 420     | 29       | 63      | Akali - Rogue Assassin      |
| kill           | 428     | 29       | 62      | Acceptable Losses           |
| restriction    | —       | 21       | 50      | Akali, Silent               |
| buff           | 426     | 20       | 50      | Adaptatron                  |
| recycle        | 416     | 19       | 33      | Baited Hook                 |
| return_to      | —       | 17       | 35      | Abandon                     |
| pay            | 444     | 14       | 28      | Akshan - Mischievous        |
| channel        | 430     | 14       | 26      | Black Rose Dignitary        |
| ignore         | —       | 13       | 30      | Baited Hook                 |
| reveal         | 424     | 13       | 28      | Dazzling Aurora             |
| discard        | 422     | 12       | 30      | Chemtech Enforcer           |
| add            | 429     | 11       | 30      | Baron Nashor                |
| stun           | 423     | 11       | 24      | Back Off                    |
| banish         | 427     | 10       | 28      | Baited Hook                 |
| exhaust        | 414     | 9        | 16      | Altar of Blood              |
| gain_xp        | —       | 8        | 18      | Alpha Strike                |
| look_at        | —       | 8        | 15      | Baited Hook                 |
| score          | —       | 8        | 15      | Ahri - Alluring             |
| enter          | 355.2   | 7        | 32      | Baron Nashor                |
| permission     | —       | 7        | 13      | Arachnoid Horror            |
| counter        | 425     | 7        | 11      | Abandon                     |
| recall         | 455     | 6        | 13      | Altar of Blood              |
| put            | —       | 6        | 10      | Lightning Rush              |
| heal           | 418     | 6        | 9       | Altar of Blood              |
| spend          | —       | 5        | 17      | Call to Glory               |
| empower        | 441     | 4        | 16      | Ambessa - Matriarch of War  |
| attach         | 434     | 4        | 14      | Akshan - Mischievous        |
| use            | 377     | 3        | 9       | Azir - Ascendant            |
| hide           | 421     | 3        | 8       | Bandle Tree                 |
| predict        | 436     | 3        | 8       | Abandon                     |
| disempower     | 442     | 3        | 7       | Lacerate                    |
| burn           | 440     | 2        | 7       | Kennen, Storm of Shuriken   |
| become_copy    | —       | 2        | 6       | LeBlanc - Deceiver          |
| set_stat       | —       | 2        | 6       | Dr. Mundo - Expert          |
| modify_trigger | 383     | 2        | 4       | Karthus - Eternal           |
| gain_control   | —       | 1        | 7       | Akshan - Mischievous        |
| detach         | 435     | 1        | 5       | Veiled Temple               |
| win_game       | —       | 1        | 3       | Aspirant's Climb            |
| swap           | 433     | 1        | 1       | Switcheroo                  |
| take_turn      | —       | 1        | 1       | Time Warp                   |
| double         | 432     | 0        | 6       | Dominus                     |
| modify_tag     | —       | 0        | 5       | Daisy!                      |
| prevent        | 437     | 0        | 4       | Counter Strike              |
| name           | —       | 0        | 2       | Fallen Feline               |
| activate       | 383.4.g | 0        | 1       | Reckoner's Arena            |
| replace        | 438     | 0        | 1       | Ivern - Green Father        |
| skip           | 443     | 0        | 1       | Endless Riches              |

## 5. Selector atoms

| selector atom    | gauntlet | all 954 |  |
|------------------|----------|---------|--|
| self             | 330      | 859     |  |
| type:unit        | 259      | 627     |  |
| side:friendly    | 176      | 405     |  |
| by_state         | 147      | 309     |  |
| at:here          | 66       | 136     |  |
| side:enemy       | 65       | 184     |  |
| type:battlefield | 61       | 178     |  |
| type:token       | 43       | 91      |  |
| all              | 42       | 131     |  |
| type:gear        | 42       | 108     |  |
| type:card        | 42       | 92      |  |
| type:spell       | 32       | 84      |  |
| zone:hand        | 32       | 65      |  |
| another          | 29       | 84      |  |
| at:base          | 27       | 55      |  |
| type:rune        | 25       | 55      |  |
| zone:trash       | 24       | 49      |  |
| count:two_plus   | 24       | 41      |  |
| by_tag           | 22       | 72      |  |
| at:battlefield   | 20       | 91      |  |
| owner            | 20       | 43      |  |
| up_to_n          | 18       | 28      |  |
| zone:deck        | 16       | 33      |  |
| by_cost          | 15       | 48      |  |
| side:any         | 15       | 42      |  |
| type:ability     | 13       | 36      |  |
| zone:top_of_deck | 12       | 19      |  |
| at:location      | 10       | 17      |  |
| by_keyword       | 9        | 25      |  |
| by_might         | 7        | 24      |  |
| negated          | 6        | 9       |  |
| at:showdown      | 4        | 7       |  |
| any_number       | 3        | 13      |  |
| zone:board       | 3        | 4       |  |
| type:legend      | 2        | 6       |  |
| type:champion    | 2        | 2       |  |
| zone:champion    | 2        | 2       |  |
| zone:banishment  | 0        | 3       |  |

## 5b. Modifier durations

How long a modifier lasts is the other half of `give_might(n, until)`. One duration per clause, the most specific that matched.

| duration    | gauntlet | all 954 |
|-------------|----------|---------|
| this_turn   | 77       | 194     |
| permanent   | 19       | 50      |
| while_state | 14       | 40      |
| until_event | 3        | 3       |
| this_combat | 1        | 2       |
| next_turn   | 0        | 2       |

- `for each N` (a count-scaled modifier): **15** gauntlet clauses, 39 across all 954
- clauses gated by a keyword (`[Empowered]{>}`, `[Level 6]{>}`, `[Legion] —`): **67** gauntlet, 193 across all 954, over 9 distinct gating keywords

## 6. Condition atoms

| condition atom       | gauntlet | all 954 | example card                |
|----------------------|----------|---------|-----------------------------|
| controls             | 11       | 37      | Dropboarder                 |
| state_of_object      | 9        | 13      | Azir - Ascendant            |
| state_of_self        | 7        | 23      | Akali - Rogue Assassin      |
| if_you_do            | 7        | 20      | Adaptatron                  |
| paid_additional_cost | 7        | 15      | Akshan - Mischievous        |
| alone                | 7        | 9       | Arachnoid Horror            |
| would_event          | 5        | 12      | Altar of Blood              |
| is_type              | 4        | 10      | Akshan - Mischievous        |
| cant                 | 3        | 5       | Catalyst of Aeons           |
| score_threshold      | 3        | 5       | Find Your Center            |
| unless_pays          | 3        | 5       | Akali, Silent               |
| already              | 3        | 3       | Baron Nashor                |
| has_played           | 2        | 4       | Azir - Emperor of the Sands |
| comparison           | 2        | 3       | Lacerate                    |
| whose_turn           | 1        | 10      | Akali - Rogue Assassin      |
| count_threshold      | 1        | 7       | Kinkou Initiate             |
| spent                | 1        | 7       | Safety Inspector            |
| phase_check          | 1        | 4       | LeBlanc - Fragmented        |
| empty                | 1        | 1       | Hallowed Tomb               |
| has_keyword          | 1        | 1       | Smoke and Mirrors           |
| played_from          | 1        | 1       | Back Off                    |
| condition:other      | 0        | 6       | Ivern - Friend to All       |
| this_killed_it       | 0        | 1       | Disintegrate                |

## 7. Choice forms

| choice form    | gauntlet | all 954 |  |
|----------------|----------|---------|--|
| may            | 82       | 181     |  |
| choose_object  | 41       | 107     |  |
| up_to          | 18       | 28      |  |
| opponent_picks | 4        | 6       |  |
| any_number     | 3        | 13      |  |
| choose_mode    | 1        | 10      |  |
| unless_pays    | 1        | 2       |  |
| order          | 1        | 1       |  |

## 8. Cost forms

Counted wherever they appear, not only on an activated ability's cost line: `You may pay {1} as an additional cost to play me` is a cost inside an effect clause. Activated-ability cost lines specifically: 70 gauntlet clauses, 214 across all 954.

| cost form       | gauntlet | all 954 |  |
|-----------------|----------|---------|--|
| energy          | 77       | 210     |  |
| power_domain    | 42       | 102     |  |
| exhaust_self    | 26       | 92      |  |
| power_any       | 23       | 63      |  |
| additional_cost | 23       | 47      |  |
| recycle_cost    | 19       | 38      |  |
| discard_cost    | 14       | 34      |  |
| banish_cost     | 11       | 30      |  |
| sacrifice       | 10       | 16      |  |
| free            | 8        | 16      |  |
| spend_xp        | 5        | 13      |  |
| power_own       | 5        | 7       |  |
| spend_buff      | 2        | 5       |  |

## 9. Keyword references

| keyword[:param] | CR  | kind (per CR)                           | gauntlet | all 954 |
|-----------------|-----|-----------------------------------------|----------|---------|
| Action          | 806 | permissive                              | 44       | 94      |
| Reaction        | 813 | permissive                              | 39       | 90      |
| Hidden          | 811 | action prerequisite                     | 32       | 44      |
| Empowered       | 828 | dependent                               | 23       | 51      |
| Equip           | 818 | activated                               | 19       | 40      |
| Deathknell      | 808 | triggered                               | 18       | 25      |
| Empower         | 827 | activated                               | 17       | 41      |
| Deflect         | 809 | passive                                 | 13       | 42      |
| Temporary       | 816 | triggered                               | 13       | 26      |
| Accelerate      | 805 | optional additional cost (unit ability) | 12       | 29      |
| Flow            | 829 | passive                                 | 12       | 17      |
| Ganking         | 810 | passive                                 | 10       | 37      |
| Ambush          | 822 | passive                                 | 8        | 19      |
| Tank            | 815 | passive                                 | 8        | 27      |
| Assault:2       | 807 | passive                                 | 7        | 19      |
| Legion          | 812 | dependent                               | 6        | 10      |
| Repeat          | 820 | optional additional cost                | 6        | 24      |
| Weaponmaster    | 821 | triggered                               | 6        | 12      |
| Shield          | 814 | passive                                 | 5        | 16      |
| Assault         | 807 | passive                                 | 4        | 16      |
| Deflect:2       | 809 | passive                                 | 3        | 6       |
| Quick-Draw      | 819 | triggered + permissive                  | 3        | 5       |
| Vision          | 817 | triggered                               | 3        | 10      |
| Assault:3       | 807 | passive                                 | 2        | 4       |
| Backline        | 826 | passive                                 | 2        | 4       |
| Hunt            | 823 | triggered                               | 2        | 8       |
| Hunt:2          | 823 | triggered                               | 2        | 5       |
| Shield:3        | 814 | passive                                 | 2        | 5       |
| Assault:4       | 807 | passive                                 | 1        | 2       |
| Deflect:3       | 809 | passive                                 | 1        | 1       |
| Level:3         | 824 | dependent                               | 1        | 6       |
| Level:6         | 824 | dependent                               | 1        | 9       |
| Shield:2        | 814 | passive                                 | 1        | 6       |
| Unique          | 825 | deck constraint                         | 1        | 3       |
| Hunt:3          | 823 | triggered                               | 0        | 1       |
| Level:11        | 824 | dependent                               | 0        | 4       |
| Level:16        | 824 | dependent                               | 0        | 1       |
| Shield:5        | 814 | passive                                 | 0        | 1       |

- distinct CR keywords referenced: **25 of the 25** in CR 805-829 (gauntlet), 25 (all 954)

Bracketed in the corpus but NOT a CR keyword — game actions set in the symbol font, plus one state the rules never define:

| token     | gauntlet | all 954 |
|-----------|----------|---------|
| Add       | 10       | 29      |
| Stun      | 5        | 14      |
| Mighty    | 6        | 10      |
| Buff      | 2        | 8       |
| Predict   | 3        | 4       |
| Burn:1    | 1        | 3       |
| Burn:3    | 1        | 3       |
| Predict:2 | 0        | 3       |
| Burn:2    | 1        | 1       |
| Burn:7    | 0        | 1       |
| Predict:5 | 0        | 1       |

## 9b. Token specs

`create_token(spec)` is one primitive; these are the specs it has to name.

| token spec   | gauntlet | all 954 |
|--------------|----------|---------|
| Gold         | 10       | 25      |
| Recruit      | 9        | 15      |
| Sprite       | 4        | 8       |
| Bird         | 1        | 6       |
| Mech         | 1        | 6       |
| Sand Soldier | 5        | 6       |
| Reflection   | 2        | 3       |
| Shadow Clone | 2        | 3       |
| Baron Pit    | 1        | 1       |
| Brush        | 0        | 1       |
| Tentacle     | 1        | 1       |

## 10. Replacement effects

| replacement kind | gauntlet clauses | all 954 clauses |
|------------------|------------------|-----------------|
| cost_replacement | 19               | 44              |
| enters_modified  | 17               | 57              |
| instead          | 15               | 34              |
| ignoring_cost    | 8                | 17              |
| would            | 7                | 19              |
| as_enters        | 3                | 9               |
| prevent_damage   | 0                | 2               |
| replace_token    | 0                | 1               |
| skip_event       | 0                | 1               |

- gauntlet cards with at least one replacement clause: **59 of 389** (15%)
- all 954: **159 of 940**

## 11. Triggers per card

- gauntlet: 0=190, 1=184, 2=14, 3=1, 4+=0 (cards with >1 trigger: **15**)
- all: 0=483, 1=425, 2=31, 3=1, 4+=0 (cards with >1 trigger: **32**)

## 12. Clauses per card

- gauntlet: 0=0, 1=32, 2=116, 3=113, 4=64, 5-6=52, 7-9=12, 10-14=0, 15+=0
- all: 0=0, 1=90, 2=267, 3=264, 4=174, 5-6=118, 7-9=27, 10-14=0, 15+=0

## 13. Text length

- gauntlet: printed median 23, mean 23.5, max 59; **over 100 words: 0** (0.0%)
  rules text only (reminder text removed): median 14, max 46, over 100 words: 0
- all: printed median 22, mean 23.4, max 60; **over 100 words: 0** (0.0%)
  rules text only (reminder text removed): median 14, max 48, over 100 words: 0

## 14. The vocabulary that covers 95% of gauntlet clauses

- **trigger events**: 20 of 29 distinct atoms reach 95% of 204 occurrences — `play_self`(63), `conquer`(29), `move`(14), `attack`(12), `hold`(12), `play_other`(12), `defend`(9), `die`(8), `beginning_phase`(6), `win_combat`(6), `delayed_next`(3), `discard_trigger`(3), `end_of_turn`(3), `targeted`(3), `as_played`(2), `become_state`(2), `nth_time`(2), `readied`(2), `reveal_trigger`(2), `stunned`(2)
- **effect primitives**: 33 of 49 distinct atoms reach 95% of 790 occurrences — `give_might`(89), `play`(84), `draw`(65), `create_token`(41), `ready`(38), `choose`(36), `grant_keyword`(33), `deal`(32), `kill`(29), `modify_cost`(29), `move`(29), `restriction`(21), `buff`(20), `recycle`(19), `return_to`(17), `channel`(14), `pay`(14), `ignore`(13), `reveal`(13), `discard`(12), `add`(11), `stun`(11), `banish`(10), `exhaust`(9), `gain_xp`(8), `look_at`(8), `score`(8), `counter`(7), `enter`(7), `permission`(7), `heal`(6), `put`(6), `recall`(6)
- **selector atoms**: 25 of 37 distinct atoms reach 95% of 1665 occurrences — `self`(330), `type:unit`(259), `side:friendly`(176), `by_state`(147), `at:here`(66), `side:enemy`(65), `type:battlefield`(61), `type:token`(43), `all`(42), `type:card`(42), `type:gear`(42), `type:spell`(32), `zone:hand`(32), `another`(29), `at:base`(27), `type:rune`(25), `count:two_plus`(24), `zone:trash`(24), `by_tag`(22), `at:battlefield`(20), `owner`(20), `up_to_n`(18), `zone:deck`(16), `by_cost`(15), `side:any`(15)
- **condition atoms**: 17 of 21 distinct atoms reach 95% of 80 occurrences — `controls`(11), `state_of_object`(9), `alone`(7), `if_you_do`(7), `paid_additional_cost`(7), `state_of_self`(7), `would_event`(5), `is_type`(4), `already`(3), `cant`(3), `score_threshold`(3), `unless_pays`(3), `comparison`(2), `has_played`(2), `count_threshold`(1), `empty`(1), `has_keyword`(1)
- **choice forms**: 4 of 8 distinct atoms reach 95% of 151 occurrences — `may`(82), `choose_object`(41), `up_to`(18), `opponent_picks`(4)
- **cost forms**: 10 of 13 distinct atoms reach 95% of 265 occurrences — `energy`(77), `power_domain`(42), `exhaust_self`(26), `additional_cost`(23), `power_any`(23), `recycle_cost`(19), `discard_cost`(14), `banish_cost`(11), `sacrifice`(10), `free`(8)
- **replacement kinds**: 6 distinct — `cost_replacement`(19), `enters_modified`(17), `instead`(15), `ignoring_cost`(8), `would`(7), `as_enters`(3)
- **modifier durations**: 5 distinct — `this_turn`(77), `permanent`(19), `while_state`(14), `until_event`(3), `this_combat`(1)
- **keywords**: all **25** of CR 805-829 appear; 5 of them take a numeric parameter
- **token specs**: 10 distinct in the gauntlet, 11 across all 954

Totals, counting every atom the whole 954-card pool uses rather than only the 95% cut: **56** effect primitives, **39** trigger events, **38** selector atoms, **23** condition atoms, **8** choice forms, **13** cost forms, **9** replacement kinds, **6** durations.

## 15. Unclassified

- gauntlet: **0 clauses** (0.0% of 1224) across 0 cards
- all: **9 clauses** (0.3% of 2943) across 9 cards

Every unclassified gauntlet clause, in full:

_(none — every gauntlet clause matched something. That is a claim the residue audit in §16 exists to check, not one to take on its own.)_

Every unclassified clause across all 954 cards:

- `Elder Dragon` — Any amount of your damage is enough
- `Experimental Hexplate` — I am a Mech
- `Heimerdinger - Inventor` — I have all {E} abilities of all friendly legends, units, and gear
- `King's Edict` — Starting with the next player
- `Mystic Reversal` — You may make new choices for it
- `Promising Future` — Starting with the next player
- `Skyfall of Areion` — My hold effects are also conquer effects, and vice versa
- `Stalking Wolf` — You may [Ambush] me to its battlefield
- `Whirlwind` — Starting with the next player

## 16. Residue audit

Content words inside CLASSIFIED effect clauses that no matched primitive accounts for. A verb high in this list is a primitive the table is missing; a noun is usually a selector already counted in §5.

| residue word | gauntlet occurrences |
|--------------|----------------------|
| additional   | 7                    |
| chosen       | 5                    |
| cost         | 4                    |
| top          | 3                    |
| original     | 2                    |
| might        | 2                    |
| energy       | 2                    |
| reducing     | 2                    |
| end          | 2                    |
| putting      | 1                    |
| leave        | 1                    |
| split        | 1                    |
| increase     | 1                    |
| needed       | 1                    |
| once         | 1                    |
| sand         | 1                    |
| soldiers     | 1                    |
| optional     | 1                    |
| mechs        | 1                    |
| third        | 1                    |
| total        | 1                    |
| guardian     | 1                    |
| angel        | 1                    |
| exactly      | 1                    |
| following    | 1                    |
| based        | 1                    |
| type         | 1                    |
| tentacle     | 1                    |
| conquer      | 1                    |
| hold         | 1                    |
| countered    | 1                    |
| anywhere     | 1                    |
| you're       | 1                    |
| allies       | 1                    |
| control      | 1                    |
| repeat       | 1                    |
| effect       | 1                    |
| own          | 1                    |
| back         | 1                    |
| combat       | 1                    |

- residue is 64 of 3233 content words in gauntlet effect clauses (2.0%)

---

# The recommended DSL vocabulary

Every atom below earns its place with a count. The rule used to draw the line: take every
atom that appears in the **gauntlet** (the cards an engine must know to play the current
meta), then add every atom that appears anywhere in the 954-card pool, because the pool
is the eventual target and the marginal cost of an atom nobody uses this season is one
table row.

## Effect primitives — 56

**The CR's own 32 game actions (413–444)** — 30 of which a card's text actually
names. A script's `citations`
field can point at the rule that defines each one, which is the point of using the rules'
names rather than inventing labels:

`draw` (413) · `exhaust` (414) · `ready` (415) · `recycle` (416) · `deal` (417) · `heal`
(418) · `play` (419) · `move` (420) · `hide` (421) · `discard` (422) · `stun` (423) ·
`reveal` (424) · `counter` (425) · `buff` (426) · `banish` (427) · `kill` (428) · `add`
(429) · `channel` (430) · `burn_out` (431) · `double` (432) · `swap` (433) · `attach`
(434) · `detach` (435) · `predict` (436) · `prevent` (437) · `replace` (438) · `create`
(439) · `burn` (440) · `empower` (441) · `disempower` (442) · `skip` (443) · `pay` (444)

Two of the 32 never appear in card text at all: **`burn_out` (431)** and **`create`
(439)**. Both are real and both happen constantly — a deck runs out and its owner
burns out; tokens come into existence — but they are performed by the game's
procedures rather than written on a card, and a token is printed as “play a Gold gear
token”, not “create” one. They belong in the engine's action set and not in the DSL's
surface vocabulary, which is a distinction a primitive list drawn from the chapter
heading would not make.

**Named by the rules, outside the 413–444 block.** The plan's list misses these because
it drew the boundary at the chapter, not at the vocabulary:

| primitive | CR | gauntlet | why it is not one of the above |
|---|---|---|---|
| `recall` | 455 | 6 | CR 456: a Recall is **not** a Move and cannot be blocked by movement restrictions |
| `choose` | 355 | 36 | targeting is its own procedure with its own legality rules (CR 355.9–355.13) |
| `enter` | 355.2 | 7 | where a unit enters is chosen as it is played, before it is on the board |
| `use` | 377 | 3 | activating an ability, as distinct from playing a card |
| `activate` | 383.4.g | 0 (1 in pool) | "activate the conquer effects of units here" — re-firing a named trigger |
| `modify_trigger` | 383 | 2 | "your `[Deathknell]` effects trigger an additional time" |

**Not named by the rules at all — the ones a DSL has to invent.** The plan anticipated
three of these (`give_might`, `create_token`, `score`); the data adds the rest:

| primitive | gauntlet | all 954 | shape |
|---|---|---|---|
| `give_might(n, until)` | 89 | 189 | the single commonest thing a card does |
| `create_token(spec)` | 41 | 85 | 11 distinct specs (§9b) |
| `grant_keyword(kw, until)` | 33 | 104 | |
| `modify_cost(delta, min)` | 29 | 75 | min-clamped — `to a minimum of {1}` |
| `restriction(pred)` | 21 | 41 | `can't`, `must`, `only` |
| `return_to(zone)` | 17 | 35 | |
| `ignore(what)` | 13 | 30 | `ignoring its cost` is distinct from paying 0 |
| `look_at(n)` | 8 | 15 | |
| `gain_xp(n)` | 8 | 18 | |
| `score(n)` | 8 | 15 | |
| `permission(pred)` | 7 | 13 | `can be played to an occupied battlefield` |
| `put(zone, position)` | 6 | 9 | top/bottom of deck |
| `spend(resource)` | 5 | 17 | XP and buffs, which are not Energy or Power |
| `become_copy` | 2 | 6 | |
| `set_stat(stat, value)` | 2 | 6 | `its base Might becomes 5` |
| `gain_control` | 1 | 7 | |
| `take_turn` | 1 | 1 | |
| `win_game` | 1 | 3 | |
| `name(what)` | 0 | 2 | naming a card or a tag — a choice over unseen information |
| `modify_tag` | 0 | 5 | |

**33 of these cover 95% of gauntlet clauses.** The other 23 are the tail, and the tail is
where an engine that reports "cards with a script" instead of "clauses covered" goes
wrong.

## Trigger events — 39, of which 20 cover 95%

The six the plan already knew about, in order of how much of the gauntlet they buy:
`play_self` (63) · `conquer` (29) · `move` (14) · `attack` (12) · `hold` (12) ·
`play_other` (12) · `defend` (9) · `die` (8).

Then, each earning its own row: `beginning_phase` (6) · `win_combat` (6) ·
`delayed_next` (3) · `discard_trigger` (3) · `end_of_turn` (3) · `targeted` (3) ·
`as_played` (2) · `become_state` (2) · `nth_time` (2) · `readied` (2) · `reveal_trigger`
(2) · `stunned` (2), and below the 95% line `become_empowered`, `combat_damage`,
`combat_ends`, `empower_other`, `equip_trigger`, `frequency_only`, `score_trigger`,
`showdown_begins`, plus `banish_trigger`, `buffed`, `burn_trigger`, `draw_trigger`,
`hide_trigger`, `kill_trigger`, `leaves`, `phase_other`, `recycle_trigger`,
`start_of_turn`, `use_ability`.

That is 39 names, matching §3's table. An earlier version of this paragraph listed
44, adding `channel_trigger`, `enters`, `gain_control`, `lose_combat` and
`pay_trigger` — rows that exist in the lexicon and match nothing in either the
gauntlet or the pool. §3 counts occurrences and so never printed them; this list
was written by hand from the lexicon rather than from the table, which is how the
two disagreed. The table is the measurement.

Two of these are not events but **modifiers on an event**, and the DSL should model them
that way rather than as 40 more events: `nth_time` (CR 383.1.b — "the first time … each
turn") and `frequency_only` (CR 383.3.e — "once each turn", "N times each turn").

**Multi-event triggers are real and the splitter must not lose them.** `When this is
played, discarded, or killed` is one trigger over three events; taking the first comma as
the trigger's end silently drops two of them. **18 of the 184 gauntlet trigger clauses
match more than one atom** — `When I attack or defend`, `When you conquer or hold`, `When
you play me or when I score`, `Once each turn, when an enemy unit dies while I'm at a
battlefield`. A trigger is therefore a *set* of events plus an optional frequency
modifier, not a single event.

## Selector atoms — 38, of which 25 cover 95%

Four independent axes, which is what makes the count small — the alternative is one
selector per printed phrase:

- **side** — `friendly` (176) · `enemy` (65) · `any` (15)
- **type** — `unit` (259) · `battlefield` (61) · `token` (43) · `card` (42) · `gear` (42)
  · `spell` (32) · `rune` (25) · `ability` (13) · `legend` · `champion`
- **place** — `here` (66) · `at:base` (27) · `at:battlefield` (20) · `at:location` (10) ·
  `at:showdown`
- **zone** — `hand` (32) · `trash` (24) · `deck` (16) · `top_of_deck` (12) · `board` ·
  `banishment` · `champion_zone`
- **predicate** — `by_state` (147) · `by_tag` (22) · `by_cost` (15) · `by_keyword` (9) ·
  `by_might` (7) · `negated` (`non-token`, `non-unit`) · `owner`
- **quantity** — `all` (42) · `another` (29) · `count:two_plus` (24) · `up_to_n` (18) ·
  `any_number`
- **`self`** (330), which is not an axis but the implicit subject of most card text

`by_tag`'s vocabulary is read out of the card data rather than typed into the script, so
a new set's regions do not become "vocabulary the census cannot name".

## Condition atoms — 23, of which 17 cover 95%

`controls` (11) · `state_of_object` (9) · `alone` (7) · `if_you_do` (7) ·
`paid_additional_cost` (7) · `state_of_self` (7) · `would_event` (5) · `is_type` (4) ·
`already` (3) · `cant` (3) · `score_threshold` (3) · `unless_pays` (3) · `comparison` (2)
· `has_played` (2) · `count_threshold` (1) · `empty` (1) · `has_keyword` (1) ·
`phase_check` · `played_from` · `spent` · `this_killed_it` · `whose_turn` ·
`zone_of_object`.

`alone` at 7 is the surprise — "if an enemy unit is alone there", "when a friendly unit
defends alone", "if I died alone" is a board predicate that no general condition language
falls out of, and it is more common in the gauntlet than `count_threshold`.

## Choice forms — 8, of which 4 cover 95%

`may` (82) · `choose_object` (41) · `up_to` (18) · `opponent_picks` (4) · `any_number` (3)
· `choose_mode` (1) · `unless_pays` (1) · `order` (1).

`choose_mode` — the bulleted `Choose one —` — appears **once in the gauntlet** and five
times across the whole pool. It is the construct most likely to be over-built relative to its use.
`opponent_picks` (the defender must kill one of their units; an opponent reveals their
hand) matters more: it is a decision request routed to the *other* seat, which is an
engine-architecture question, not a syntax one.

## Cost forms — 13, of which 10 cover 95%

`energy` (77) · `power_domain` (42) · `exhaust_self` (26) · `additional_cost` (23) ·
`power_any` (23) · `recycle_cost` (19) · `discard_cost` (14) · `banish_cost` (11) ·
`sacrifice` (10) · `free` (8) · `spend_xp` (5) · `power_own` (5) · `spend_buff` (2).

Seven of the thirteen are **a game action used as a cost** — exhaust, recycle, discard,
banish, kill, spend XP, spend a buff. The DSL should not have a second vocabulary for
those: CR 355.10.c.1's
`[do X] to [do Y]` says a cost *is* an instruction, in a cost position.

## Replacement kinds — 9, of which 6 in the gauntlet

`cost_replacement` (19) · `enters_modified` (17) · `instead` (15) · `ignoring_cost` (8) ·
`would` (7) · `as_enters` (3) · `prevent_damage` · `replace_token` · `skip_event`.

**The plan asks whether the engine needs replacement effects at all. It does.** 59 of 389
gauntlet cards with text (15%), and 159 of 940 across the pool (17%), carry at least one
replacement clause. But the distribution answers a second question the plan did not ask:
the two commonest kinds, `cost_replacement` and `enters_modified`, are not the hard,
general "modify an event before it happens" machinery at all. A cost reduction is
arithmetic in the cost calculation, and `enters ready` / `enters exhausted` is a flag set
at the moment a permanent is put on the board. The genuinely general shapes — `would`
(CR 369.1's identifying word) and `instead` — are **22 gauntlet clauses across 16 cards**
(53 clauses across 39 cards in the whole pool).
That is the size of the layer that actually has to intercept events, and it is small
enough to build carefully rather than generally.

## Modifier kinds — 6 durations, plus two structural modifiers

`this_turn` (77) · `permanent` (19, a buff counter) · `while_state` (14) · `until_event`
(3) · `this_combat` (1) · `next_turn`.

Plus, as modifiers on the whole clause rather than the value:

- **`for_each(selector)`** — 15 gauntlet clauses, 39 over the pool. The min-clamp is part
  of this: `to a minimum of {1}` appears in the same breath as the cost reduction it
  bounds, and the prior engine's audit lists min-clamped modifiers among its documented
  failures.
- **keyword gate** — 67 gauntlet clauses, 9 distinct gating keywords. `[Empowered]{>}`,
  `[Level 6]{>}`, `[Legion] —`. CR 135.2.e.7 defines the binder; the gated ability is
  inactive while its keyword's condition is false.

## Keywords — 25, all of them, with parameters

The whole CR glossary (805–829) appears in the gauntlet. Five take a numeric parameter
(`Assault`, `Deflect`, `Shield`, `Hunt`, `Level`), with values up to `Level 16`. The
rules classify each into a kind, and the kind *is* the DSL construct: **eight** passives,
**six** triggered abilities (one of which, `Quick-Draw`, is also permissive), **three**
dependent, **two** permissive, **two** activated, **two** optional additional costs, one
action prerequisite and one deck constraint. §9 carries the table. That is **eight kinds
of construct**, not 25 separate ones — which is why a keyword belongs in the AST as a
parameterised *reference* rather than as 25 more primitives.

**`[Mighty]` is not a keyword.** It is bracketed 10 times across the pool (6 in the
gauntlet), the corpus sets it in the keyword font, and CR 805–829 does not define it — it is a *state*, defined only in
reminder text ("I'm Mighty while I have 5+ Might"). A
DSL that builds its keyword table by scanning brackets will invent a 26th keyword; one
that builds it from the CR will have no way to say what these six clauses say. It needs
to be a derived state, like `Empowered` but without a rule to cite.

---

# What the census cannot tell you

This is a count of surface forms. Five kinds of question are invisible to it, and all
five are the kind that produce a plausible game and a wrong one.

**1. Whether two identical phrasings mean the same thing.** `When I hold` and `When you
hold` are both `hold` here. CR 383.4.d.2 distinguishes them: the first triggers only from
a unit present at the battlefield during the Hold, the second from anything referencing
the player who Held. Same words, different subscription. The census counts the event; only
the rules say who is listening. The same trap sits under `When I conquer` / `When you
conquer` (383.4.c.2) and under every `me` / `this` / `it` in the corpus.

**2. Whether a clause targets.** CR 355.10 is two pages of exceptions determining whether
a game object mentioned in card text is a *target*: not if it is in a non-public zone, not
if it is only a restriction on another choice, not if it is part of a cost or a trigger
condition, not if it is programmatically selected. `Kill a unit at a battlefield` targets
the unit and not the battlefield; `Kill all units at a battlefield` targets the
battlefield and not the units. Those two clauses are one selector shape apart in this
report and a different legality check apart in the engine. The selector counts in §5 are
a count of *phrases*, and the targeting question has to be answered per clause against
355.10, not inferred from them.

**3. What order things happen in, and what is one event.** `Kill a friendly unit. If you
do, give +Might equal to its Might to another friendly unit` reads its Might *after* it
died. Sequencing, simultaneity (CR 370.1.a.2), and whether two effects are one event or
two decide half of the interactions a player would actually ask about, and none of it is
recoverable from clause boundaries. The census splits on punctuation; the rules split on
events.

**4. Which of several replacement effects applies, and in what order.** CR 372–373 give
the ordering to the controller of the object being acted on, cap each replacement at one
application per event, and define "sequence" over simultaneous events. §10 says how many
replacement clauses exist. It says nothing about the lattice they form when two of them
apply to the same death.

**5. Whether a primitive's argument is legal here.** `move` is one primitive; CR 446–453
decide whether a particular move is possible, and CR 456.3 says a Recall ignores exactly
the restrictions a Move obeys. `play … ignoring its cost` still pays Power on Rift Herald
because the text says *Energy* cost. A vocabulary is a set of verbs, not a set of
preconditions, and every one of these primitives will need its legality written against
the rules rather than against the phrase it was counted from.

There is a sixth, smaller one. **Nine clauses across the pool are in `unclassified`** —
listed in full in §15 — and they are not noise. `My hold effects are also conquer effects,
and vice versa` rewrites what a trigger *is*. `I have all {E} abilities of all friendly
legends, units, and gear` copies an unbounded set of activated abilities. `Starting with
the next player` reorders a procedure. `Any amount of your damage is enough` replaces a
damage threshold. These are the cards that will decide whether the DSL grows a general
mechanism or a quarantine list, and the census's job was to name them, not to make them
disappear.

---

# Caveats on the numbers themselves

- **The field is 95 lists and 396 distinct cards, not 96 and 398.** Issue #26 says 288
  gauntlet cards, from an earlier gauntlet; the merge commit for
  [#54](https://github.com/gear-null/riftbound-oracle/pull/54) says "96 tournament lists"
  and "398 distinct cards". The committed folder holds 95 `.json` files, and both
  `deck_cli.py gauntlet` and `SKILL.md` say 95/396. The census imports the skill's own
  loader precisely so this number cannot drift from the one the deck lab reports, and it
  quotes the content digest (`591cd98a6510`) beside the version so two runs against
  different fields are distinguishable. The commit message is the outlier.
- **`ambiguous` (37) counts name aliases, not cards.** The flag sits on bare champion
  names — `ahri`, `master yi` — that could mean several different cards. There are 37
  such names; there is no set of 37 ambiguous cards.
- **Errata is 52 cards under 63 keys.** The corpus already serves Riot's corrected text,
  so this census reads errata'd wording without doing anything special — except that
  Riot's articles use a *different symbol notation* and sometimes drop keyword brackets
  entirely (`Ganking (I can move…)`), which the normaliser has to handle or those 52
  cards parse differently from the other 902.
- **Occurrences, not clauses.** A clause may carry more than one primitive; the totals in
  §4 are occurrences. Clause counts are in §2.
- **The lexicons are ordered and first-match-wins, with an explicit fallback tier.** Rows
  like `set_stat` (matching "becomes") fire only when nothing specific did, so they read
  as what they are: the clauses whose verb the table cannot name. Changing that ordering
  changes the counts, which is why the tables live in code with the counts regenerated
  from them rather than being transcribed here.

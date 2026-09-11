"""Which of the table's checks the engine carries, and which it cannot.

The table's suite is 209 checks that took a 54-defect review to earn. The engine
is a second implementation of the same rules, so every one of them is a question
that has to be asked again — and "we ported the ones that seemed relevant" is
exactly the silent partial coverage this project is built to avoid.

So the mapping is DATA, and `engine_ported` in `selftest.py` checks it against
what actually ran:

* every table check is a key here, and a key that names no table check is stale —
  so a check renamed on either side breaks this instead of quietly losing cover;
* a value that is a check name must be the EXACT name of an engine check that
  ran, resolved against the suite's own registry;
* a value beginning `N/A:` or `SHARED:` must say why, in a sentence.

`SHARED` is the honest third answer: `cards.py`, `deckfile.py` and the battery
record are one implementation used by both tools, so the table's checks over
them already cover the engine and porting them would be running the same code
twice under two names.
"""

#: table check name -> engine check name, or "N/A: why", or "SHARED: why".
PORTED = {
    # -- cards and decks: one implementation, used by both ----------------
    "a subtitled card resolves across the separator both sources use":
        "SHARED: cards.py is the engine's card database too",
    "a name that could mean six different cards resolves to none of them":
        "SHARED: cards.py is the engine's card database too",
    "an ambiguous name is refused with the options named":
        "SHARED: cards.py is the engine's card database too",
    "a name that matches nothing at all returns nothing":
        "SHARED: cards.py is the engine's card database too",
    "an absent name is no card, not a crash":
        "SHARED: cards.py is the engine's card database too",
    "colorless is domainless, not a seventh domain":
        "SHARED: cards.py is the engine's card database too",
    "the corpus really does run sentences together (so this is not dead code)":
        "N/A: display spacing is for a reader; the engine never prints card text",
    "display spacing separates reminder text from rules text":
        "N/A: display spacing is for a reader; the engine never prints card text",
    "a keyword bracket is separated from the sentence after it":
        "N/A: display spacing is for a reader; the engine never prints card text",
    "text() is left byte-identical, so the corpus is still Riot's":
        "N/A: display spacing is for a reader; the engine never prints card text",
    "every affected card differs between the raw and the readable form":
        "N/A: display spacing is for a reader; the engine never prints card text",
    "symbol markup is not treated as a seam":
        "N/A: display spacing is for a reader; the engine never prints card text",
    "a lowercase word after punctuation is left alone — that is the "
    "extraction-artifact signature, not a sentence break":
        "N/A: display spacing is for a reader; the engine never prints card text",
    "the bare first-person 'I' after a seam is spaced too":
        "N/A: display spacing is for a reader; the engine never prints card text",
    "spacing is idempotent":
        "N/A: display spacing is for a reader; the engine never prints card text",
    "every deck that ships is legal and playable":
        "SHARED: deckfile.py builds the Deck objects the engine plays with",
    "a 4th copy of a card is rejected (103.2.b)":
        "SHARED: deckfile.py builds the Deck objects the engine plays with",
    "a rune deck that is not exactly 12 is rejected (103.3.a)":
        "SHARED: deckfile.py builds the Deck objects the engine plays with",
    "a deck with no Chosen Champion is rejected (103.2.a.1)":
        "SHARED: deckfile.py builds the Deck objects the engine plays with",
    "duplicate battlefield names are rejected (103.4.c)":
        "SHARED: deckfile.py builds the Deck objects the engine plays with",
    "champion tags are told apart from traits and regions (103.2.a.2)":
        "SHARED: deckfile.py builds the Deck objects the engine plays with",
    "every legend in the pool has a derivable champion tag":
        "SHARED: deckfile.py builds the Deck objects the engine plays with",
    "a champion sharing only a trait is not a legal Chosen Champion":
        "SHARED: deckfile.py builds the Deck objects the engine plays with",
    "a deck whose champion shares only a trait is rejected (103.2.a.2)":
        "SHARED: deckfile.py builds the Deck objects the engine plays with",
    "a deck naming an ambiguous card says so, not 'not in the card pool'":
        "SHARED: deckfile.py builds the Deck objects the engine plays with",
    "format legality is reported as unchecked, not as a pass":
        "SHARED: deckfile.py builds the Deck objects the engine plays with",
    "the Domain exception is reported as unchecked too (103.1.b.5)":
        "SHARED: deckfile.py builds the Deck objects the engine plays with",
    "the copy limit counts a card across every entry naming it (103.2.b)":
        "SHARED: deckfile.py builds the Deck objects the engine plays with",
    "the same battlefield listed twice is caught (103.4.c)":
        "SHARED: deckfile.py builds the Deck objects the engine plays with",
    "exactly one Chosen Champion copy leaves the deck, however it is listed (112)":
        "SHARED: deckfile.py builds the Deck objects the engine plays with",
    "the Chosen Champion is not shuffled into the Main Deck (112)":
        "the Chosen Champion starts in the Champion Zone, not the Main Deck (112)",

    # -- setup (110-118) --------------------------------------------------
    "both players open on 4 cards (116)":
        "a new game deals an opening hand of 4 to each seat (116)",
    "each player's Chosen Champion starts in the Champion Zone (112)":
        "the Chosen Champion starts in the Champion Zone, not the Main Deck (112)",
    "exactly 2 battlefields are in play, one from each deck (485.4)":
        "exactly two battlefields are in play, one provided by each seat (485.4)",
    "the same seed replays the same game exactly": "the same seed replays byte for byte",
    "who goes first is decided by the seed, not the clock (115)":
        "who goes first is decided by the seed, not fixed (115)",
    "a different seed deals a different game": "a different seed is a different game",
    "a seat's shuffle does not depend on the opposing deck":
        "a seat's shuffle does not depend on the opposing deck",
    "a different seed still deals the opponent a different hand":
        "the two seats draw from different streams at the same seed",
    "a seeded game survives being saved and reloaded mid-play":
        "N/A: the engine holds positions in memory and copies them with `clone`; "
        "there is no on-disk game yet, and `engine_cloning` is the property that "
        "replaces this one",
    "a mulligan redraws to the same hand size (117.2)":
        "a mulligan redraws to the same hand size (117.2)",
    "the cards not set aside are still in hand":
        "the cards not set aside are still in hand (117.1)",
    "a mulligan sets aside at most two cards (117.1)":
        "a mulligan sets aside at most two cards (117.1)",
    "a set-aside card cannot be redrawn by the same mulligan (117.2/117.3)":
        "a set-aside card cannot be redrawn by the same mulligan (117.2, 117.3)",

    # -- the turn (314-317) -----------------------------------------------
    "the turn player channels 2 runes (315.3)":
        "the player going first channels 2 on their first Channel Phase (315.3.b)",
    "the turn player draws for turn (315.4)": "the Turn Player draws for turn (315.4)",
    "play reaches the Main Phase":
        "the phases of a turn run in the order 314-317 lists them",
    "the player going second channels 3 on their first turn (485.7)":
        "the player going second channels 3 on their first Channel Phase (485.7)",
    "the extra rune is granted once, not every turn":
        "and 2 on every Channel Phase after that (485.7)",
    "Awaken readies everything the turn player controls (315.1.b)":
        "awaken readies everything the turn player controls (315.1.b)",
    "unspent Energy is lost at end of turn (317.2.e)":
        "unspent Energy is lost at the end of the turn (317.2.e)",
    "a turn cannot begin while another is still running (317)":
        "N/A: a turn is a sequence of phases inside one loop here, not a verb a "
        "caller can invoke out of order",
    "and begins normally once the previous one ended":
        "the turn passes to the other seat (317.3)",

    # -- runes, the pool and paying (163-168, 356-357, 429-430) -----------
    "exhausting a rune adds 1 Energy (164.2.a)":
        "exhausting a rune adds 1 Energy (164.2.a)",
    "a rune cannot be exhausted twice":
        "exhausting an already-exhausted object is refused (414)",
    "recycling a rune adds Power of its domain (164.2.b.1)":
        "recycling a rune adds Power of its domain (164.2.b.1)",
    "a recycled rune returns to the Rune Deck, not the Main Deck (161.2.b)":
        "a recycled rune returns to the Rune Deck, not the Main Deck (161.2.b)",
    "the rune pool is emptied entering the Main Phase (316.3)":
        "the Main Phase begins by emptying every rune pool (316.3)",
    "a 2-Energy card is payable from 2 runes":
        "a cost is payable from readied runes (357)",
    "paying leaves the pool at zero": "paying leaves the pool at zero (357)",
    "a cost beyond the runes available is refused, with the reason":
        "a cost beyond the runes available is refused, with the reason (358)",
    "an unpayable cost raises rather than going through":
        "an unpayable cost raises rather than going through (357)",
    "Power can be recycled from an EXHAUSTED rune (164.2.b)":
        "Power can be recycled from an EXHAUSTED rune (164.2.b)",
    "paying that way actually recycles the rune":
        "and paying that way actually recycles the rune (416)",

    # -- movement (144, 445-458) -----------------------------------------
    "a Standard Move exhausts the unit (144.2)":
        "a Standard Move exhausts the unit (144.2)",
    "arriving at an uncontrolled battlefield contests it (190.3.a.1)":
        "a unit moving onto a battlefield it does not control contests it (190.3.a.1)",
    "the Standard Move cannot go battlefield → battlefield without Ganking (144.4)":
        "a Standard Move cannot go battlefield -> battlefield without Ganking (144.4.c)",
    "an exhausted unit cannot pay its own move cost":
        "an exhausted unit cannot pay its move cost (144.2)",
    "a Standard Move outside the Main Phase is refused (144.1.a)":
        "a Standard Move happens during the Main Phase (144.1.a)",

    # -- combat (459-466) -------------------------------------------------
    "damage is assigned lethal-first, not spread (465.2.c.3)":
        "damage is assigned lethal-first (465.2.c.3)",
    "a 0-Might unit is assigned its minimum lethal of 1, not skipped (142.4.b)":
        "a 0-Might unit needs a non-zero assignment to take lethal damage (142.4.b)",
    "the excess is not dumped while a unit is still owed lethal (465.2.c.4)":
        "excess lands only once every defender has its lethal (465.2.c.4)",
    "no more than minimum lethal is assigned while it is the only target (465.2.c.4)":
        "no more than the minimum lethal lands while it is the only target (465.2.c.4)",
    "equal Might trades both units simultaneously (465.2.c.1.a)":
        "equal Might trades both units simultaneously (465.2.c.1.a)",
    "a repelled attacker is recalled to base, not left standing (466.1.a.2)":
        "attackers still present when defenders remain are recalled (466.1.a.2)",
    "winning a combat establishes control and Conquers (466.5.d)":
        "winning a combat establishes control and Conquers (466.5.d)",
    "units are healed after combat (466.1.a.1)":
        "combat heals every unit before the result is determined (466.1.a.1)",
    "a 0-Might unit assigned no damage is not lethally damaged (465.2.c.2)":
        "and assigning nothing at all leaves it alive (465.2.c.2)",
    "the preview shows every involved unit's printed text":
        "N/A: `combat_preview` is a reader's tool — it puts card text in front of "
        "a person before they assign damage. The engine assigns it",
    "the preview changes nothing":
        "N/A: `combat_preview` is a reader's tool — it puts card text in front of "
        "a person before they assign damage. The engine assigns it",
    "the preview reports an assignment that is at least lethal":
        "damage is assigned lethal-first (465.2.c.3)",
    "a Might change applied before combat changes who dies":
        "a Might change applied before combat changes who dies (703, 142.4.b)",
    "combat logs the text of the units that fought, so it can be audited":
        "N/A: the table prints card text so its reader can apply it. The engine's "
        "log is a record of physical operations, and card text is issue #25",
    "the Attacker is whoever applied Contested, not the turn player (464.2.c.1)":
        "the Attacker is whoever's unit applied Contested (464.2.c.1)",
    "the preview labels the resident unit the defender":
        "every unit at the battlefield takes its controller's designation (464.2.c.3)",
    "a repelled attack still leaves the defender establishing control (466.5)":
        "a defender that survives keeps the battlefield (466.5)",
    "a unit with lethal damage marked is killed at a cleanup (323.5)":
        "a unit with lethal damage marked is killed at a cleanup (323.5)",
    "gear arriving at a battlefield does not contest it (190.3.a)":
        "gear arriving at a battlefield does not contest it (190.3.a)",

    # -- scoring, control and winning (188-196, 467-472) ------------------
    "scoring gains a point": "a Score gains a point (468.1)",
    "a Hold outside the Beginning Phase is refused (469.2)":
        "a Hold is refused outside the Beginning Phase (469.2)",
    "a battlefield cannot be scored twice in a turn (470)":
        "a battlefield is scored at most once per turn per player (470)",
    "the turn player Holds every battlefield they control (315.2.b.2)":
        "the Turn Player Holds every battlefield they control, in the Beginning "
        "Phase (315.2.b)",
    "a Conquer at 7 points draws instead of winning when a battlefield is "
    "unscored (471.1.b.1)":
        "a Conquer at one point short draws instead, without every battlefield "
        "scored (471.1.b.1)",
    "a Score whose point was withheld still triggers the battlefield (471.2)":
        "N/A: 471.2's Score abilities are battlefield card text, which this slice "
        "does not execute (docs/engine/spec.md, issue #25)",
    "the final point lands once every battlefield has been scored that turn":
        "with every battlefield scored, the final point lands (471.1.b.1)",
    "reaching the Victory Score wins the game (472)":
        "the Victory Score with more points than any opponent wins (472)",
    "a tie at the Victory Score wins for nobody (472)":
        "a tie at the Victory Score wins for nobody (472)",
    "a finished game refuses to start another turn":
        "a finished game asks no more questions (196)",
    "a win during the Scoring Step stops the turn there (196)":
        "a win in the Scoring Step stops the turn where it happened (196, 472)",
    "control is lost when no units remain there (190.4.c)":
        "a player with no units at a battlefield loses control of it (323.6)",
    "moving alone onto an empty battlefield takes control and Conquers (466.5.d)":
        "moving alone onto an empty battlefield takes control and Conquers (469.1)",
    "a cleanup does not hand control to either side while a combat is staged "
    "(190.4.b)":
        "a cleanup hands control to nobody while a combat is staged there (190.4.b)",
    "a unit in the opponent's base is recalled at cleanup (323.7)":
        "a permanent in another player's base is recalled (323.7)",
    "a unit in its OWN base is left alone by the same sweep (323.7)":
        "a unit in its OWN base is left alone by the same sweep (323.7)",
    "unattached Gear left at a battlefield is recalled at cleanup (323.7)":
        "unattached Gear left at a battlefield is recalled at cleanup (323.7)",
    "Gear attached to a unit is NOT recalled off the battlefield (323.7)":
        "N/A: attachment is card text and no engine object has an `attached_to` "
        "yet (docs/engine/spec.md, 119-187)",
    "a unit at a battlefield is untouched by the Gear clause (323.7)":
        "a unit at a battlefield is untouched by the Gear clause (323.7)",
    "a raised Victory Score is respected, not overridden by the mode's 8":
        "a raised Victory Score is respected, not overridden by the mode's 8 (485.3)",
    "the raised Victory Score still ends the game when reached":
        "and the raised Victory Score still ends the game when reached (472)",
    "battlefield text is surfaced at setup, where it starts applying":
        "N/A: the table prints battlefield text for its reader to apply; the "
        "engine will execute it when battlefield abilities land (issue #25)",

    # -- burn out (431) ---------------------------------------------------
    "drawing from an empty Main Deck reports a Burn Out (431)":
        "drawing from an empty Main Deck reports a Burn Out (431)",
    "burning out recycles the trash into the Main Deck (431.2.b)":
        "and recycles the trash into the Main Deck (431.2.b)",
    "burning out gives an opponent a point (431.2.c)":
        "burning out hands an opponent a point (431.2.c)",
    "the draw that caused the burn out still completes (431.2.d, 315.4.b.2)":
        "the draw that caused the burn out still completes (431.2.d, 315.4.b.2)",
    "an empty deck AND an empty trash hands the game to the opponent (431.3.a)":
        "an empty trash keeps the deck empty, and the points keep coming (431.3)",
    "that win is immediate, without waiting for a cleanup (431.3.c.1)":
        "a burn-out win is immediate, without waiting for a cleanup (431.3.c.1)",

    # -- privacy (108.7.c) ------------------------------------------------
    "the public log does not name the cards anyone drew (108.7.c)":
        "a draw is private to the drawing seat in the log (108.7.c)",
    "the log still shows that a draw happened":
        "the log still shows that a draw happened (108.7.c)",
    "a seat sees its own draws in full": "a seat sees its own draws in full (108.7.c)",
    "and still not the opponent's": "and still not the opponent's (108.7.c)",
    "a finished game can be reviewed in full":
        "a finished game can be reviewed in full",

    # -- refusals and identity --------------------------------------------
    "a refused `cast` does not spend the runes it had already paid":
        "a refused answer leaves the position byte-identical",
    "a refused move does not leave the unit exhausted":
        "a refused answer leaves the position byte-identical",
    "a refused action leaves the table byte-identical":
        "a refused answer leaves the position byte-identical",
    "a card in no zone cannot be put into play":
        "a card in no zone cannot be put into play",
    "a name that is not a card at all is refused":
        "N/A: the engine never takes a card name from a caller — every name it "
        "moves came out of a zone it was already in",
    "an effect may put a card into play from a named zone":
        "an effect may put a card into play from a named zone",
    "a loaded game never mints an id an object already has":
        "N/A: there is no saved game to load; `clone` copies `next_id` with the "
        "rest of the position",
    "loading derives the id counter past every id on the board":
        "N/A: there is no saved game to load; `clone` copies `next_id` with the "
        "rest of the position",
    "minting skips an id already in use": "minting skips an id already in use",
    "minted ids are unique among themselves": "minted ids are unique among themselves",
    "an import refuses to overwrite a DIFFERENT deck on the same slug":
        "SHARED: importer.py and deckfile.py are how both tools get a decklist",
    "re-importing the same deck is an update, not a collision":
        "SHARED: importer.py and deckfile.py are how both tools get a decklist",
    "no deck name is claimed by both gauntlet/ and decks/ today":
        "SHARED: importer.py and deckfile.py are how both tools get a decklist",
    "a name claimed by two decks is refused, not silently picked":
        "SHARED: importer.py and deckfile.py are how both tools get a decklist",
    "the refusal names both directories so the caller can choose":
        "SHARED: importer.py and deckfile.py are how both tools get a decklist",
    "an unambiguous name resolves to the gauntlet file it names":
        "SHARED: importer.py and deckfile.py are how both tools get a decklist",
    "a saved game naming an ambiguous deck says WHICH game and where":
        "N/A: saved games belong to the table's `do` loop",

    # -- guards -----------------------------------------------------------
    "1v1 seats exactly two players (485.1)":
        "N/A: `Game.new` takes exactly two decks by signature, so there is no "
        "third seat to refuse",
    "setup cannot run twice":
        "N/A: setup is a phase of the one loop, entered once, not a verb a caller "
        "can call again",
    "a deck with no battlefields cannot start a game (103.4)":
        "a deck with no battlefields cannot start a game (103.4)",
    "a spell not in hand cannot be played (157)":
        "a card not in the zone it is played from is refused (354)",
    "a card cannot be discarded from a hand that lacks it (422)":
        "a card cannot be discarded from a hand that lacks it (422)",
    "a card cannot be recycled from a zone it is not in (416)":
        "N/A: the engine has no free-standing recycle verb — 416 runs inside the "
        "mulligan, the burn out and a rune's Power ability",
    "a card cannot enter play from a zone it is not in":
        "a card in no zone cannot be put into play",
    "an unknown permanent id is refused, not silently ignored":
        "an unknown object id is refused, not silently ignored",
    "an unknown rune id is refused": "a rune id that is not a rune is refused",
    "an unknown object id is refused":
        "an unknown object id is refused, not silently ignored",
    "a location that is not a location is refused":
        "a location that is not a location is refused",
    "a rune cannot be recycled by the player who does not control it":
        "a rune cannot be recycled by a player who does not control it",
    "a unit cannot move to where it already is (447)":
        "a move to where the unit already stands is not a Move (446.3.b)",
    "only units have a Standard Move (144)": "only units have a Standard Move (144)",
    "an exhausted unit is refused by the MOVE COST guard, not by exhaust() (144.2)":
        "an exhausted unit cannot pay its move cost (144.2)",
    "exhausting an already-exhausted object is refused (414)":
        "exhausting an already-exhausted object is refused (414)",
    "combat needs units from two players to resolve (461)":
        "a combat with one side gone skips the Damage Step (465.1)",
    "a mulligan cannot set aside a card that is not in hand (117.1)":
        "N/A: the engine offers only the cards in hand as options and `answer` "
        "refuses everything else, so there is no illegal set-aside to guard",
    "`pay` still refuses when `can_pay` wrongly says yes":
        "`pay` still refuses when `can_pay` wrongly says yes",
    "a seat other than 0 or 1 is refused":
        "N/A: a seat is an index into two-element lists inside the kernel and is "
        "never taken from a caller",
    "an unknown action verb is refused by name":
        "N/A: `do`'s verbs are the table's text interface; the engine's interface "
        "is the enumerated option list",

    # -- the table's own instruments --------------------------------------
    "a saved game restores every field of its state":
        "N/A: no on-disk game; `a clone shares no zone, object, chain item, task "
        "or log with the original` is the property that replaces it",
    "a card's printed text appears the first time it is rendered":
        "N/A: `view.py` renders the table for a person to read",
    "the same render twice does not repeat the text":
        "N/A: `view.py` renders the table for a person to read",
    "--verbose brings the text back":
        "N/A: `view.py` renders the table for a person to read",
    "what is hidden is the TEXT, never the card's presence":
        "N/A: `view.py` renders the table for a person to read",
    "what has been seen survives a save and reload":
        "N/A: `view.py` renders the table for a person to read",
    "a mirror match is not counted as a win (it is 50% by construction)":
        "N/A: the journal records games a person played by hand",
    "a real matchup is still counted":
        "N/A: the journal records games a person played by hand",
    "a 3-1 does not read as a confident 75%":
        "N/A: the journal records games a person played by hand",
    "every count notation is read the same way":
        "SHARED: importer.py and deckfile.py are how both tools get a decklist",
    "a set code after the name is not part of the name":
        "SHARED: importer.py and deckfile.py are how both tools get a decklist",
    "cards are filed by type, not by the heading above them":
        "SHARED: importer.py and deckfile.py are how both tools get a decklist",
    "the legend is taken from its own line and resolved":
        "SHARED: importer.py and deckfile.py are how both tools get a decklist",
    "section headings and comments are not read as cards":
        "SHARED: importer.py and deckfile.py are how both tools get a decklist",
    "an unknown card name refuses the whole import":
        "SHARED: importer.py and deckfile.py are how both tools get a decklist",
    "an ambiguous card name refuses rather than picking one":
        "SHARED: importer.py and deckfile.py are how both tools get a decklist",
    "a list with no legend is refused (it decides Domain Identity)":
        "SHARED: importer.py and deckfile.py are how both tools get a decklist",
    "every bad name is reported, not just the first":
        "SHARED: importer.py and deckfile.py are how both tools get a decklist",
    "an imported deck records its own provenance":
        "SHARED: importer.py and deckfile.py are how both tools get a decklist",
    "an ambiguous Chosen Champion is left unset and explained":
        "SHARED: importer.py and deckfile.py are how both tools get a decklist",
    "an action script splits on ; without cutting inside quotes":
        "N/A: `do`'s script splitter is the table's text interface",
    "quoted card names survive the split":
        "N/A: `do`'s script splitter is the table's text interface",
    "an empty script is not an error":
        "N/A: `do`'s script splitter is the table's text interface",
}


# -- the field, the docs and the battery's own record -----------------
PORTED['the gauntlet is versioned, not merely dated'] = (
    'SHARED: the gauntlet is the field BOTH tools measure against, and deckfile/deck_cli compute its version and fingerprint once for both')
PORTED['`gauntlet` prints the version it is measuring against'] = (
    'SHARED: the gauntlet is the field BOTH tools measure against, and deckfile/deck_cli compute its version and fingerprint once for both')
PORTED['`gauntlet` prints a fingerprint of the field, not just its name'] = (
    'SHARED: the gauntlet is the field BOTH tools measure against, and deckfile/deck_cli compute its version and fingerprint once for both')
PORTED['the fingerprint follows the contents, not the file names alone'] = (
    'SHARED: the gauntlet is the field BOTH tools measure against, and deckfile/deck_cli compute its version and fingerprint once for both')
PORTED['the fingerprint is stable when nothing has changed'] = (
    'SHARED: the gauntlet is the field BOTH tools measure against, and deckfile/deck_cli compute its version and fingerprint once for both')
PORTED['`gauntlet` prints how many lists the field holds'] = (
    'SHARED: the gauntlet is the field BOTH tools measure against, and deckfile/deck_cli compute its version and fingerprint once for both')
PORTED['`gauntlet` prints the distinct-card count, the scripting frontier'] = (
    'SHARED: the gauntlet is the field BOTH tools measure against, and deckfile/deck_cli compute its version and fingerprint once for both')
PORTED['two spellings of one card count once (the frontier is cards, not names)'] = (
    'SHARED: the gauntlet is the field BOTH tools measure against, and deckfile/deck_cli compute its version and fingerprint once for both')
PORTED['no card is counted twice in the frontier under two spellings'] = (
    'SHARED: the gauntlet is the field BOTH tools measure against, and deckfile/deck_cli compute its version and fingerprint once for both')
PORTED['the legend and the Chosen Champion are inside the frontier'] = (
    'SHARED: the gauntlet is the field BOTH tools measure against, and deckfile/deck_cli compute its version and fingerprint once for both')
PORTED['the gauntlet is only gauntlet/, never the decks you are building'] = (
    'SHARED: the gauntlet is the field BOTH tools measure against, and deckfile/deck_cli compute its version and fingerprint once for both')
PORTED['a copy with no version file reports one rather than crashing'] = (
    'SHARED: the gauntlet is the field BOTH tools measure against, and deckfile/deck_cli compute its version and fingerprint once for both')
PORTED['every list in the field records where and when it came from'] = (
    'SHARED: the gauntlet is the field BOTH tools measure against, and deckfile/deck_cli compute its version and fingerprint once for both')
PORTED['every action the CLI advertises exists'] = (
    "N/A: SKILL.md and the CLI's help are the table's front door; the engine's interface is the enumerated option list")
PORTED["every action in SKILL.md's own examples is real"] = (
    "N/A: SKILL.md and the CLI's help are the table's front door; the engine's interface is the enumerated option list")
PORTED['the table never tells the reader to run something that does not exist'] = (
    "N/A: SKILL.md and the CLI's help are the table's front door; the engine's interface is the enumerated option list")
PORTED["SKILL.md's numbers match the mode: channel 2 runes"] = (
    "N/A: SKILL.md and the CLI's help are the table's front door; the engine's interface is the enumerated option list")
PORTED["SKILL.md's numbers match the mode: first to 8 points"] = (
    "N/A: SKILL.md and the CLI's help are the table's front door; the engine's interface is the enumerated option list")
PORTED["SKILL.md's numbers match the mode: opening hand of 4"] = (
    "N/A: SKILL.md and the CLI's help are the table's front door; the engine's interface is the enumerated option list")

#: The suite's own `proven_ratio` group: 8 checks that report how much of THIS
#: suite — the engine's half included — the mutation battery has watched fail.
#: They are not classified above because they are not coverage of a rule, and
#: because they run after the engine's sections and so are not in the registry
#: when `engine_ported` reads it.
PROVEN_RATIO_CHECKS = 8


def classify(value):
    """"ported", "shared" or "na"."""
    if value.startswith("N/A:"):
        return "na"
    if value.startswith("SHARED:"):
        return "shared"
    return "ported"

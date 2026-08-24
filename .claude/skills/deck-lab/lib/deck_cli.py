"""deck-lab — a table for Riftbound, and the deck math around it.

    python3 deck_cli.py <command> [args]

Run `python3 deck_cli.py help` for the command list.
"""
import argparse
import hashlib
import json
import os
import shlex
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import analyze
import cards
import deckfile
import session
import table
import view
from table import RulesError


# -- actions ---------------------------------------------------------------
#
# One verb per physical thing that can happen. Nothing here interprets card
# text: a card that says "draw 2" is applied by calling `draw`, which is why the
# log ends up a record of moves rather than of intentions.

def _seat(v):
    s = int(v)
    if s not in (0, 1):
        raise RulesError(f"seat must be 0 or 1, got {v!r}")
    return s


def _loc(v):
    return v if ":" in v else f"bf:{v}"


def act(t, argv):
    """Apply one action, or leave the table exactly as it was.

    Several verbs mutate before they can refuse — `cast` pays a cost before the
    card can turn out not to be in hand, `standard_move` exhausts before the
    destination is checked — and `cmd_do` then saved the half-applied state
    while printing "nothing after the refusal was applied". That message was
    false, and the resulting state was one no legal sequence of actions could
    have produced.

    Hoisting every precondition above every mutation would have to be redone for
    each new verb and silently forgotten once. Snapshotting is one guarantee in
    one place, and it holds for verbs nobody has written yet.
    """
    before = t.as_dict()
    try:
        return _act(t, argv)
    except Exception:
        t.restore(before)
        raise


def _act(t, argv):
    verb, rest = argv[0], argv[1:]

    if verb == "beginturn":
        return t.begin_turn(_seat(rest[0]) if rest else None)
    if verb == "endturn":
        return t.end_turn()
    if verb == "cleanup":
        return t.cleanup()
    if verb == "mulligan":
        return t.mulligan(_seat(rest[0]), set_aside=rest[1:])

    if verb == "draw":
        return t.draw(_seat(rest[0]), int(rest[1]) if len(rest) > 1 else 1)
    if verb == "channel":
        n = int(rest[1]) if len(rest) > 1 else 1
        return t.channel(_seat(rest[0]), n, exhausted="exhausted" in rest)
    if verb == "discard":
        return t.discard(_seat(rest[0]), rest[1])
    if verb == "recycle":
        return t.recycle_card(_seat(rest[0]), rest[1], rest[2] if len(rest) > 2 else "hand")

    if verb == "cast":
        # Pay, then put it where it goes. A spell's text is printed for the
        # reader to apply; a unit or gear arrives on the board.
        seat, name = _seat(rest[0]), rest[1]
        t.pay(seat, name)
        if cards.card_type(name) == cards.SPELL:
            return f"{name}: {t.play_spell(seat, name)}"
        return t.put_into_play(seat, name, _loc(rest[2]) if len(rest) > 2 else None).id
    if verb == "pay":
        return t.pay(_seat(rest[0]), rest[1])
    if verb == "play":
        return t.play_spell(_seat(rest[0]), rest[1])
    if verb == "put":
        return t.put_into_play(
            _seat(rest[0]), rest[1],
            _loc(rest[2]) if len(rest) > 2 else None,
            source=rest[3] if len(rest) > 3 else None,
        ).id

    if verb == "move":
        return t.move(rest[0], _loc(rest[1]))
    if verb == "smove":
        return t.standard_move(rest[0], _loc(rest[1]))
    if verb == "recall":
        return t.recall(rest[0])
    if verb == "exhaust":
        return t.exhaust(rest[0])
    if verb == "ready":
        return t.ready(rest[0])

    if verb == "damage":
        perm = t.permanent(rest[0])
        perm.damage += int(rest[1])
        return t.note(f"{perm.name} [{perm.id}] takes {rest[1]} damage ({perm.damage}/{perm.might})")
    if verb == "heal":
        perm = t.permanent(rest[0])
        perm.damage = 0
        return t.note(f"{perm.name} [{perm.id}] is healed")
    if verb == "buff":
        perm = t.permanent(rest[0])
        perm.buffs += int(rest[1]) if len(rest) > 1 else 1
        return t.note(f"{perm.name} [{perm.id}] now has {perm.buffs} buff(s), {perm.might} Might")
    if verb == "kill":
        return t.to_trash(rest[0], reason=" ".join(rest[1:]) or "killed")
    if verb == "banish":
        return t.banish(rest[0])
    if verb == "mark":
        # A state the engine does not model, carried on the object and shown.
        perm = t.permanent(rest[0])
        perm.note = " ".join(rest[1:])
        return t.note(f"{perm.name} [{perm.id}] marked: {perm.note}")

    if verb == "tap":
        return t.tap_for_energy(_seat(rest[0]), int(rest[1]) if len(rest) > 1 else 1)
    if verb == "energy":
        return t.add_energy(_seat(rest[0]), int(rest[1]))
    if verb == "power":
        return t.add_power(_seat(rest[0]), rest[1], int(rest[2]) if len(rest) > 2 else 1)

    if verb == "precombat":
        p = t.combat_preview(int(rest[0]))
        lines = [
            f"{p['battlefield']}: seat {p['attacker_seat']} {p['attacker_might']}M "
            f"vs seat {p['defender_seat']} {p['defender_might']}M"
            + ("" if p["staged"] else "   (no combat staged — one side has no units)")
        ]
        for u in p["units"]:
            lines.append(f"  [{u['id']}] {u['name']} {u['might']}M {u['role']}")
            if u["text"]:
                lines.append(f"        {u['text']}")
        lines.append(f"  would assign  attacker→{p['onto_defenders']}  defender→{p['onto_attackers']}")
        lines.append("  apply any Might changes with `buff` before running `combat`.")
        return "\n".join(lines)
    if verb == "combat":
        return json.dumps(t.resolve_combat(int(rest[0])))
    if verb == "score":
        return t.score(_seat(rest[0]), int(rest[1]), method=rest[2] if len(rest) > 2 else "Conquer")
    if verb == "control":
        return t.establish_control(_seat(rest[0]), int(rest[1])).name
    if verb == "target":
        return t.set_target(int(rest[0]), " ".join(rest[1:]))
    if verb == "note":
        return t.note(" ".join(rest))

    raise RulesError(f"unknown action {verb!r} — run `help` for the list")


# -- commands --------------------------------------------------------------

def cmd_decks(args):
    for path in deckfile.available():
        d = deckfile.load(path)
        legal = deckfile.check(d)
        where = "gauntlet" if os.sep + "gauntlet" + os.sep in path else "decks"
        flag = "  " if legal.legal else "!!"
        print(f"{flag} {where:8} {os.path.splitext(os.path.basename(path))[0]}")
        print(f"     {d.legend} · {d.chosen_champion or 'NO CHOSEN CHAMPION'}")


def cmd_check(args):
    d = deckfile.resolve(args.deck)
    r = deckfile.check(d)
    print(f"{d.name}\n  legend: {d.legend}\n  champion: {d.chosen_champion}")
    print(f"\n  {'LEGAL' if r.legal else 'ILLEGAL'} for {deckfile.MODE['name']}")
    for e in r.errors:
        print(f"    error   {e}")
    for w in r.warnings:
        print(f"    warn    {w}")
    for u in r.unchecked:
        print(f"    unchecked  {u}")
    return 0 if r.legal else 1


def cmd_card(args):
    name = " ".join(args.name)
    card = cards.find(name)
    if card is None:
        options = cards.candidates(name)
        print(f"no card named {name!r}" + (f"\n  could be: {', '.join(options)}" if options else ""))
        return 1
    s = card["stats"]
    print(card["name"])
    print(f"  {s['type']}"
          + (f" · {s['supertype']}" if s.get("supertype") else "")
          + f" · {'/'.join(s['domain'])} · {s['rarity']}")
    print(f"  energy {s['energy']}  power {s['power']}  might {s['might']}")
    if s.get("tags"):
        print(f"  tags: {', '.join(s['tags'])}")
    print(f"\n  {card['text'] or '(no text)'}")
    if card.get("incomplete"):
        print(f"\n  INCOMPLETE: {card['incomplete']}")


def cmd_analyze(args):
    d = deckfile.resolve(args.deck)
    result = analyze.analyse(d, trials=args.trials)
    if args.json:
        print(json.dumps(result, indent=1))
        return
    c = result["composition"]
    print(f"{d.name}  —  {d.legend}")
    print(f"  {c['main_deck_size']} main deck · {'/'.join(c['domain_identity'])} · "
          f"runes {c['rune_split']}")
    print(f"  types {c['by_type']}")
    print(f"  curve {c['curve']}  (avg {c['average_energy']} energy, {c['average_might']} might)")
    print(f"  {c['cards_with_text']} of {c['shuffled_cards']} shuffled cards have rules text")
    if c["ambiguous_power_split"]:
        print(f"  power split not in the card data for: {', '.join(c['ambiguous_power_split'])}")
    for label in ("on_the_play", "on_the_draw"):
        s = result[label]
        print(f"\n  {label.replace('_', ' ')}  ({s['trials']} shuffles)")
        print("    turn          " + "".join(f"{t:>7}" for t in range(1, s["turns"] + 1)))
        print("    has a play    " + "".join(f"{v:>7.0%}" for v in s["has_a_play"][1:]))
        print("    castable      " + "".join(f"{v:>7.1f}" for v in s["castable_in_hand"][1:]))
        print("    stranded      " + "".join(f"{v:>7.1f}" for v in s["stranded_in_hand"][1:]))
        print("    power denied  " + "".join(f"{v:>7.0%}" for v in s["power_denied"][1:]))
        for domain, series in sorted(s["domain_online"].items()):
            print(f"    {domain:<13} " + "".join(f"{v:>7.0%}" for v in series[1:]))


def cmd_new(args):
    decks = [deckfile.resolve(args.deck_a), deckfile.resolve(args.deck_b)]
    for d in decks:
        r = deckfile.check(d)
        if not r.legal:
            print(f"{d.name} is not legal — fix it or the game proves nothing:")
            for e in r.errors:
                print(f"  {e}")
            return 1
    t = table.Table(decks, seed=args.seed, first=args.first).setup()
    # Truncating each deck name to 20 characters made two different pairings
    # collide on one filename, and the second game overwrote the first with no
    # warning. The digest is short, stable, and distinguishes the full pairing.
    default = f"{args.deck_a[:20]}-vs-{args.deck_b[:20]}-s{args.seed}"
    digest = hashlib.sha256(
        f"{args.deck_a}|{args.deck_b}|{args.seed}".encode()
    ).hexdigest()[:6]
    name = args.name or f"{default}-{digest}"
    if os.path.exists(session.path_for(name)) and not args.force:
        print(f"a game called '{session.slug(name)}' already exists — pass --force to "
              "start over, or --name to keep both.")
        return 1
    session.save(t, name, [args.deck_a, args.deck_b])
    print("\n".join(view.log_lines(t, seat=None)))
    print(f"\ngame '{session.slug(name)}' saved · seat 0 = {decks[0].name} · seat 1 = {decks[1].name}")
    print("mulligans are next: `do 'mulligan 0 \"Card A\"'` sets aside that card, "
          "draws a replacement, then shuffles it back (117; at most two)")


def cmd_state(args):
    name, t, refs = session.load(args.game)
    out = view.render(t, seat=args.seat, full=args.full, verbose=args.verbose)
    # `first_sight` is state: showing a card's text is what marks it as seen, so
    # the render has to be saved or the next one repeats everything.
    session.save(t, name, refs)
    print(out)


def cmd_log(args):
    name, t, _ = session.load(args.game)
    if args.full and t.winner is None:
        print("refusing --full on a game still in progress: it would show both hands.")
        print("finish the game, or pass --seat N to read it from one seat.")
        return 1
    print("\n".join(view.log_lines(t, last=args.last, seat=args.seat, full=args.full)))


def split_actions(script):
    """Split an action script on `;`, without breaking quoted text.

    A plain `script.split(";")` cuts inside quotes, so a note like
    `note "drew 1; kept the rune"` became an unterminated string and took the
    whole batch down — including the actions that had already been applied.
    """
    lex = shlex.shlex(script, posix=True, punctuation_chars=";")
    lex.whitespace_split = True
    lex.commenters = ""
    out, current = [], []
    for token in lex:
        if token == ";":
            if current:
                out.append(current)
            current = []
        else:
            current.append(token)
    if current:
        out.append(current)
    return out


def cmd_do(args):
    """Apply one or more actions, separated by `;`, then show the table.

    Batched on purpose. A turn is a dozen physical operations and issuing them
    one command at a time is most of the cost of playing a game at all.
    """
    name, t, refs = session.load(args.game)
    script = " ".join(args.actions)
    try:
        batches = split_actions(script)
    except ValueError as err:
        print(f"error: could not parse the action script — {err}")
        return 1
    if args.seat is not None:
        t.note(f"— seat {args.seat} acting —")
    else:
        t.note("— acting with no seat declared —")
    results = []
    for argv in batches:
        chunk = " ".join(shlex.quote(a) if " " in a else a for a in argv)
        try:
            results.append((chunk, act(t, argv)))
        except (RulesError, KeyError, IndexError, ValueError) as err:
            # Stop at the first refusal and save what happened before it, so the
            # table never holds a half-applied action.
            session.save(t, name, refs)
            print("\n".join(f"  ok  {c}" for c, _ in results))
            print(f"\n  REFUSED  {chunk}\n    {err}")
            print("\nnothing after the refusal was applied.")
            return 1
    session.save(t, name, refs)
    for chunk, result in results:
        print(f"  ok  {chunk}")
        if isinstance(result, str) and result and result not in chunk:
            print(f"        {result}")
    if not args.quiet:
        print()
        print(view.render(t, seat=args.seat, full=args.full, verbose=args.verbose))


def cmd_games(args):
    current = None
    if os.path.exists(session.CURRENT):
        with open(session.CURRENT, encoding="utf-8") as fh:
            current = session.slug(fh.read().strip())
    for name in session.games():
        print(("* " if name == current else "  ") + name)


def cmd_report(args):
    import report as report_mod
    d = deckfile.resolve(args.deck)
    out = report_mod.build(d, trials=args.trials, out_path=args.out)
    print(f"wrote {out}")


def cmd_record(args):
    """Record a finished game so the report can aggregate it.

    Read off the saved game rather than typed in, so the recorded winner is the
    one the table actually declared and the seed is the one that produced it.
    """
    import journal
    name, t, refs = session.load(args.game)
    if t.winner is None and not args.force:
        print(f"game '{name}' has no winner yet — finish it, or pass --force to record it as unfinished")
        return 1
    decks = [deckfile.resolve(r) for r in refs]
    entry = {
        "game": name,
        "deck": decks[0].name,
        "opponent": decks[1].name,
        "seed": t.seed,
        "first_player": t.first_player,
        "turns": t.turn,
        "winner_seat": t.winner,
        "winner_deck": decks[t.winner].name if t.winner is not None else None,
        "points": [p.points for p in t.players],
        "note": args.note or "",
    }
    journal.record(entry)
    print(json.dumps(entry, indent=1))


def cmd_journal(args):
    import journal
    rows = journal.entries()
    if not rows:
        print("no games recorded yet")
        return
    for row in rows:
        print(f"  {row.get('winner_deck') or 'unfinished':<32} beat "
              f"{row.get('opponent') if row.get('winner_deck') == row.get('deck') else row.get('deck'):<32}"
              f" seed {row.get('seed')} · {row.get('turns')} turns · {row.get('points')}")


def cmd_import(args):
    """Turn a pasted decklist into a gauntlet opponent.

    Four of the six decklist sites measured refuse scripted requests, so the
    gauntlet cannot be built by scraping alone. Anything a person can copy can
    be imported here.
    """
    import importer
    text = sys.stdin.read() if args.file == "-" else open(args.file, encoding="utf-8").read()
    try:
        deck = importer.build(text, name=args.name, source=args.source,
                              legend=args.legend, champion=args.champion)
    except importer.ImportError_ as err:
        print("could not import this list:")
        print(err)
        return 1
    path = importer.save(deck, slug=args.slug)
    loaded = deckfile.load(path)
    result = deckfile.check(loaded)
    print(f"{deck['name']} → {path}")
    print(f"  legend    {deck['legend']}")
    print(f"  champion  {deck['chosen_champion'] or 'UNRESOLVED'}")
    if deck.get("chosen_champion_note"):
        print(f"            {deck['chosen_champion_note']}")
    print(f"  {sum(c['qty'] for c in deck['main'])} main · "
          f"{sum(c['qty'] for c in deck['runes'])} runes · "
          f"{sum(c['qty'] for c in deck['battlefields'])} battlefields")
    print(f"\n{'LEGAL' if result.legal else 'NOT YET LEGAL'} for {deckfile.MODE['name']}")
    for e in result.errors:
        print(f"    {e}")
    return 0 if result.legal else 1


def cmd_gauntlet(args):
    """What the gauntlet covers, and what it does not.

    A gauntlet with no deck in your own domain pair tells you nothing about your
    own mirror, and that gap is invisible until an analysis is already running.
    """
    import collections
    decks = [deckfile.load(p) for p in deckfile.available()]
    gauntlet = [d for d in decks if os.sep + "gauntlet" + os.sep in (d.path or "")]
    by_pair = collections.Counter()
    illegal = []
    for d in gauntlet:
        by_pair["/".join(sorted(d.domain_identity())) or "—"] += 1
        if not deckfile.check(d).legal:
            illegal.append(d.name)

    print(f"{len(gauntlet)} deck(s) in the gauntlet\n")
    print("  by domain identity:")
    for pair, n in sorted(by_pair.items(), key=lambda x: (-x[1], x[0])):
        print(f"    {n:>3}  {pair}")

    pairs = sorted(cards.DOMAINS)
    have = set(by_pair)
    missing = [f"{a}/{b}" for i, a in enumerate(pairs) for b in pairs[i+1:]
               if f"{a}/{b}" not in have]
    print(f"\n{len(have)} of 15 domain pairings represented; missing "
          f"{len(missing)}:\n{', '.join(missing)}")
    if illegal:
        print(f"\n{len(illegal)} NOT PLAYABLE: {', '.join(illegal)}")
    if args.against:
        try:
            mine = deckfile.resolve(args.against)
        except KeyError as err:
            print(f"\n{err}")
            return 1
        pair = "/".join(sorted(mine.domain_identity()))
        same = [d.name for d in gauntlet if "/".join(sorted(d.domain_identity())) == pair]
        print(f"\n{mine.name} is {pair}; the gauntlet holds "
              f"{len(same)} deck(s) in that pairing"
              + (f": {', '.join(same)}" if same else " — no mirror to test against"))
    return 0


def cmd_selftest(args):
    import selftest
    return selftest.main()


def cmd_mutants(args):
    """Prove the selftest can fail. Slow; a pre-merge gate, not an inner loop."""
    import mutants
    return mutants.main()


def cmd_help(args):
    print(__doc__)
    print("""commands
  decks                        every deck in gauntlet/ and decks/, with legality
  gauntlet [--against DECK]    what the gauntlet covers, and what it does not
  import <file|-> [--name X]   paste a decklist from anywhere and make it an
                               opponent. Most decklist sites block scraping, so
                               this is how the gauntlet actually gets built
  check <deck>                 deck construction report (103)
  card <name>                  a card's printed text and stats
  analyze <deck>               shuffle math: curve, domain access, stranded cards
  report <deck>                the same, as a self-contained HTML page
  new <deckA> <deckB>          start a game (--seed, --first, --name)
  state --seat N               the table from that seat. Card text prints once,
                               the first time you see the card; --verbose repeats it
  do "<action>; <action>"      apply actions, then show the table
  log [--seat N]               the game log; another seat's draws stay hidden.
                               --full needs a finished game
  games                        saved games; * marks the current one
  record [--note "..."]        log the current game's result to the journal
  journal                      every recorded result
  selftest                     regression harness
  mutants                      reintroduce each defect the selftest claims to
                               catch, and prove the right check goes red

actions for `do`
  beginturn [seat]             awaken, hold-score, channel, draw, into main phase
  endturn                      heal, expire, empty pools, pass the turn
  mulligan <seat> [card...]    set aside up to 2 named cards, draw that many,
                               then shuffle the set-aside cards back (117)
  cast <seat> <card> [loc]     pay the cost, then resolve or put into play
  put <seat> <card> [loc] [from]  onto the board without paying. `from` is the
                               zone it came from: trash, main_deck, banished,
                               or elsewhere for a token
  play <seat> <card>           a spell to the trash; its text is printed back
  pay <seat> <card>            pay a cost on its own
  draw <seat> [n]              channel <seat> [n] [exhausted]
  discard <seat> <card>        recycle <seat> <card> [zone]
  smove <id> <loc>             Standard Move: exhausts, base<->battlefield only
  move <id> <loc>              a move from an effect, no exhaust cost
  recall <id>                  exhaust <id>            ready <id>
  damage <id> <n>              heal <id>               buff <id> [n]
  kill <id> [reason]           banish <id>             mark <id> <text>
  tap <seat> [n]               energy <seat> <n>       power <seat> <domain> [n]
  precombat <bf>               what combat WOULD do: every unit's text, the
                               assignment, no changes. Always run this first.
  combat <bf>                  damage step + resolution at a battlefield
  score <seat> <bf> [method]   control <seat> <bf>     target <n> [reason]
  note <text>                  a line in the log

locations are base:0, base:1, bf:0, bf:1 — a bare number means a battlefield.
card names contain spaces, so quote them: cast 0 "Stellacorn Herder" bf:0
""")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="deck_cli.py", add_help=False)
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("decks")
    p = sub.add_parser("check"); p.add_argument("deck")
    p = sub.add_parser("card"); p.add_argument("name", nargs="+")
    p = sub.add_parser("analyze"); p.add_argument("deck")
    p.add_argument("--trials", type=int, default=20000); p.add_argument("--json", action="store_true")
    p = sub.add_parser("report"); p.add_argument("deck")
    p.add_argument("--trials", type=int, default=50000); p.add_argument("--out")
    p = sub.add_parser("new")
    p.add_argument("deck_a"); p.add_argument("deck_b")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--first", type=int, default=None)
    p.add_argument("--name"); p.add_argument("--force", action="store_true")
    p = sub.add_parser("state")
    p.add_argument("--seat", type=int); p.add_argument("--full", action="store_true")
    p.add_argument("--game"); p.add_argument("--verbose", action="store_true")
    p = sub.add_parser("log"); p.add_argument("--last", type=int); p.add_argument("--game")
    p.add_argument("--seat", type=int); p.add_argument("--full", action="store_true")
    p = sub.add_parser("do"); p.add_argument("actions", nargs="+")
    p.add_argument("--seat", type=int); p.add_argument("--full", action="store_true")
    p.add_argument("--game"); p.add_argument("--quiet", action="store_true")
    p.add_argument("--verbose", action="store_true")
    sub.add_parser("games")
    p = sub.add_parser("import"); p.add_argument("file")
    p.add_argument("--name"); p.add_argument("--source"); p.add_argument("--slug")
    p.add_argument("--legend"); p.add_argument("--champion")
    p = sub.add_parser("gauntlet"); p.add_argument("--against")
    p = sub.add_parser("record")
    p.add_argument("--game"); p.add_argument("--note"); p.add_argument("--force", action="store_true")
    sub.add_parser("journal")
    sub.add_parser("selftest")
    sub.add_parser("mutants")
    sub.add_parser("help")

    args = parser.parse_args(argv)
    handler = {
        "decks": cmd_decks, "check": cmd_check, "card": cmd_card, "analyze": cmd_analyze,
        "report": cmd_report, "new": cmd_new, "state": cmd_state, "log": cmd_log,
        "do": cmd_do, "games": cmd_games, "record": cmd_record, "journal": cmd_journal,
        "import": cmd_import, "gauntlet": cmd_gauntlet,
        "selftest": cmd_selftest, "mutants": cmd_mutants, "help": cmd_help,
    }.get(args.command, cmd_help)
    try:
        return handler(args) or 0
    except (RulesError, KeyError, FileNotFoundError, ValueError) as err:
        # A traceback here would bury the one line that says what went wrong.
        print(f"error: {err}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

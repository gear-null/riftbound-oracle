#!/usr/bin/env python3
"""Mutation battery — proves the selftest can actually fail.

WHY THIS EXISTS

A pre-merge review of this skill found 54 defects, every one of them shipping
past a suite that reported 71/71. The suite was green because it tested the
implementation rather than the rules: delete the 466.1.a.2 attacker recall, or
the 316.3 Main-Phase pool emptying, and the checks named for those rules still
passed.

So: a check that has never been observed to fail is not yet a check. This file
reintroduces each defect the suite claims to catch, runs the suite against a
damaged copy, and asserts the right check goes red. A mutant that SURVIVES is a
check that is lying about what it covers.

    python3 mutants.py            (or: python3 deck_cli.py mutants)

Nothing here touches the working tree — every mutant is applied to a throwaway
copy of the whole skill folder.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)

FAILED_RE = re.compile(r"^\s*(\d+)/(\d+) passed", re.M)


# Each mutant reintroduces ONE defect and names a distinctive fragment of the
# check that must catch it. `expect` is matched against the [FAIL] names.
MUTANTS = [
    # ---- card resolution ------------------------------------------------
    dict(name="resolve an ambiguous base name to an arbitrary printing",
         file="cards.py",
         find='        if entry is not None and not entry.get("ambiguous"):',
         repl="        if entry is not None:",
         expect="could mean six different cards"),
    dict(name="match only the literal card name, not the other separator",
         file="cards.py",
         find='    for v in (base, base.replace(", ", " - "), base.replace(" - ", ", ")):',
         repl="    for v in (base,):",
         expect="separator"),
    dict(name="treat Colorless as a seventh domain",
         file="cards.py",
         find='    return [d for d in (stats(name).get("domain") or []) if d != COLORLESS]',
         repl='    return list(stats(name).get("domain") or [])',
         expect="colorless is domainless"),

    # ---- deck construction (103) ---------------------------------------
    dict(name="drop the 3-copy limit",
         file="deckfile.py",
         find='        if qty > mode["max_copies"]:',
         repl="        if False:",
         expect="4th copy"),
    dict(name="drop the 12-rune requirement",
         file="deckfile.py",
         find='    if total_runes != mode["rune_deck_size"]:',
         repl="    if False:",
         expect="rune deck"),
    dict(name="allow duplicate battlefield names",
         file="deckfile.py",
         find="        if qty > 1:\n            r.errors.append(f\"{qty}x {name}: battlefields must have distinct names (103.4.c)\")",
         repl="        if False:\n            pass",
         expect="duplicate battlefield"),
    dict(name="allow a deck with no Chosen Champion",
         file="deckfile.py",
         find='    if not deck.chosen_champion:',
         repl="    if False:",
         expect="no Chosen Champion"),
    dict(name="shuffle the Chosen Champion into the Main Deck",
         file="deckfile.py",
         find="            if not removed and _same(name, self.chosen_champion):\n                copies -= 1\n                removed = True",
         repl="            if False:\n                copies -= 1\n                removed = True",
         expect="not shuffled into the Main Deck"),

    # ---- setup and determinism -----------------------------------------
    dict(name="deal an opening hand of 3",
         file="table.py",
         find='            self.draw(p.seat, self.mode["opening_hand"], reason="opening hand")',
         repl="            self.draw(p.seat, 3, reason='opening hand')",
         expect="open on 4 cards"),
    dict(name="leave the Chosen Champion out of the Champion Zone",
         file="table.py",
         find="        self.champion_zone = [deck.chosen_champion] if deck.chosen_champion else []",
         repl="        self.champion_zone = []",
         expect="Champion Zone"),
    dict(name="reseed the shuffle from the clock instead of the seed",
         file="table.py",
         find="        self.rng = random.Random(seed)",
         repl="        self.rng = random.Random()",
         expect="same seed replays"),

    # ---- the turn (314-317) --------------------------------------------
    dict(name="channel 1 rune a turn instead of 2",
         file="table.py",
         find='        n = self.mode["channel_per_turn"]',
         repl="        n = 1",
         expect="channels 2 runes"),
    dict(name="skip the draw for turn",
         file="table.py",
         find='        self.draw(seat, 1, reason="draw phase")',
         repl="        pass",
         expect="draws for turn"),
    dict(name="grant the second player's extra rune every turn",
         file="table.py",
         find="        if seat != self.first_player and not self.second_player_channel_bonus_used:",
         repl="        if seat != self.first_player:",
         expect="granted once"),
    dict(name="stop readying on Awaken",
         file="table.py",
         find="        for obj in readied:\n            obj.exhausted = False",
         repl="        for obj in []:\n            obj.exhausted = False",
         expect="Awaken readies"),
    dict(name="keep unspent Energy across turns",
         file="table.py",
         find="        # 317.2.e Rune pools empty.\n        for p in self.players:\n            self.empty_pool(p.seat)",
         repl="        # 317.2.e Rune pools empty.\n        for p in []:\n            self.empty_pool(p.seat)",
         expect="unspent Energy is lost"),
    dict(name="skip emptying the rune pool entering the Main Phase",
         file="table.py",
         find="        self.phase = MAIN\n        for p in self.players:\n            self.empty_pool(p.seat)",
         repl="        self.phase = MAIN\n        for p in []:\n            self.empty_pool(p.seat)",
         expect="emptied entering the Main Phase"),

    # ---- resources ------------------------------------------------------
    dict(name="let an exhausted rune be tapped again",
         file="table.py",
         find="        available = [r for r in self.runes if r.controller == seat and not r.exhausted]",
         repl="        available = [r for r in self.runes if r.controller == seat]",
         expect="exhausted twice"),
    dict(name="send a recycled rune to the Main Deck",
         file="table.py",
         find="        self.player(seat).rune_deck.append(rune.name)",
         repl="        self.player(seat).main_deck.append(rune.name)",
         expect="returns to the Rune Deck"),
    dict(name="let any cost be paid regardless of runes available",
         file="table.py",
         find='        if cost["energy"] > energy_capacity:',
         repl="        if False:",
         expect="refused, with the reason"),

    # ---- movement -------------------------------------------------------
    dict(name="make the Standard Move free",
         file="table.py",
         find="        self.exhaust(oid)\n        return self.move(oid, destination)",
         repl="        return self.move(oid, destination)",
         expect="Standard Move exhausts"),
    dict(name="allow a battlefield-to-battlefield Standard Move",
         file="table.py",
         find="        if origin_kind == BATTLEFIELD and dest_kind == BATTLEFIELD:",
         repl="        if False:",
         expect="without Ganking"),
    dict(name="stop applying Contested on arrival",
         file="table.py",
         find="        if bf.controller != perm.controller and not bf.contested:",
         repl="        if False:",
         expect="contests it"),
    dict(name="allow a Standard Move outside the Main Phase",
         file="table.py",
         find="        if self.phase != MAIN:",
         repl="        if False:",
         expect="outside the Main Phase"),

    # ---- combat ---------------------------------------------------------
    dict(name="spread combat damage instead of assigning lethal first",
         file="table.py",
         find="            give = min(pool, need)",
         repl="            give = min(pool, 1)",
         expect="lethal-first"),
    dict(name="call zero damage lethal again",
         file="table.py",
         find="        dead = [u for u in attackers + defenders if u.damage > 0 and u.damage >= u.might]",
         repl="        dead = [u for u in attackers + defenders if u.damage >= u.might]",
         expect="0-Might unit"),
    dict(name="stop recalling a repelled attacker",
         file="table.py",
         find="            for unit in list(attackers):\n                self.recall(unit.id)",
         repl="            for unit in []:\n                self.recall(unit.id)",
         expect="repelled attacker"),
    dict(name="stop healing units after combat",
         file="table.py",
         find="        for perm in self.permanents:\n            if perm.is_unit:\n                perm.damage = 0  # 466.1.a.1 heal all units",
         repl="        for perm in []:\n            if perm.is_unit:\n                perm.damage = 0",
         expect="healed after combat"),
    dict(name="hide the printed text of units in a combat preview",
         file="table.py",
         find='                    "text": cards.text(u.name) if cards.find(u.name) else "",',
         repl='                    "text": "",',
         expect="printed text"),

    dict(name="treat a 0-Might unit's minimum lethal as zero again",
         file="table.py",
         find="            need = 0 if already_lethal else max(target.might - target.damage, 1)",
         repl="            need = 0 if already_lethal else max(target.might - target.damage, 0)",
         expect="0-Might"),
    dict(name="assume the turn player is always the Attacker",
         file="table.py",
         find="        if bf.contested_by is None:",
         repl="        return self.turn_player\n        if bf.contested_by is None:",
         expect="whoever applied Contested"),
    dict(name="forget which seat applied Contested",
         file="table.py",
         find="            bf.contested_by = perm.controller",
         repl="            bf.contested_by = None",
         expect="applied Contested"),
    dict(name="let gear apply Contested",
         file="table.py",
         find="        if not perm.is_unit:\n            return",
         repl="        if False:\n            return",
         expect="gear arriving"),
    dict(name="stop at 'no result' when the attackers are repelled",
         file="table.py",
         find='        result = "attackers repelled" if repelled else "control established"',
         repl='        if repelled:\n            return {"result": "no result", "battlefield": bf.name}\n        result = "control established"',
         expect="repelled attack still leaves"),
    dict(name="stop killing lethally damaged units at a cleanup",
         file="table.py",
         find="            if perm.is_unit and perm.damage > 0 and perm.damage >= perm.might:",
         repl="            if False:",
         expect="lethal damage marked is killed"),
    dict(name="discard an explicit empty damage assignment",
         file="table.py",
         find="            if attacker_assignment is None else dict(attacker_assignment)",
         repl="            if not attacker_assignment else dict(attacker_assignment)",
         expect="repelled attacker"),

    # ---- scoring --------------------------------------------------------
    dict(name="allow a battlefield to be scored twice in a turn",
         file="table.py",
         find="        if seat in bf.scored_by:",
         repl="        if False:",
         expect="scored twice"),
    dict(name="stop Holding controlled battlefields in the Beginning Phase",
         file="table.py",
         find="            if bf.controller == seat:\n                self.score(seat, bf.index, method=\"Hold\")",
         repl="            if False:\n                self.score(seat, bf.index, method=\"Hold\")",
         expect="Holds every battlefield"),
    dict(name="grant the final point without scoring every battlefield",
         file="table.py",
         find="            if all(seat in b.scored_by for b in self.battlefields):",
         repl="            if True:",
         expect="draws instead of winning"),
    dict(name="win on points alone, ignoring the opponent's score",
         file="table.py",
         find="        if all(best.points > o.points for o in self.players if o is not best):",
         repl="        if True:",
         expect="Victory Score",
         optional=True),
    dict(name="hard-code the Victory Score to the mode's 8",
         file="table.py",
         find="        target = self.victory_target\n        eligible =",
         repl='        target = self.mode["victory_score"]\n        eligible =',
         expect="raised Victory Score"),
    dict(name="carry on with the turn after the game is won",
         file="table.py",
         find="        if self.winner is not None:\n            # 196: when a player wins, the game ends",
         repl="        if False:\n            # 196: when a player wins, the game ends",
         expect="stops the turn there"),
    dict(name="stop losing control of an empty battlefield",
         file="table.py",
         find="            if bf.controller is not None and bf.controller not in controllers:",
         repl="            if False:",
         expect="control is lost"),
    dict(name="stop establishing control when a lone unit holds a battlefield",
         file="table.py",
         find="            if len(controllers) == 1:",
         repl="            if False:",
         expect="moving alone"),
    dict(name="settle control at a cleanup while both sides are present",
         file="table.py",
         find="            if not bf.contested or len(controllers) > 1:",
         repl="            if not bf.contested:",
         expect="combat is staged"),

    # ---- atomicity and produced state ------------------------------------
    dict(name="save a half-applied action instead of rolling it back",
         file="deck_cli.py",
         find="    except Exception:\n        t.restore(before)\n        raise",
         repl="    except Exception:\n        raise",
         expect="does not spend the runes"),
    dict(name="let a card enter play from no zone at all",
         file="table.py",
         find='                raise RulesError(\n                    f"{name} is not in seat {seat}\'s hand or Champion Zone — pass a "',
         repl='                self.note("conjured")\n            if False:\n                raise RulesError(\n                    f"{name} is not in seat {seat}\'s hand or Champion Zone — pass a "',
         expect="card in no zone"),
    dict(name="put a name that is not a card into play",
         file="table.py",
         find="        if cards.find(name) is None:",
         repl="        if False:",
         expect="not a card at all"),

    # ---- counting cards, not entries --------------------------------------
    dict(name="count the copy limit per JSON entry again",
         file="deckfile.py",
         find="    for name, qty in sorted(_tally(deck.main).items()):",
         repl="    for name, qty in deck.main:",
         expect="every entry naming it"),
    dict(name="count battlefield duplicates per entry again",
         file="deckfile.py",
         find="    for name, qty in sorted(_tally(deck.battlefields).items()):",
         repl="    for name, qty in deck.battlefields:",
         expect="listed twice"),
    dict(name="remove one Chosen Champion copy per matching entry",
         file="deckfile.py",
         find="            if not removed and _same(name, self.chosen_champion):\n                copies -= 1\n                removed = True",
         repl="            if self.chosen_champion and _same(name, self.chosen_champion):\n                copies -= 1",
         expect="however it is listed"),
    dict(name="stop reporting the Domain exception as unchecked",
         file="deckfile.py",
         find='        "cards added irrespective of Domain by a game effect (103.1.b.5) — the "',
         repl='        "" or "cards added irrespective of Domain by a game effect — the "',
         expect="103.1.b.5"),

    # ---- burn out and persistence ---------------------------------------
    dict(name="draw from an empty deck in silence",
         file="table.py",
         find='        self.note(f"seat {seat} BURNS OUT (431)")',
         repl="        pass",
         expect="reports a Burn Out"),
    dict(name="burn out without recycling the trash",
         file="table.py",
         find="            p.main_deck.extend(p.trash)\n            p.trash = []",
         repl="            pass",
         expect="recycles the trash"),
    dict(name="burn out without giving an opponent a point",
         file="table.py",
         find="        self.player(opponent).points += 1",
         repl="        pass",
         expect="gives an opponent a point"),
    dict(name="abandon the draw that caused the burn out",
         file="table.py",
         find="            self.burn_out(seat)\n            if self.winner is not None:\n                break",
         repl="            self.burn_out(seat)\n            break",
         expect="still completes"),
    dict(name="drop a field when saving a game",
         file="table.py",
         find='            "victory_target": self.victory_target,',
         repl="",
         expect="restores every field"),

    # ---- rendering cost and privacy ---------------------------------------
    dict(name="reprint every card's text on every render",
         file="table.py",
         find="        if name in self.text_shown:\n            return False",
         repl="        if False:\n            return False",
         expect="does not repeat the text"),
    dict(name="forget what has been seen when the game is saved",
         file="table.py",
         find='            "text_shown": sorted(self.text_shown),',
         repl="",
         expect="survives a save and reload"),
    dict(name="hide the card itself, not just its text",
         file="view.py",
         find="        if cards.might(name) is not None:\n            line += f\"  [{cards.might(name)}M]\"\n        out.append(line)",
         repl="        if cards.might(name) is not None:\n            line += f\"  [{cards.might(name)}M]\"\n        if name in t.text_shown:\n            continue\n        out.append(line)",
         expect="never the card's presence"),
    dict(name="put drawn card names back in the public log",
         file="table.py",
         find="                private_to=seat,\n                detail=\", \".join(drawn),",
         repl='                detail=", ".join(drawn),',
         expect="does not name the cards"),
    dict(name="show every seat's private detail to everyone",
         file="view.py",
         find="            if full or owner == seat:",
         repl="            if True:",
         expect="does not name the cards"),

    # ---- the action layer ------------------------------------------------
    dict(name="split an action script on ; without respecting quotes",
         file="deck_cli.py",
         find='    lex = shlex.shlex(script, posix=True, punctuation_chars=";")',
         repl='    lex = shlex.shlex(script.replace(";", " ; "), posix=True)',
         expect="without cutting inside quotes"),
]


def run_one(m):
    """Apply one mutant to a throwaway copy and return the checks that failed."""
    with tempfile.TemporaryDirectory() as tmp:
        skill = os.path.join(tmp, "deck-lab")
        shutil.copytree(SKILL, skill, ignore=shutil.ignore_patterns(
            "reports", "games", "__pycache__", "*.tmp"))
        lib = os.path.join(skill, "lib")
        path = os.path.join(lib, m["file"])
        src = open(path, encoding="utf-8").read()
        if src.count(m["find"]) != 1:
            return None, (f"anchor matched {src.count(m['find'])}x — the mutant is "
                          "stale and is testing nothing")
        open(path, "w", encoding="utf-8").write(src.replace(m["find"], m["repl"]))

        r = subprocess.run([sys.executable, os.path.join(lib, "selftest.py")],
                           capture_output=True, text=True, cwd=lib)
        failed = re.findall(r"^\s*\[FAIL\]\s*(.+?)(?:\s+—.*)?$", r.stdout, re.M)
        if failed:
            return failed, None
        if r.returncode != 0:
            last = [x for x in r.stderr.strip().splitlines() if x.strip()]
            return ["<suite crashed> " + (last[-1] if last else "no output")], None
        return [], None


def main():
    print("mutation battery — reintroducing defects the suite claims to catch\n")
    survived, stale, crashed_only = [], [], []
    caught = 0
    for i, m in enumerate(MUTANTS, 1):
        failures, err = run_one(m)
        if err:
            stale.append((m["name"], err))
            print(f"  [STALE]    {i:2}. {m['name']}\n              {err}")
            continue
        crashes = [f for f in failures if f.startswith("<suite crashed>")]
        named = [f for f in failures if not f.startswith("<suite crashed>")]
        # Credit only a NAMED check. A traceback that happens to contain the
        # expected words is the suite dying, not the suite detecting.
        hit = [f for f in named if m["expect"].lower() in f.lower()]
        if hit:
            caught += 1
            print(f"  [caught]   {i:2}. {m['name']}\n              → {hit[0]}")
        elif named:
            caught += 1
            print(f"  [caught*]  {i:2}. {m['name']}\n              → {named[0]}"
                  f"   (expected a check naming {m['expect']!r})")
        elif crashes:
            crashed_only.append((m["name"], crashes[0]))
            print(f"  [CRASH]    {i:2}. {m['name']}\n              {crashes[0]}")
        else:
            survived.append(m)
            print(f"  [SURVIVED] {i:2}. {m['name']}\n              nothing failed — "
                  f"no check covers this")

    print(f"\n{caught}/{len(MUTANTS)} mutants caught")
    if crashed_only:
        print(f"\n{len(crashed_only)} mutant(s) only crashed the suite rather than "
              "failing a named check:")
        for name, why in crashed_only:
            print(f"  - {name}\n      {why}")
    if stale:
        print(f"\n{len(stale)} STALE anchor(s) — the mutant no longer matches the source:")
        for name, why in stale:
            print(f"  - {name}\n      {why}")
    if survived:
        print(f"\n{len(survived)} SURVIVED — each is a behaviour with no check behind it:")
        for m in survived:
            print(f"  - {m['name']}  ({m['file']}, expected {m['expect']!r})")
        return 1
    return 1 if (stale or crashed_only) else 0


if __name__ == "__main__":
    sys.exit(main())

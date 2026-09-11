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
import json
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

    dict(name="match a legend's traits and regions as champion tags",
         file="cards.py",
         find="            if t in bases",
         repl="            if True",
         expect="told apart from traits"),
    dict(name="bind the Chosen Champion by any shared tag",
         file="deckfile.py",
         find="            if legend_tags and not (cards.champion_tags_of(cc) & legend_tags):",
         repl="            if legend_tags and not (set(cards.tags(cc)) & set(cards.tags(deck.legend))):",
         expect="shares only a trait is rejected"),
    dict(name="report an ambiguous card name as missing from the pool",
         file="deckfile.py",
         find="        (ambiguous if options else unknown).append(",
         repl="        (unknown if True else ambiguous).append(",
         expect="says so, not"),

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
    dict(name="draw both seats' shuffles from one shared stream",
         file="table.py",
         find="            self.seat_rng[p.seat].shuffle(p.main_deck)\n            self.seat_rng[p.seat].shuffle(p.rune_deck)",
         repl="            self.rng.shuffle(p.main_deck)\n            self.rng.shuffle(p.rune_deck)",
         expect="does not depend on the opposing deck"),
    dict(name="forget the per-seat generator positions when saving",
         file="table.py",
         find='            "seat_rng_state": [_jsonable_rng(r.getstate()) for r in self.seat_rng],',
         repl="",
         expect="restores every field"),
    dict(name="reseed the per-seat shuffles from the clock",
         file="table.py",
         find='        self.seat_rng = [random.Random(f"{seed}/seat{i}") for i in range(2)]',
         repl="        self.seat_rng = [random.Random() for i in range(2)]",
         expect="same seed replays"),
    dict(name="reseed the shared stream from the clock",
         file="table.py",
         find="        self.rng = random.Random(seed)",
         repl="        self.rng = random.Random()",
         expect="who goes first is decided by the seed"),

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

    dict(name="let a turn begin while another is still running",
         file="table.py",
         find="        if self.setup_done and self.phase not in (None, ENDING):",
         repl="        if False:",
         expect="cannot begin while another"),

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
         find='                    "text": cards.for_reading(u.name) if cards.find(u.name) else "",',
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
         expect="equal Might trades both units simultaneously (465.2.c.1.a)"),
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
    # ---- card text as a human reads it ----------------------------------
    dict(name="stop spacing the reminder/rules seam at display time",
         file="cards.py",
         find='    return _SEAM.sub(r"\\1 \\2", printed or "")',
         repl="    return printed or \"\"",
         expect="separates reminder text from rules text"),
    dict(name="space the seam in the CORPUS, not just at display",
         file="cards.py",
         find='    """Printed rules text, verbatim. Do not add spacing here — see for_reading."""\n    return require(name).get("text", "")',
         repl='    """Printed rules text, verbatim. Do not add spacing here — see for_reading."""\n    return space_seams(require(name).get("text", ""))',
         expect="byte-identical, so the corpus is still Riot"),
    dict(name="require a lowercase tail, dropping the first-person 'I' cards",
         file="cards.py",
         find='_SEAM = re.compile(r"([)\\]])([A-Z])")',
         repl='_SEAM = re.compile(r"([)\\]])([A-Z][a-z])")',
         expect="first-person 'I' after a seam"),
    dict(name="admit ':' to the seam class, so symbol markup splits",
         file="cards.py",
         find='_SEAM = re.compile(r"([)\\]])([A-Z])")',
         repl='_SEAM = re.compile(r"([)\\]:])([A-Z])")',
         expect="symbol markup is not treated as a seam"),
    dict(name="space a lowercase artifact too, hiding the Gemhand signature",
         file="cards.py",
         find='_SEAM = re.compile(r"([)\\]])([A-Z])")',
         repl='_SEAM = re.compile(r"([)\\]])([A-Za-z])")',
         expect="lowercase word after punctuation is left alone"),
    # ---- the suite reporting on itself ----------------------------------
    dict(name="stop reporting how much of the suite has been tested",
         file="selftest.py",
         find="    print(proven_line())",
         repl="    proven_line()",
         expect="actually prints the ratio"),
    dict(name="score a missing record as full coverage instead of saying so",
         file="selftest.py",
         find='        return ("  (no record of which checks can fail — run `mutants` to make "',
         repl='        return ("  of N distinct checks, N have been observed to fail (100%). (",',
         expect="missing record is reported, not silently scored"),
    dict(name="keep credit for checks that no longer exist",
         file="selftest.py",
         find='    return set(names) & set(record.get("observed_to_fail", ()))',
         repl='    return set(record.get("observed_to_fail", ()))',
         expect="NOT kept for a recorded check that no longer exists"),
    dict(name="count only PROVEN checks, so an untested one cannot lower the ratio",
         file="selftest.py",
         find="    names = set(NAMES)\n    proven = proven_among(names, record)",
         repl="    proven = proven_among(set(NAMES), record)\n    names = proven",
         expect="and it is counted, so the two numbers disagree visibly"),
    dict(name="tie-break a two-directory name collision instead of refusing",
         file="deckfile.py",
         find="    if len(exact) > 1:",
         repl="    if False:",
         expect="refused, not silently picked"),
    dict(name="let a session collision report without naming the session",
         file="session.py",
         find='                f"saved game {name!r} cannot be loaded — {err}. "',
         repl='                f"{err}. "',
         expect="says WHICH game and where"),
    dict(name="resolve an unambiguous name to whatever sorts first",
         file="deckfile.py",
         find="    if exact:\n        return load(exact[0])",
         repl="    if exact:\n        return load(sorted(available())[0])",
         expect="resolves to the gauntlet file it names"),
    dict(name="report the collision without saying which decks collided",
         file="deckfile.py",
         find='            + ", ".join(_where(c) for c in sorted(exact))',
         repl='            + "two decks"',
         expect="names both directories"),
    # The over-broad direction — refusing a name that matches ONE deck — has no
    # mutant here on purpose, and the reason is worth stating precisely because
    # the first version of this comment got it wrong. `resolve()` is load-
    # bearing for the whole suite, so the mutant aborts in `setup_rules`, three
    # groups before the collision checks are reached. It is not that the
    # collision check fails impolitely; it is that the run never gets there.
    # This battery counts a crash as "not caught by a named check" rather than
    # claiming a catch, so the mutant would be scored as a survivor either way.
    dict(name="let a permanent rest in another player's base (323.7)",
         file="table.py",
         find='            if where == BASE and perm.location != f"{BASE}:{perm.controller}":',
         repl="            if False:",
         expect="in the opponent's base is recalled"),
    dict(name="recall from EVERY base, including the controller's own (323.7)",
         file="table.py",
         find='            if where == BASE and perm.location != f"{BASE}:{perm.controller}":',
         repl="            if where == BASE:",
         expect="in its OWN base is left alone"),
    dict(name="leave unattached Gear standing at a battlefield (323.7)",
         file="table.py",
         find="            elif where == BATTLEFIELD and not perm.is_unit and perm.attached_to is None:",
         repl="            elif False:",
         expect="unattached Gear left at a battlefield"),
    dict(name="recall attached Gear along with the loose kind (323.7)",
         file="table.py",
         find="            elif where == BATTLEFIELD and not perm.is_unit and perm.attached_to is None:",
         repl="            elif where == BATTLEFIELD and not perm.is_unit:",
         expect="attached to a unit is NOT recalled"),
    dict(name="sweep units off battlefields with the Gear clause (323.7)",
         file="table.py",
         find="            elif where == BATTLEFIELD and not perm.is_unit and perm.attached_to is None:",
         repl="            elif where == BATTLEFIELD and perm.attached_to is None:",
         expect="a unit at a battlefield is untouched"),

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
         expect="the log still shows that a draw happened"),
    dict(name="show every seat's private detail to everyone",
         file="view.py",
         find="            if full or owner == seat:",
         repl="            if True:",
         expect="does not name the cards"),

    # ---- mulligan, determinism, payment, scoring --------------------------
    dict(name="recycle the set-aside cards before drawing replacements",
         file="table.py",
         find="        self.draw(seat, len(set_aside), reason=\"mulligan\")\n        p.main_deck.extend(set_aside)",
         repl="        p.main_deck.extend(set_aside)\n        self.rng.shuffle(p.main_deck)\n        self.draw(seat, len(set_aside), reason=\"mulligan\")",
         expect="cannot be redrawn"),
    dict(name="let a mulligan set aside any number of cards",
         file="table.py",
         find="        if len(set_aside) > self.MULLIGAN_MAX:",
         repl="        if False:",
         expect="at most two"),
    dict(name="forget the generator's position when saving",
         file="table.py",
         find='            "rng_state": _jsonable_rng(self.rng.getstate()),',
         repl="",
         expect="restores every field"),
    dict(name="require a rune to be readied before recycling it for Power",
         file="table.py",
         find="        spent_runes = matching([r for r in mine if r.exhausted])",
         repl="        spent_runes = []",
         expect="EXHAUSTED rune"),
    dict(name="award a Hold at any point in the turn",
         file="table.py",
         find='        if method == "Hold" and self.phase != BEGINNING:',
         repl="        if False:",
         expect="outside the Beginning Phase"),
    dict(name="count a mirror match as a win",
         file="journal.py",
         find='        if row.get("deck") == deck and row.get("opponent") == deck:',
         repl="        if False:",
         expect="mirror match"),

    # ---- the import path --------------------------------------------------
    dict(name="accept an unresolvable card name as written",
         file="importer.py",
         find="    if options:\n        return None, f\"{name!r} is ambiguous",
         repl="    if False:\n        return None, f\"{name!r} is ambiguous",
         expect="ambiguous card name refuses"),
    dict(name="stop at the first bad name instead of reporting all of them",
         file="importer.py",
         find="            problems.append(why)\n            continue",
         repl="            raise ImportError_(why)",
         expect="every bad name is reported"),
    dict(name="file cards by the heading above them rather than their type",
         file="importer.py",
         find="        target = {cards.RUNE: runes, cards.BATTLEFIELD: battlefields}.get(kind, main)",
         repl="        target = main",
         expect="filed by type"),
    dict(name="read a trailing set code as part of the card name",
         file="importer.py",
         find="    line = _CODE.sub(\"\", line)",
         repl="    pass",
         expect="a well-formed pasted list imports at all"),
    dict(name="treat a bare section heading as a one-of card",
         file="importer.py",
         find="        if _SECTION.match(raw):\n            continue",
         repl="        if False:\n            continue",
         expect="a well-formed pasted list imports at all"),
    dict(name="import a list with no legend at all",
         file="importer.py",
         find="    if not found_legend:",
         repl="    if False:",
         expect="no legend is refused"),
    dict(name="pick a Chosen Champion when the list is genuinely ambiguous",
         file="importer.py",
         find="    if len(options) == 1:\n        return options[0], None",
         repl="    if options:\n        return options[0], None",
         expect="ambiguous Chosen Champion is left unset"),

    dict(name="import a deck with no record of when it arrived",
         file="importer.py",
         find='        "fetched": today or datetime.date.today().isoformat(),',
         repl='        "site2": "x",',
         expect="records its own provenance"),

    dict(name="let the move-cost guard be masked by exhaust()'s complaint",
         file="table.py",
         find='            raise RulesError(f"{perm.name} is exhausted and cannot pay its move cost (144.2)")',
         repl="            pass",
         expect="refused by the MOVE COST guard"),
    dict(name="drop the payment safety net behind can_pay",
         file="table.py",
         find='                raise RulesError(f"seat {seat} has no rune to produce {\'/\'.join(wanted)} Power")',
         repl="                pass",
         expect="still refuses when `can_pay` wrongly says yes"),

    # ---- minted identifiers -----------------------------------------------
    dict(name="trust the saved id counter instead of deriving it from the board",
         file="table.py",
         find="        t._next_id = max([t._next_id] + [_id_number(o.id) + 1 for o in t.permanents + t.runes])",
         repl="        pass",
         expect="derives the id counter past every id"),
    dict(name="hand out an id that is already in use",
         file="table.py",
         find="            if oid not in taken:\n                return oid",
         repl="            return oid",
         expect="minting skips an id already in use"),
    dict(name="let an import overwrite a different deck on the same slug",
         file="importer.py",
         find="        if existing and existing.get(\"name\") != deck[\"name\"]:",
         repl="        if False:",
         expect="refuses to overwrite a DIFFERENT deck"),

    # ---- the rules kernel (lib/engine) -----------------------------------
    #
    # The engine plays the game rather than holding it (ADR 0009), so its
    # failure mode is worse than the table's: a mis-implemented rule produces a
    # plausible finished game and a plausible win rate, with nothing to read
    # afterwards. Every kernel check below has been watched to go red.
    # One per engine module that has logic. Ten of sixteen carried none, which
    # is the same blind spot the battery exists to find: `combat.py` computed
    # every damage assignment in the game and `invariants.py` watched every
    # transition, and either could have been gutted with the suite still green.
    # Both of these mutate `assign_damage`'s own loop and leave the decision
    # path alone, so the games in the later sections still play legally. A
    # mutant that broke `next_amount` instead made the engine generate an
    # assignment its own validator refuses, and the suite died on a RulesError
    # before the check that names the defect had run — a crash, not a catch.
    dict(name="assign one point at a time instead of lethal in full (465.2.c.3)",
         file="engine/combat.py",
         find="        give = next_amount(s, defenders, assignment, target, pool)",
         repl="        give = 1",
         expect="lethal-first"),
    dict(name="call zero damage lethal for a 0-Might unit (142.4.b)",
         file="engine/combat.py",
         find="    if marked > 0 and marked >= might:",
         repl="    if marked >= might:",
         expect="0-Might unit needs a non-zero assignment"),
    dict(name="stop asserting that cards are conserved",
         file="engine/invariants.py",
         find="        if found != expected:",
         repl="        if False:",
         expect="appeared from nowhere"),
    dict(name="stop asserting that the Chain is LIFO",
         file="engine/invariants.py",
         find="        elif seen_pending:",
         repl="        elif False:",
         expect="finalized item sitting above a pending one"),
    dict(name="stop asserting that a won game gets noticed (472)",
         file="engine/invariants.py",
         find="        if not any(task[0] == \"cleanup\" for task in s.tasks):",
         repl="        if False:",
         expect="won game nothing is about to notice"),
    dict(name="let the golden comparison forgive a changed answer",
         file="engine/goldens.py",
         find="        if got != expected:\n            out.append(\"%s: decision %d differs",
         repl="        if False:\n            out.append(\"%s: decision %d differs",
         expect="names the decision whose ANSWER moved"),
    dict(name="let the golden comparison forgive a changed state",
         file="engine/goldens.py",
         find="            out.append(\"%s: the state diverges at decision %d (%s, golden %s) — a rule \"",
         repl="            pass\n            _unused = (\"%s: the state diverges at decision %d (%s, golden %s) — a rule \"",
         expect="a moved state hash means a rule changed"),
    dict(name="shuffle nothing, and call it a shuffle",
         file="engine/rng.py",
         find="    for i in range(len(items) - 1, 0, -1):",
         repl="    for i in range(0):",
         expect="a shuffle is a permutation"),
    dict(name="derive a seat's stream from the seed alone, not the seat",
         file="engine/rng.py",
         find='    return seed_from("%s/seat%d" % (seed, seat))',
         repl='    return seed_from("%s/seat" % (seed,))',
         expect="two seats draw from different streams"),
    dict(name="let an Option compare equal to anything",
         file="engine/decisions.py",
         find="        return self.key == getattr(other, \"key\", other)",
         repl="        return True",
         expect="answer refuses an option"),
    dict(name="make the content policy depend on how many questions came before",
         file="engine/policies.py",
         find="        key = repr((decision.seat, decision.kind, [o.key for o in decision.options]))",
         repl="        key = repr(id(decision))",
         expect="surfacing trivial decisions"),
    dict(name="move a canonical perft board somewhere else",
         file="engine/perft.py",
         find='"seed": 11, "first": 1, "advance": 24, "policy": 202,',
         repl='"seed": 11, "first": 1, "advance": 25, "policy": 202,',
         expect="perft matches the golden count from the midgame board"),
    dict(name="count a perft leaf twice at the depth bound",
         file="engine/perft.py",
         find="    decision = game.step()\n    if decision.terminal or depth <= 0:\n        return 1",
         repl="    decision = game.step()\n    if decision.terminal or depth <= 0:\n        return 2",
         expect="independent enumeration"),
    dict(name="hand the terminal decision a seat's hand (108.7.c)",
         file="engine/game.py",
         find="                return terminal(public_view(s))",
         repl="                return terminal(view(s, 0))",
         expect="the terminal decision carries no hand"),
    dict(name="open a staged Combat before a staged Showdown (323.12, 323.13)",
         file="engine/turn.py",
         find="        if showdowns:\n            _open_at(g, showdowns, combat=False)\n            return True\n        if combats:\n            _open_at(g, combats, combat=True)\n            return True",
         repl="        if combats:\n            _open_at(g, combats, combat=True)\n            return True\n        if showdowns:\n            _open_at(g, showdowns, combat=False)\n            return True",
         expect="before a staged Combat elsewhere"),
    dict(name="stop Holding once the Victory Score is passed (315.2.b.2)",
         file="engine/scoring.py",
         find="        if bf[\"ctrl\"] == seat and seat not in bf[\"scored\"]:\n            score(g, seat, bf[\"i\"], method=\"Hold\")",
         repl="        if bf[\"ctrl\"] == seat and seat not in bf[\"scored\"]:\n            if g.s.points[seat] >= g.s.victory_target:\n                return\n            score(g, seat, bf[\"i\"], method=\"Hold\")",
         expect="Holds EVERY battlefield"),
    dict(name="decide the win inside the Score instead of at the cleanup (472)",
         file="engine/scoring.py",
         find="    # No victory check here.",
         repl="    actions.check_victory(g, \"472\")\n    # No victory check here.",
         expect="the final point lands"),
    dict(name="shallow-copy the pending decision, so a clone shares its options",
         file="engine/state.py",
         find="    copy = dict(p)\n    copy[\"options\"] = list(p[\"options\"])\n    return copy",
         repl="    return dict(p)",
         expect="does not add an option to the original"),
    dict(name="shallow-copy the half-made choice, so a clone shares its list",
         file="engine/state.py",
         find="    for key, value in copy.items():\n        if isinstance(value, list):\n            copy[key] = value[:]",
         repl="    for key, value in copy.items():\n        if False:\n            copy[key] = value[:]",
         expect="shares no zone, object, chain item, task or log"),
    dict(name="determinize into the world the position is already holding",
         file="engine/game.py",
         find="        g = self.clone()\n        s = g.s\n        stream = rng.seed_from",
         repl="        g = self\n        s = g.s\n        stream = rng.seed_from",
         expect="shares no zone with the game it came from"),
    dict(name="credit a golden game that was never played",
         file="engine/goldens.py",
         find="        if not any(g[\"name\"] == name for g in fresh[\"games\"]):",
         repl="        if False:",
         expect="stopped being played"),

    dict(name="point an engine fixture at a deck the gauntlet no longer has",
         file="engine/fixtures.py",
         find='IRELIA = "irelia-core-meta"',
         repl='IRELIA = "a-tournament-list-that-was-deleted"',
         expect="is still in the gauntlet"),
    dict(name="drop the going-second extra rune (485.7)",
         file="engine/turn.py",
         find="        if seat != s.first_player and not s.second_channel_used:",
         repl="        if False:",
         expect="channels 3 on their first Channel Phase"),
    dict(name="resolve the Chain oldest-item-first, i.e. FIFO",
         file="engine/chain.py",
         find="    for i in range(len(s.chain) - 1, -1, -1):",
         repl="    for i in range(len(s.chain)):",
         expect="LIFO"),
    dict(name="skip the final-point rule and win a point early (471.1.b)",
         file="engine/scoring.py",
         find='    if method == "Conquer" and s.points[seat] >= target - 1:',
         repl="    if False:",
         expect="final point"),
    dict(name="iterate players by seat number instead of in turn order (303.2.a)",
         file="engine/state.py",
         find="        first = self.turn_player if start is None else start\n"
              "        return (first, 1 - first)",
         repl="        return (0, 1)",
         expect="exact mirror"),
    dict(name="place the battlefields by seat number, so a mirror renumbers them",
         file="engine/turn.py",
         find="    for seat in s.turn_order(s.first_player):\n"
              "        provided = g.decks[seat].battlefield_cards()",
         repl="    for seat in (0, 1):\n"
              "        provided = g.decks[seat].battlefield_cards()",
         expect="battlefield 0 belongs to the player going first"),
    dict(name="answer a two-option decision automatically as if it were forced",
         file="engine/game.py",
         find='                if self.auto_trivial and len(s.pending["options"]) == 1:',
         repl='                if self.auto_trivial and len(s.pending["options"]) <= 2:',
         expect="surfacing trivial decisions"),
    dict(name="let a unit enter the board ready (359.2.c)",
         file="engine/chain.py",
         find='        actions.put_into_play(g, seat, item["name"], item["loc"], True, "chain")',
         repl='        actions.put_into_play(g, seat, item["name"], item["loc"], False, "chain")',
         expect="enters the board exhausted"),
    dict(name="close a Showdown on a single pass (347.2.a)",
         file="engine/chain.py",
         find='    if sd["passes"] >= 2:',
         repl='    if sd["passes"] >= 1:',
         expect="one pass is not a sequence of passes"),
    dict(name="resolve a Chain item on the first pass (339.1)",
         file="engine/chain.py",
         find="    if s.passes >= 2:",
         repl="    if s.passes >= 1:",
         expect="one pass is not a sequence of passes"),
    dict(name="never apply Contested when a unit becomes present (190.3.a.1)",
         file="engine/actions.py",
         find='    if bf["ctrl"] != unit["ctrl"] and not bf["contested"]:',
         repl="    if False:",
         expect="contests it"),
    dict(name="leave units with lethal damage marked on the board (323.5)",
         file="engine/turn.py",
         find='        if unit["unit"] and unit["dmg"] > 0 and unit["dmg"] >= s.might_of(unit):',
         repl="        if False:",
         expect="leaves the board"),
    dict(name="do not recall repelled attackers (466.1.a.2)",
         file="engine/turn.py",
         find="    if attackers and defenders:                            # 3d",
         repl="    if False:",
         expect="attackers still present when defenders remain are recalled"),
    dict(name="allow a Standard Move from battlefield to battlefield (144.4.c)",
         file="engine/actions.py",
         find="    if origin_bf and dest_bf:",
         repl="    if False:",
         expect="Ganking"),
    dict(name="drop the guard that a move to where you already are is not a Move",
         file="engine/actions.py",
         find='    if destination == unit["loc"]:',
         repl="    if False:",
         expect="already stands is not a Move"),
    dict(name="allow a Standard Move from one base to the other (144.4)",
         file="engine/actions.py",
         find="    if not origin_bf and not dest_bf:",
         repl="    if False:",
         expect="base -> base"),
    dict(name="leave the hands out of the state hash",
         file="engine/state.py",
         find="            tuple(tuple(z) for z in self.hand),",
         repl="",
         expect="golden playthrough"),
    dict(name="accept an answer the decision never offered",
         file="engine/game.py",
         find="        option = decision.find(choice)\n        if option is None:",
         repl="        option = decision.find(choice) or decision.options[0]\n"
              "        if option is None:",
         expect="answer refuses an option"),
    dict(name="lose a resolved spell instead of trashing it (351.2)",
         file="engine/chain.py",
         find='        s.trash[seat].append(item["name"])',
         repl="        pass",
         expect="trash"),
    dict(name="determinize without redealing the opponent's hand",
         file="engine/game.py",
         find="        stream = rng.shuffle(stream, pool)",
         repl="        pool.sort()",
         expect="two seeds give two different worlds"),
    dict(name="leave Priority behind when a Showdown closes (313.5)",
         file="engine/chain.py",
         find="    s.priority = None\n    if len(seats) == 1:",
         repl="    if len(seats) == 1:",
         expect="nobody is left holding Priority"),
    dict(name="skip the Scoring Step of the Beginning Phase (315.2.b)",
         file="engine/turn.py",
         find="        scoring.hold_all(g, seat)",
         repl="        pass",
         expect="Holds every battlefield they control"),
    # ---- the action layer ------------------------------------------------
    dict(name="split an action script on ; without respecting quotes",
         file="deck_cli.py",
         find='    lex = shlex.shlex(script, posix=True, punctuation_chars=";")',
         repl='    lex = shlex.shlex(script.replace(";", " ; "), posix=True)',
         expect="without cutting inside quotes"),

    # ---- the gauntlet's identity -----------------------------------------
    # A result is a number against a particular field. Every defect below leaves
    # the games playing correctly and the number still printed — it just stops
    # meaning what the reader takes it to mean, which is the failure mode a
    # measuring instrument has.
    dict(name="date the gauntlet instead of naming a version",
         file="deckfile.py",
         find='            return fh.read().strip() or "unversioned"',
         repl='            return "2026-09-11"',
         expect="versioned, not merely dated"),
    dict(name="compute the gauntlet version but never print it",
         file="deck_cli.py",
         find='    print(f"{deckfile.gauntlet_version()} ({deckfile.gauntlet_digest()}) — "',
         repl='    print(f"({deckfile.gauntlet_digest()}) — "',
         expect="prints the version it is measuring against"),
    dict(name="report the whole deck folder as the size of the field",
         file="deck_cli.py",
         find="{len(gauntlet)} list(s), ",
         repl="{len(deckfile.available())} list(s), ",
         expect="prints how many lists the field holds"),
    dict(name="print the whole card pool as the scripting frontier",
         file="deck_cli.py",
         find='          f"{len(deckfile.distinct_cards(gauntlet))} distinct cards\\n")',
         repl='          f"{len(cards.pool())} distinct cards\\n")',
         expect="prints the distinct-card count"),
    dict(name="count card spellings rather than cards in the frontier",
         file="deckfile.py",
         find="        for name, _ in deck.main + deck.runes + deck.battlefields:\n            names.add(canonical(name))",
         repl="        for name, _ in deck.main + deck.runes + deck.battlefields:\n            names.add(name)",
         expect="two spellings of one card count once"),
    dict(name="leave the legend and Chosen Champion out of the frontier",
         file="deckfile.py",
         find="        for name in [deck.legend, deck.chosen_champion]:",
         repl="        for name in []:",
         expect="legend and the Chosen Champion are inside the frontier"),
    dict(name="count the decks under construction as part of the gauntlet",
         file="deckfile.py",
         find='    return sorted(glob.glob(os.path.join(GAUNTLET_DIR, "*.json")))',
         repl="    return available()",
         expect="only gauntlet/, never the decks you are building"),
    dict(name="let an unreadable version file take the whole command down",
         file="deckfile.py",
         find='    except OSError:\n        return "unversioned"',
         repl='    except ValueError:\n        return "unversioned"',
         expect="reports one rather than crashing"),
    dict(name="name the field but never fingerprint it",
         file="deck_cli.py",
         find='    print(f"{deckfile.gauntlet_version()} ({deckfile.gauntlet_digest()}) — "',
         repl='    print(f"{deckfile.gauntlet_version()} — "',
         expect="prints a fingerprint of the field"),
    dict(name="fingerprint the file names and ignore what is in them",
         file="deckfile.py",
         find='        entries.append(f"{slug}::{composition_key(deck)}")',
         repl='        entries.append(slug)',
         expect="follows the contents, not the file names alone"),
    # ---- combat, scoring and the designations (issue #23) ----------------
    #
    # Combat is where the games are decided, so these are the mutants that
    # matter most: every one of them leaves a plausible finished game behind.
    dict(name="never designate the units at the battlefield (464.2.c.3)",
         file="engine/combat.py",
         find="    if s.combat_attacker is None or s.showdown is None:\n        return False",
         repl="    if True:\n        return False",
         expect="takes its controller's designation"),
    dict(name="read a combat's sides by designation OR none at all (465.2.a-b)",
         file="engine/combat.py",
         find='and u["role"] == "attacker"]',
         repl='and u["role"] is not None]',
         expect="read by designation, not by side"),
    dict(name="stop designating units that arrive mid-combat (323.2.a)",
         file="engine/turn.py",
         find="    from . import combat as _combat\n    if _combat.apply_designations(g):",
         repl="    from . import combat as _combat\n    if False and _combat.apply_designations(g):",
         expect="gives it its controller's designation"),
    dict(name="leave a designation on a unit that has left the battlefield (323.2.c)",
         file="engine/combat.py",
         find='            want = None                                # 323.2.c',
         repl='            want = unit["role"]                        # 323.2.c',
         expect="loses its designation (323.2.c)"),
    dict(name="end combat without removing the designations (466.7.a)",
         file="engine/combat.py",
         find='    for unit in s.units:\n        unit["role"] = None\n    s.combat_attacker = None',
         repl="    s.combat_attacker = None",
         expect="removing the designation from every unit and player"),
    dict(name="stop asserting that the designations agree with 323.2",
         file="engine/invariants.py",
         find="    _designations(game, bad)",
         repl="    _designations(game, bad) if False else None",
         expect="names a unit 323.2 should have designated"),
    dict(name="assign the whole pool to whichever unit is chosen (465.2.c.4)",
         file="engine/combat.py",
         find="        give = next_amount(s, defenders, assignment, target, pool)",
         repl="        give = pool",
         expect="excess lands only once every defender has its lethal"),
    dict(name="offer only the engine's own choice, so there is no decision (465.2.c)",
         file="engine/combat.py",
         find="    options = []\n    for unit in targets:",
         repl="    options = []\n    for unit in targets[:1]:",
         expect="is a decision when more than one unit can take it"),
    dict(name="order the assignment options the other way round (465.2.c.7)",
         file="engine/combat.py",
         find="    for unit in targets:\n        amount = next_amount(",
         repl="    for unit in reversed(targets):\n        amount = next_amount(",
         expect="the first option is the engine's own lethal-first assignment"),
    dict(name="take an assignment without checking it obeys 465.2.c (465.2.c.6)",
         file="engine/combat.py",
         find='        refuse_illegal(s, attackers, defenders, dict(c["onto"]))\n        c["first"]',
         repl='        c["first"]',
         expect="an assignment built outside the option list is still refused"),
    dict(name="let an assignment stop early with damage left to give (465.2.c)",
         file="engine/combat.py",
         find="    if total < pool and pending_targets(s, defenders, {}):",
         repl="    if False:",
         expect="leaving damage unassigned while a unit could take it is refused"),
    dict(name="let two units both be left short of lethal (465.2.c.3)",
         file="engine/combat.py",
         find="    if len(short) > 1:",
         repl="    if False:",
         expect="two units left short of lethal is refused"),
    dict(name="let the excess pile up while a unit is untouched (465.2.c.4)",
         file="engine/combat.py",
         find="    if over and (short or untouched):",
         repl="    if False:",
         expect="piling the excess on one unit while another is untouched is refused"),
    dict(name="ignore Tank when choosing what may be assigned damage (815.1.c.2)",
         file="engine/combat.py",
         find='    if unit["tank"]:\n        return 0',
         repl="    if False:\n        return 0",
         expect="only legal assignment until it has its lethal"),
    dict(name="offer every pending unit, whatever priority it is bound by",
         file="engine/combat.py",
         find='    return [u for u in pending if priority(u) == first]',
         repl="    return pending",
         expect="the plain units become legal"),
    # The refusal itself comes from the option list now, so these two mutate the
    # part that is still hand-written: which rule the message names. A refusal
    # that cites the wrong rule sends a reader to the wrong paragraph.
    dict(name="name a jumped Tank as a Backline violation (815.1.c.2)",
         file="engine/combat.py",
         find='            rule = ("815.1.c.2" if any(v["tank"] for v in live',
         repl='            rule = ("826.4.b" if any(v["tank"] for v in live',
         expect="jumping a Tank is refused"),
    dict(name="name a jumped Backline unit as a Tank violation (826.4.b)",
         file="engine/combat.py",
         find='                                       if v["id"] in jumped) else "826.4.b")',
         repl='                                       if v["id"] in jumped) else "815.1.c.2")',
         expect="assigning to Backline before the rest is refused"),
    dict(name="apply Assault whatever the unit is designated (807.1.d)",
         file="engine/state.py",
         find='        if unit["role"] == "attacker":\n            might += unit["assault"]',
         repl='        if True:\n            might += unit["assault"]',
         expect="Assault adds Might only while the unit is an attacker"),
    dict(name="never apply Shield (814.1.c)",
         file="engine/state.py",
         find='        elif unit["role"] == "defender":\n            might += unit["shield"]',
         repl='        elif False:\n            might += unit["shield"]',
         expect="Shield adds Might only while the unit is a defender"),
    dict(name="call a unit Mighty at 4 Might (708)",
         file="engine/state.py",
         find="        return self.might_of(unit) >= 5",
         repl="        return self.might_of(unit) >= 4",
         expect="a unit below 5 Might is not Mighty"),
    dict(name="let Bonus Damage go negative and reduce the assignment (714.2)",
         file="engine/combat.py",
         find='    return max(sum(u["bonus"] for u in units), 0)',
         repl='    return sum(u["bonus"] for u in units)',
         expect="no bonus at all, not a reduction"),
    dict(name="leave Bonus Damage out of what a side assigns (715)",
         file="engine/combat.py",
         find="    return sum(s.might_of(u) for u in units) + bonus_damage(units)",
         repl="    return sum(s.might_of(u) for u in units)",
         expect="summed and applied once"),
    dict(name="charge Deflect to the controller of the deflecting unit (809.1.c)",
         file="engine/actions.py",
         find='    if seat == obj["ctrl"]:\n        return 0',
         repl="    if False:\n        return 0",
         expect="costs its own controller nothing"),
    dict(name="run the Damage Step with one side already gone (465.1)",
         file="engine/combat.py",
         find='    if not attackers or not defenders:\n        g.note("no damage at %s',
         repl='    if False:\n        g.note("no damage at %s',
         expect="skips the Damage Step (465.1)"),
    dict(name="keep the Tasks the Combat Showdown Step left outstanding (465.3)",
         file="engine/combat.py",
         find="    if dropped:\n        s.tasks = keep",
         repl="    if False:\n        s.tasks = keep",
         expect="cancels the Tasks the Showdown left outstanding"),
    dict(name="let the Resolution Step's window run once and give up (466.2)",
         file="engine/combat.py",
         find='    s.tasks.insert(0, ("combat_fepr", index))\n    chain.fepr_step(g)',
         repl="    chain.fepr_step(g)",
         expect="re-queues itself while the Chain has something on it"),
    dict(name="skip the Combat Cleanup's healing and attacker recall (466.1.a)",
         file="engine/turn.py",
         find='    """466.1.a: "3c. Heal all Units" and "3d. Recall Attackers ... if Defenders\n    are still present"."""',
         repl='    """466.1.a, deleted."""\n    return False',
         expect="agree on the shared subset"),
    dict(name="hard-code the Victory Score at 8, ignoring what is in force (485.3)",
         file="engine/actions.py",
         find="    eligible = [seat for seat in (0, 1) if s.points[seat] >= s.victory_target]",
         repl="    eligible = [seat for seat in (0, 1) if s.points[seat] >= 8]",
         expect="a raised Victory Score is respected"),
    dict(name="keep the rune pools over the turn boundary (317.2.e)",
         file="engine/turn.py",
         find="        if s.energy[seat] or s.power[seat]:\n            actions.empty_pool(g, seat)",
         repl="        if False:\n            actions.empty_pool(g, seat)",
         expect="unspent Energy is lost at the end of the turn"),
    dict(name="send a recycled rune to the Main Deck (161.2.b)",
         file="engine/actions.py",
         find='    s.rune_deck[seat].append(rune["name"])',
         repl='    s.main_deck[seat].append(rune["name"])',
         expect="returns to the Rune Deck, not the Main Deck"),
    dict(name="require a READIED rune to pay a Power cost (164.2.b)",
         file="engine/actions.py",
         find='    spent_runes = matching([r for r in mine if r["exh"]])',
         repl="    spent_runes = []",
         expect="Power can be recycled from an EXHAUSTED rune"),
    dict(name="keep the set-aside cards in hand through the mulligan (117.1)",
         file="engine/turn.py",
         find="    for name in aside:\n        s.hand[seat].remove(name)",
         repl="    for name in aside:\n        pass",
         expect="redraws to the same hand size"),
    dict(name="leave a field out of what the parity harness compares",
         file="engine/parity.py",
         find='        "points": list(s.points),',
         repl="",
         expect="compares points, zones, units, runes and battlefields"),
    dict(name="leave a table check out of the ported map",
         file="engine/ported.py",
         find='    "scoring gains a point": "a Score gains a point (468.1)",',
         repl="",
         expect="is classified: ported, shared or not applicable"),
    dict(name="claim a ported check the engine does not have",
         file="engine/ported.py",
         find='    "a Hold outside the Beginning Phase is refused (469.2)":\n        "a Hold is refused outside the Beginning Phase (469.2)",',
         repl='    "a Hold outside the Beginning Phase is refused (469.2)":\n        "a Hold is refused somewhere (469.2)",',
         expect="names an engine check that ran, by its exact name"),

    # ---- the review of #59: every fix above has one of these ------------
    dict(name="let the validator accept anything the option list did not produce",
         file="engine/combat.py",
         find="        if tuple(sorted(assignment.items())) in legal:\n            return []",
         repl="        if legal:\n            return []",
         expect="accepts exactly the assignments the option list generates"),
    dict(name="call the pool spent once every unit is lethal, however much is left",
         file="engine/combat.py",
         find="    if total < pool and pending_targets(s, defenders, {}):",
         repl="    if total < pool and pending_targets(s, defenders, assignment):",
         expect="stopping early once every unit happens to be lethal"),
    dict(name="skip the Combat Cleanup's heal, leaving damage on a survivor (466.1.a.1)",
         file="engine/turn.py",
         find='    for unit in s.units:                                   # 3c\n        if unit["unit"] and unit["dmg"]:',
         repl="    for unit in s.units:                                   # 3c\n        if False:",
         expect="heals every unit before the result is determined"),
    dict(name="let a Backline unit be assigned damage first (826.4.b)",
         file="engine/combat.py",
         find='    if unit["backline"]:\n        return 2',
         repl="    if False:\n        return 2",
         expect="not a legal assignment while another unit can take damage"),
    dict(name="leave a Backline unit with no legal assignment at all (826.4.b)",
         file="engine/combat.py",
         find="    first = min(priority(u) for u in pending)",
         repl="    first = 1",
         expect="becomes one once nothing else can"),
    dict(name="let Backline beat Tank on a unit that has both (465.2.c.8)",
         file="engine/combat.py",
         find='    if unit["tank"]:\n        return 0\n    if unit["backline"]:\n        return 2',
         repl='    if unit["backline"]:\n        return 2\n    if unit["tank"]:\n        return 0',
         expect="with both Tank and Backline is assigned as a Tank"),
    dict(name="kill a 0-Might unit that was never assigned damage (142.4.b, 323.5)",
         file="engine/turn.py",
         find='        if unit["unit"] and unit["dmg"] > 0 and unit["dmg"] >= s.might_of(unit):',
         repl='        if unit["unit"] and unit["dmg"] >= s.might_of(unit):',
         expect="assigning nothing at all leaves it alive"),
    dict(name="stand down from 466.5 whenever 323.8 has re-marked a Showdown",
         file="engine/combat.py",
         find="    if restaged(s, index):\n        return\n    if len(seats) == 1:",
         repl='    if bf["sd_staged"] or bf["cb_staged"]:\n        return\n    if len(seats) == 1:',
         expect="winning a combat establishes control and Conquers"),
    dict(name="compare only the Attacker's damage assignment in the parity harness",
         file="engine/parity.py",
         find='            side = (c["bf"], c["by"])',
         repl='            side = (c["bf"], c["attacker"])',
         expect="BOTH sides' damage assignments"),
    dict(name="compare the two games only at the end, never mid-game",
         file="engine/parity.py",
         find='    return decision.kind == "main" or decision.terminal',
         repl="    return decision.terminal",
         expect="compares a state at every Main Phase decision"),

    dict(name="salt the fingerprint, so two reads of one folder disagree",
         file="deckfile.py",
         find='    payload = "\\n".join(sorted(entries))',
         repl='    payload = "\\n".join(sorted(entries)) + str(os.urandom(4))',
         expect="stable when nothing has changed"),

    # ---- the card-script DSL ---------------------------------------------
    #
    # A schema that accepts everything reports 100% valid and gives the
    # compiler's repair loop nothing to repair, so every mutant here loosens the
    # validator rather than breaking it: each one leaves the suite runnable and
    # the library "valid", and the named check is the only thing that notices.
    dict(name="accept a verb no census table contains",
         file="engine/dsl/schema.py",
         find='        w.add("unknown_atom", path, "no census atom named %r" % (name,),\n'
              '              token=name, expected=_active(table))\n'
              '        return False',
         repl="        return True",
         expect="a verb no census table contains is an unknown atom"),
    dict(name="treat a reserved census atom as part of the active vocabulary",
         file="engine/dsl/schema.py",
         find="    if not atom.active:",
         repl="    if False:",
         expect="a real census atom outside the active cut is reserved"),
    dict(name="let a node carry no citation",
         file="engine/dsl/schema.py",
         find="        if required:\n"
              '            w.add("missing_citation", "%s.cites" % path,',
         repl="        if False:\n"
              '            w.add("missing_citation", "%s.cites" % path,',
         expect="a node with no citation is refused"),
    dict(name="accept any well-formed citation, right rule or not",
         file="engine/dsl/schema.py",
         find="    if canonical not in heads:",
         repl="    if False:",
         expect="a well-formed citation to the wrong rule is still wrong"),
    dict(name="take a coverage mark's word for what the card says",
         file="engine/dsl/schema.py",
         find="        elif printed and not quotes_printed_text(text, printed):",
         repl="        elif False:",
         expect="a clause that is not a run of the printed text is refused"),
    dict(name="match a clause against the raw text, reminder text included",
         file="engine/dsl/schema.py",
         find="    text = _REMINDER.sub(\" \", _SYMBOL.sub(\" \", text or \"\"))",
         repl="    text = _SYMBOL.sub(\" \", text or \"\")",
         expect="reminder text is not a clause a script may claim"),
    dict(name="hash the whole script, tests and coverage marks included",
         file="engine/dsl/schema.py",
         find='BODY_FIELDS = ("schema", "card", "keywords", "abilities")',
         repl='BODY_FIELDS = ("schema", "card", "keywords", "abilities", "tests", "clauses")',
         expect="does NOT change the version"),
    dict(name="stop checking that a version matches its body",
         file="engine/dsl/schema.py",
         find='        if doc["version"] != want:',
         repl="        if False:",
         expect="a version that is not the hash of the body is refused"),
    dict(name="build the keyword table by scanning brackets, inventing Mighty",
         file="engine/dsl/schema.py",
         find="    if name in NOT_KEYWORDS:",
         repl="    if False:",
         expect="Mighty in a keyword slot is refused"),
    dict(name="let a trigger leave out who it listens to (383.4.d.2)",
         file="engine/dsl/schema.py",
         find='    if "who" not in value:',
         repl="    if False:",
         expect="a trigger must say WHO it listens to"),
    dict(name="allow a cost reduction with no floor",
         file="engine/dsl/schema.py",
         find='    if name == "modify_cost" and node.get("delta", 0) < 0 and "min" not in node:',
         repl="    if False:",
         expect="a cost reduction with no floor is refused"),
    dict(name="let a choice leave the targeting question to be inferred (355.10)",
         file="engine/dsl/schema.py",
         find='    if name == "choose_object" and "targets" not in node:',
         repl="    if False:",
         expect="a choice must say whether what it chooses is a Target"),
    dict(name="ignore fields the schema does not define",
         file="engine/dsl/schema.py",
         find='    allowed = set(spec["req"]) | set(spec["opt"]) | {"kind", "cites", "note", "id",\n'
              '                                                     "gate", "when"}',
         repl='    allowed = set(spec["req"]) | set(spec["opt"]) | {"kind", "cites", "note", "id",\n'
              '                                                     "gate", "when"} | set(node)',
         expect="a field the schema does not define is refused"),
    dict(name="leave a reserved atom writable through a zone field",
         file="engine/dsl/schema.py",
         find='ZONES = ("hand", "trash", "deck", "top_of_deck", "champion")',
         repl='ZONES = ("hand", "trash", "deck", "top_of_deck", "champion", "banishment")',
         expect="every value a script may write is an active atom"),
    dict(name="point a keyword's trigger at an event the vocabulary does not have",
         file="engine/dsl/schema.py",
         find='    "Quick-Draw": ("play_self",),',
         repl='    "Quick-Draw": ("draw_trigger",),',
         expect="every event a keyword triggers on is active"),
    dict(name="promote an atom without saying which construct needed it",
         file="engine/dsl/schema.py",
         find='    "primitive:attach": "[Equip] (CR 818, 19) and [Quick-Draw] (CR 819, 3) perform it",',
         repl='    "primitive:attach": "",',
         expect="every promoted atom says which active construct needed it"),
    dict(name="let a clause point at a node that is not there",
         file="engine/dsl/schema.py",
         find='        if node and node not in w.node_paths:',
         repl="        if False:",
         expect="a clause cannot be implemented by a node that is not there"),
    dict(name="accept a script with one scenario test",
         file="engine/dsl/schema.py",
         find="    if not 2 <= len(tests) <= 4:",
         repl="    if False:",
         expect="fewer than two scenario tests is refused"),
    dict(name="let a script live in a file named after something else",
         file="engine/dsl/library.py",
         find="    if want and want != got:",
         repl="    if False:",
         expect="a script must live in the file named after its card"),
    dict(name="report clause coverage over implemented clauses only",
         file="engine/dsl/library.py",
         find='        "clause_coverage": (marks["implemented"] / total_clauses) if total_clauses else 0.0,',
         repl='        "clause_coverage": 1.0 if marks["implemented"] else 0.0,',
         expect="an unsupported clause LOWERS coverage"),
    dict(name="score atom coverage against the atoms the scripts happened to use",
         file="engine/dsl/library.py",
         find='        "atoms_exercised": len(active & exercised),',
         repl='        "atoms_exercised": len(active),',
         expect="the coverage report counts against the vocabulary"),
    dict(name="leave the legend and Chosen Champion out of engine readiness",
         file="engine/dsl/library.py",
         find="    names = sorted(deckfile.distinct_cards([deck]))",
         repl="    names = sorted(n for n, _ in deck.main + deck.runes + deck.battlefields)",
         expect="scripted and unscripted partition the deck exactly"),
    dict(name="freeze the vocabulary at 34 primitives by activating a reserved one",
         file="engine/dsl/schema.py",
         find='    ("hide",         "CR:421",  3,   8, False),',
         repl='    ("hide",         "CR:421",  3,   8, True),',
         expect="the active vocabulary has the 33 effect primitives"),
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
        # The separator is exactly the one `check()` prints — two spaces, an em
        # dash, a space — and nothing looser. `\s+—` also matched a single
        # space before an em dash INSIDE a name, so any check whose name
        # contained one was recorded truncated, never matched on the way back,
        # and silently lost its credit for good.
        failed = re.findall(r"^\s*\[FAIL\]\s*(.+?)(?:  — .*)?$", r.stdout, re.M)
        if failed:
            return failed, None
        if r.returncode != 0:
            last = [x for x in r.stderr.strip().splitlines() if x.strip()]
            return ["<suite crashed> " + (last[-1] if last else "no output")], None
        return [], None


PROVEN = os.path.join(HERE, "proven-checks.json")


def write_proven(reddened):
    """Record the checks this run actually watched go red.

    The ratio printed by `selftest` used to be derived by matching each mutant's
    `expect` string against check names. That counts what a mutant CLAIMS, not
    what has been seen — and a claim can be false for a long time: a whole check
    group can sit un-run inside the battery while every mutant naming it reports
    caught. Only the battery knows, because only the battery removes things.

    So the battery writes down what it saw, and `selftest` reads it. Names that
    no longer exist are dropped on read rather than here, so an edited check
    lowers the ratio instead of quietly keeping its old credit.
    """
    payload = {
        "mutants": len(MUTANTS),
        "observed_to_fail": sorted(reddened),
    }
    with open(PROVEN, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    print(f"recorded {len(reddened)} checks observed to fail -> {os.path.basename(PROVEN)}")


def preflight():
    """Does the suite run the SAME checks inside the battery's copy?

    The copy omits `reports`, `games` and caches. Any check that reads a fixture
    from one of those — rather than constructing what it needs — silently does
    not run here, and every mutant that check exists to catch then walks past a
    green suite reporting itself caught. A skipped group is not a failure, so
    nothing says so, and hand-verification cannot find it because the fixture is
    sitting right there on the author's disk. Only this comparison can, because
    only this copy takes the fixture away.

    Costs one extra suite run per battery, once, not per mutant.
    """
    def count(cwd):
        r = subprocess.run([sys.executable, os.path.join(cwd, "selftest.py")],
                           capture_output=True, text=True, cwd=cwd)
        m = re.search(r"(\d+)/(\d+) passed", r.stdout)
        return int(m.group(2)) if m else -1

    here = count(HERE)
    with tempfile.TemporaryDirectory() as tmp:
        skill = os.path.join(tmp, "deck-lab")
        shutil.copytree(SKILL, skill, ignore=shutil.ignore_patterns(
            "reports", "games", "__pycache__", "*.tmp"))
        there = count(os.path.join(skill, "lib"))
    if here != there:
        print(f"  PREFLIGHT FAILED: {here} checks run normally, {there} inside the "
              "battery's copy.\n  Some check reads a fixture the copy omits, so it "
              "is invisible to every mutant\n  below. Construct what it needs "
              "instead of reading a directory.")
        return False
    print(f"  preflight: {here} checks run in both environments\n")
    return True


def main():
    print("mutation battery — reintroducing defects the suite claims to catch\n")
    if not preflight():
        return 1
    survived, stale, crashed_only, misnamed = [], [], [], []
    caught = 0
    reddened = set()   # checks OBSERVED to fail, not merely claimed
    for i, m in enumerate(MUTANTS, 1):
        failures, err = run_one(m)
        if err:
            stale.append((m["name"], err))
            print(f"  [STALE]    {i:2}. {m['name']}\n              {err}")
            continue
        crashes = [f for f in failures if f.startswith("<suite crashed>")]
        named = [f for f in failures if not f.startswith("<suite crashed>")]
        reddened.update(named)
        # Credit only a NAMED check. A traceback that happens to contain the
        # expected words is the suite dying, not the suite detecting.
        hit = [f for f in named if m["expect"].lower() in f.lower()]
        if hit:
            caught += 1
            print(f"  [caught]   {i:2}. {m['name']}\n              → {hit[0]}")
        elif named:
            # NOT caught. Something went red, but not the check this mutant
            # claims to prove — so that check is still one nobody has watched
            # fail, and recording it as proven is exactly the stale credit this
            # battery exists to prevent. A mutant either names what it proves or
            # it is not evidence.
            misnamed.append((m["name"], m["expect"], named[0]))
            print(f"  [MISNAMED] {i:2}. {m['name']}\n              → {named[0]}"
                  f"\n              but it claims to prove a check naming "
                  f"{m['expect']!r}, which stayed green")
        elif crashes:
            crashed_only.append((m["name"], crashes[0]))
            print(f"  [CRASH]    {i:2}. {m['name']}\n              {crashes[0]}")
        else:
            survived.append(m)
            print(f"  [SURVIVED] {i:2}. {m['name']}\n              nothing failed — "
                  f"no check covers this")

    print(f"\n{caught}/{len(MUTANTS)} mutants caught")
    write_proven(reddened)
    if crashed_only:
        print(f"\n{len(crashed_only)} mutant(s) only crashed the suite rather than "
              "failing a named check:")
        for name, why in crashed_only:
            print(f"  - {name}\n      {why}")
    if misnamed:
        print(f"\n{len(misnamed)} mutant(s) caught by a check OTHER than the one they "
              "name. Point `expect` at\nthe check that actually reddens, or tighten the "
              "mutant until the named one does:")
        for name, expect, got in misnamed:
            print(f"  - {name}\n      claims {expect!r}\n      got    {got!r}")
    if stale:
        print(f"\n{len(stale)} STALE anchor(s) — the mutant no longer matches the source:")
        for name, why in stale:
            print(f"  - {name}\n      {why}")
    if survived:
        print(f"\n{len(survived)} SURVIVED — each is a behaviour with no check behind it:")
        for m in survived:
            print(f"  - {m['name']}  ({m['file']}, expected {m['expect']!r})")
        return 1
    return 1 if (stale or crashed_only or misnamed) else 0


if __name__ == "__main__":
    sys.exit(main())

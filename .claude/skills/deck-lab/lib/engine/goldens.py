"""Golden playthroughs and golden perft counts, and how to regenerate them.

A golden game is the primary test artifact this kernel has: a deck pair, a seed,
a policy seed, and then every decision the engine asked, every answer it was
given, the state hash after each one, and the whole log. Replaying it asserts
far more than a final score — it asserts that the engine asked the SAME
QUESTIONS in the same order, which is where a rules change actually shows up.

Two kinds of mismatch, told apart on purpose:

* a **state** mismatch (a step hash moved) means the rules changed;
* a **log** mismatch with the hashes intact means only the wording moved.

The second is usually deliberate and the message says so, instead of sending
someone to look for a rules bug in a reworded sentence.

Regenerate with `python3 deck_cli.py engine golden --write`, read the diff, and
commit the result in the same commit as the change that moved it.
"""
import json
import os

from . import fixtures, perft, policies
from .game import Game

HERE = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(HERE, "goldens")
PLAYTHROUGHS = os.path.join(DIR, "playthroughs.json")
PERFT = os.path.join(DIR, "perft.json")

#: Three games, chosen to cover the shapes a vanilla game can take: one that
#: ends on the Victory Score, one that runs long enough to fight over both
#: battlefields, and one seated the other way round.
GAMES = [
    {"name": "irelia-vs-viktor-s7",
     "a": fixtures.IRELIA, "b": fixtures.VIKTOR,
     "seed": 7, "first": 0, "policy": "g7"},
    {"name": "viktor-vs-irelia-s7-swapped",
     "a": fixtures.VIKTOR, "b": fixtures.IRELIA,
     "seed": 7, "first": 1, "policy": "g7"},
    {"name": "viktor-vs-kennen-s23",
     "a": fixtures.VIKTOR, "b": fixtures.KENNEN,
     "seed": 23, "first": 0, "policy": "g23"},
]

#: Depths frozen in the golden file. The selftest checks the first four (a
#: quarter of a second); `deck_cli.py engine perft` checks all of them.
PERFT_DEPTH = 6
SELFTEST_PERFT_DEPTH = 4


def play_golden(spec, invariants=True):
    """Play one golden game and return the record of it."""
    game = Game.new(fixtures.deck(spec["a"]), fixtures.deck(spec["b"]),
                    seed=spec["seed"], first=spec["first"],
                    hash_log=True, invariants=invariants)
    pol = policies.random_pair(spec["policy"])
    answers, hashes = [], []
    for _ in range(100000):
        decision = game.step()
        if decision.terminal:
            break
        hashes.append(game.state_hash())
        option = pol[decision.seat](decision)
        answers.append([decision.seat, decision.kind, list(option.key)])
        game.answer(option)
    else:
        raise AssertionError("%s never ended" % spec["name"])
    return {
        "name": spec["name"],
        "spec": {k: spec[k] for k in ("a", "b", "seed", "first", "policy")},
        "answers": answers,
        "step_hashes": hashes,
        "summary": game.summary(),
        "log": [e["text"] for e in game.log],
    }


def record_all():
    return {
        "note": "regenerate with `python3 deck_cli.py engine golden --write`",
        "games": [play_golden(spec) for spec in GAMES],
    }


def record_perft(depth=PERFT_DEPTH):
    return {
        "note": "legal-action perft; regenerate with `engine perft --write`",
        "depth": depth,
        "boards": dict((name, perft.counts(name, depth)) for name in sorted(perft.BOARDS)),
    }


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def write(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    return path


def compare(fresh, golden):
    """The first thing that differs, said in the terms a maintainer can act on."""
    problems = []
    by_name = dict((g["name"], g) for g in golden.get("games", []))
    for game in fresh["games"]:
        want = by_name.get(game["name"])
        if want is None:
            problems.append("%s: no golden recorded for this game" % game["name"])
            continue
        problems.extend(_compare_one(game, want))
    for name in by_name:
        if not any(g["name"] == name for g in fresh["games"]):
            problems.append("%s: a golden exists for a game that is no longer played"
                            % name)
    return problems


def _compare_one(game, want):
    name = game["name"]
    out = []
    for i, (got, expected) in enumerate(zip(game["answers"], want["answers"])):
        if got != expected:
            out.append("%s: decision %d differs — the engine asked seat %s a %s and was "
                       "answered %r, the golden has seat %s / %s / %r"
                       % (name, i, got[0], got[1], got[2],
                          expected[0], expected[1], expected[2]))
            break
    if len(game["answers"]) != len(want["answers"]):
        out.append("%s: %d decisions now, %d in the golden"
                   % (name, len(game["answers"]), len(want["answers"])))
    for i, (got, expected) in enumerate(zip(game["step_hashes"], want["step_hashes"])):
        if got != expected:
            out.append("%s: the state diverges at decision %d (%s, golden %s) — a rule "
                       "changed" % (name, i, got, expected))
            break
    if game["summary"] != want["summary"]:
        differing = sorted(k for k in game["summary"]
                           if game["summary"][k] != want["summary"].get(k))
        out.append("%s: the final summary differs in %s" % (name, ", ".join(differing)))
    if game["log"] != want["log"] and not out:
        first = next((i for i, (a, b) in enumerate(zip(game["log"], want["log"]))
                      if a != b), min(len(game["log"]), len(want["log"])))
        out.append("%s: the state is identical but the LOG changed at entry %d — this is "
                   "wording, not rules:\n      now:    %s\n      golden: %s"
                   % (name, first,
                      game["log"][first] if first < len(game["log"]) else "<end>",
                      want["log"][first] if first < len(want["log"]) else "<end>"))
    return out

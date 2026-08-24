"""Saving and restoring a game.

A game runs across many commands and often many sittings. Keeping the table in
a file rather than in a variable is what makes that possible, and it is also
what makes a game auditable afterwards: the log is append-only, so a result can
always be traced back to the moves that produced it.
"""
import json
import os
import re

import deckfile
import table

HERE = os.path.dirname(os.path.abspath(__file__))
GAMES_DIR = os.path.join(os.path.dirname(HERE), "games")
CURRENT = os.path.join(GAMES_DIR, ".current")


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "game"


def path_for(name):
    return os.path.join(GAMES_DIR, f"{slug(name)}.json")


def save(t, name, deck_refs):
    os.makedirs(GAMES_DIR, exist_ok=True)
    payload = {"name": name, "decks": deck_refs, "table": t.as_dict()}
    with open(path_for(name), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, ensure_ascii=False)
    with open(CURRENT, "w", encoding="utf-8") as fh:
        fh.write(name)
    return path_for(name)


def load(name=None):
    """The named game, or the one most recently touched."""
    if name is None:
        if not os.path.exists(CURRENT):
            raise FileNotFoundError("no current game — start one with `new`")
        with open(CURRENT, encoding="utf-8") as fh:
            name = fh.read().strip()
    path = path_for(name)
    if not os.path.exists(path):
        raise FileNotFoundError(f"no saved game {name!r} at {path}")
    with open(path, encoding="utf-8") as fh:
        payload = json.load(fh)
    decks = [deckfile.resolve(ref) for ref in payload["decks"]]
    t = table.Table.from_dict(payload["table"], decks)
    return payload["name"], t, payload["decks"]


def games():
    if not os.path.isdir(GAMES_DIR):
        return []
    return sorted(
        f[:-5] for f in os.listdir(GAMES_DIR) if f.endswith(".json")
    )

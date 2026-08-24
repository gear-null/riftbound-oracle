"""What actually happened in the games that were played.

Deck math is cheap and can be run at a hundred thousand shuffles. Played games
are not: every decision in one costs a reasoning step, so a matchup is measured
in tens of games, not hundreds. That makes the record of them worth keeping
across sessions rather than recomputing, and it makes stating `n` next to every
number non-negotiable — a 3-1 is not a 75% win rate.
"""
import json
import math
import os
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
JOURNAL = os.path.join(os.path.dirname(HERE), "games", "journal.jsonl")


def record(entry):
    os.makedirs(os.path.dirname(JOURNAL), exist_ok=True)
    with open(JOURNAL, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def entries(deck=None):
    if not os.path.exists(JOURNAL):
        return []
    out = []
    with open(JOURNAL, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if deck is None or deck in (row.get("deck"), row.get("opponent")):
                out.append(row)
    return out


def wilson(wins, n, z=1.96):
    """A 95% interval that stays honest at small n.

    A normal-approximation interval on 3 of 4 games spans past 100%, which reads
    as precision that is not there. Wilson does not, which is the whole reason
    to use it on samples this size.
    """
    if n == 0:
        return (0.0, 1.0)
    p = wins / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(centre - margin, 0.0), min(centre + margin, 1.0))


def matchups(deck):
    """Win/loss per opponent for one deck, from whichever seat it played."""
    table = defaultdict(lambda: {"games": 0, "wins": 0, "seeds": [], "notes": [],
                                 "mirror": False})
    mirrors = 0
    for row in entries(deck):
        # A mirror is 50% by construction: both seats are this deck, so one of
        # them always wins and `winner_deck == deck` is trivially true. Counting
        # it reported a 100% win rate against yourself.
        if row.get("deck") == deck and row.get("opponent") == deck:
            mirrors += 1
            continue
        if row.get("deck") == deck:
            opponent, won = row.get("opponent"), row.get("winner_deck") == deck
        elif row.get("opponent") == deck:
            opponent, won = row.get("deck"), row.get("winner_deck") == deck
        else:
            continue
        cell = table[opponent]
        cell["games"] += 1
        cell["wins"] += 1 if won else 0
        cell["seeds"].append(row.get("seed"))
        if row.get("note"):
            cell["notes"].append(row["note"])
    out = []
    if mirrors:
        out.append({
            "opponent": f"{deck} (mirror)", "games": mirrors, "wins": None,
            "rate": None, "low": None, "high": None, "seeds": [],
            "notes": ["a mirror is 50% by construction; excluded from the rates"],
        })
    for opponent, cell in sorted(table.items()):
        low, high = wilson(cell["wins"], cell["games"])
        out.append({
            "opponent": opponent,
            "games": cell["games"],
            "wins": cell["wins"],
            "rate": cell["wins"] / cell["games"] if cell["games"] else None,
            "low": low,
            "high": high,
            "seeds": cell["seeds"],
            "notes": cell["notes"],
        })
    return out

"""The rules kernel: code plays the game, through a decision-request API.

The table (`../table.py`) holds a game while a reader plays it. This plays it:
the engine runs the rules until a choice is actually needed, hands out the
enumerated legal options, and takes an answer. Humans, random policies, greedy
policies and search are all clients of the same interface (ADR 0009, decision 1).

This first slice is *vanilla*: real decks are loaded, but no card text is
executed. Units are bodies with Might and a cost; spells and gear are played
(cost paid, Chain used) and do nothing. Everything about the STRUCTURE — zones,
turn order, the Chain, Showdowns, Combat, Scoring — is meant to be right, and
`docs/engine/spec.md` says which Core Rules sections are implemented, which are
simplified, and which are out of scope.

Import layout. The kernel is pure Python 3.9+ with no third-party packages and
reaches no further than the skill folder (ADR 0004): the lines below put the
skill's own `lib/` on the path so `cards` and `deckfile` resolve whether the
engine is imported as a package or one of its modules is run directly.
"""
import os
import sys

_LIB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

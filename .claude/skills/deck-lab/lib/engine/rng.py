"""A deterministic generator whose whole state is one integer.

`random.Random` is the obvious choice and the wrong one here. Its state is a
tuple of 625 integers, so cloning a position — the operation search spends all
its time on — would copy 625 machine words per seat before it copied anything
about the game. splitmix64 is a 64-bit integer in, a 64-bit integer out, which
makes a clone of the generator a single `int` assignment.

It is also reproducible across processes, which `hash()` is not: Python salts
string hashing per interpreter, so a seed derived with `hash("x")` produces a
different game tomorrow. Seeds derive from blake2b instead.

Every function is pure: it takes a state and returns `(new_state, value)`. The
caller stores the new state. Nothing here mutates.
"""
import hashlib

MASK64 = (1 << 64) - 1
_GOLDEN = 0x9E3779B97F4A7C15


def step(state):
    """One step of splitmix64. Returns (next state, 64-bit value)."""
    state = (state + _GOLDEN) & MASK64
    z = state
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK64
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK64
    return state, z ^ (z >> 31)


def below(state, n):
    """A value in [0, n). Returns (next state, value).

    Plain modulo. The bias is bounded by n / 2**64 — for the largest n this
    engine ever asks for (a 40-card shuffle) that is about 2e-18, which is
    smaller than the chance of the seed being mistyped. Rejection sampling
    would cost a branch on every draw for that.
    """
    if n <= 1:
        return state, 0
    state, value = step(state)
    return state, value % n


def shuffle(state, items):
    """Fisher-Yates, in place, on this stream. Returns the next state.

    Downward, so the same list shuffled from the same state is the same
    permutation on every platform and Python version — `random.shuffle`'s
    algorithm is not part of its contract.
    """
    for i in range(len(items) - 1, 0, -1):
        state, j = below(state, i + 1)
        items[i], items[j] = items[j], items[i]
    return state


def seed_from(text):
    """A 64-bit seed from a string, stable across processes and releases."""
    digest = hashlib.blake2b(str(text).encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big")


def seat_seed(seed, seat):
    """The stream a seat shuffles and draws on.

    Derived from the seed and the SEAT, never from the game as a whole: a
    single shared stream made one seat's shuffle depend on how many numbers the
    other seat's deck had consumed, so a 39-card list silently unpaired two
    arms of a comparison that a 40-card list paired perfectly. The table
    learned that the hard way (see `table.Table.__init__`); the engine inherits
    the fix rather than the bug.
    """
    return seed_from("%s/seat%d" % (seed, seat))

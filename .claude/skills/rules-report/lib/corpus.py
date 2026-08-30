"""Where the skill's data lives.

The skill is the shipped artifact: copy `rules-report/` anywhere an agent can
run it and answering works offline, immediately, with no build step. Everything
needed for that is vendored in `data/`:

    data/rules.json    the parsed rulebook — 3,300+ addressable rules
    data/cards.json    every card's printed text, keywords and artwork URL
    data/rules.html    the anchored rulebook reports link into

Only *rebuilding* that data needs anything external, and only a maintainer does
that (`npm run oracle skill-data` in the source repo). `source_corpus_dir()`
below exists for exactly that path and is never touched while answering — a
user who never clones the repo should never see it mentioned.
"""
import glob
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.normpath(os.path.join(HERE, ".."))
DATA = os.path.join(SKILL, "data")
REPO = os.path.normpath(os.path.join(SKILL, "..", "..", ".."))

# Markdown the *rebuild* path reads. Not needed to answer a question.
REQUIRED_SOURCE = ("core-rules.md", "tournament-rules.md")


def data_path(name):
    """A file inside the skill's vendored data directory."""
    return os.path.join(DATA, name)


def _require(name, how):
    path = data_path(name)
    if not os.path.exists(path):
        raise SystemExit(
            f"Missing {name}.\n"
            f"  Expected at: {path}\n\n"
            f"  {how}"
        )
    return path


def rules_json():
    return _require(
        "rules.json",
        "This ships with the skill, so an absent copy means the install is\n"
        "  incomplete — re-copy the rules-report/ folder. To rebuild from source:\n"
        "    python3 rules_cli.py build",
    )


def cards_json():
    return _require(
        "cards.json",
        "This ships with the skill. Re-copy the rules-report/ folder, or\n"
        "  regenerate it from the source repo with:\n"
        "    npm run oracle skill-data",
    )


def load_cards():
    """name -> {name, text, keywords, image}. Empty dict if absent.

    Card lookup degrades to "no card matching X" rather than exploding, because
    a rules-only question is still answerable without card data.
    """
    try:
        with open(data_path("cards.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


# A word welded onto the punctuation that closed the clause before it, with no
# space between: `...where you have units.)ambush`. That is not prose, it is a
# seam left by whatever turned a PDF or a web page into text, and it reads as
# rules. On `Gemhand Hunter` it read as the Ambush keyword, and two agents built
# and piloted decks around an ability the card does not have.
#
# Two exclusions, both MEASURED over the shipped pool rather than reasoned. Widen
# this and you will meet them; they are recorded so you meet them here first.
#
# `:` is excluded because Riftbound symbol markup is written `:rb_might:`.
# Admitting it takes this from 0 complaints to 1,183 — every symbol on every
# card. `,` and `;` are IN: both are clean today, and a word fused onto a comma
# is the same seam as a word fused onto a full stop.
#
# The following letter must be LOWERCASE, which is the subtler one. Widening
# `[a-z]` to `[A-Za-z]` here matches 357 cards / 411 occurrences, all the same
# benign shape: reminder text closing and rules text beginning with no space —
# `(Play on your turn or in showdowns.)Each player kills one of their gear.`
# That is a cosmetic seam in the source, and it invents nothing, because a
# capital reads as a new sentence. (An earlier draft of this comment said 284,
# which was measured with a narrower probe — `[)\]][A-Z][a-z]+` — and quoted as
# though it described the widening above. The decision is the same either way;
# the number was not, and a measurement stated in a comment justifying a design
# outlives anyone's memory of which pattern produced it.)
#
# A LOWERCASE word fused on is the dangerous
# one precisely because it reads as continuing prose, or as a keyword: that is
# how `ambush` became an ability `Gemhand Hunter` does not have.
#
# KNOWN BLIND SPOT, and it is a trade rather than an oversight: the two-letter
# floor means a ONE-letter fusion is silent — `...units.)a unit gains Shield`
# passes. The floor is what holds this at zero false positives over the pool,
# and a one-letter token is far less likely to read as a keyword. Recorded
# because a limit nobody wrote down is indistinguishable from a limit nobody
# knew about. (Found by riftbound-oracle-c6 reviewing this.)
FUSED_ARTIFACT = re.compile(r"[,;)\].!?][a-z]{2,}")

# ...and the CAPITALISED shape, anchored to the end of the text.
#
# The reasoning above was inverted where it mattered most. It said a capital
# "reads as a new sentence" and a lowercase word is "the dangerous one because
# it reads as a keyword". But EVERY ONE of the 35 bracketed keywords in this
# corpus is capitalised — `Ambush`, `Deathknell`, `Tank`, `Deflect`. So a fused
# KEYWORD arrives capitalised, exactly as the keyword ships, and `.)Ambush`
# reads as the Ambush keyword at least as strongly as `.)ambush` did. Both
# halves of the pair were blind to it: `stripTrailingArtifact` requires
# lowercase too. `Gemhand Hunter` was lowercase by luck.
#
# Unanchored it would cost 357 cards of benign reminder/rules seam. ANCHORED it
# costs nothing measurable: zero cards in the pool end in punctuation followed
# by a word, which is also precisely where the Gemhand artifact sat. So the
# end-of-text position takes both cases, and the interior keeps the lowercase
# floor that holds the whole scan at zero false positives.
FUSED_ARTIFACT_TAIL = re.compile(r"[,;)\].!?][A-Za-z]{2,}$")


def artifact_complaints(cards):
    """Card text carrying an extraction artifact. Empty when the corpus is clean.

    DELIBERATELY WIDER than `stripTrailingArtifact` in `src/skill-data.ts`, and
    it must stay wider. That function DELETES, so it is anchored to the end of
    the string and demands three trailing letters — deleting the wrong span
    destroys a real card's rules text, and there is no way to notice afterwards.
    This only REPORTS, and reporting cannot destroy anything, so it casts wide
    on three axes: unanchored, a larger punctuation class, and a floor of two
    letters rather than three.

    The asymmetry is the entire point. A detector derived from the stripper
    could only ever find what the stripper already removes, which is not a
    detector — it is the same function asked twice. So when this fires on
    something the stripper leaves alone, that is this working. Go and look at
    the card. Do NOT widen the stripper to make this green, and do not narrow
    this to match the stripper; either one collapses the pair back into one
    opinion.

    Returns a list of strings so a caller can print them. The corpus is clean as
    of the 1,037-card pool this shipped against, so a non-empty return means
    either a new artifact or a false positive, and both want a human.
    """
    out = []
    for key, card in sorted(cards.items()):
        # Total by construction: a malformed entry is skipped rather than
        # raised on. Whether the corpus is structurally sound is `card_rendering`
        # and `corpus_integrity`'s question, and a detector that dies on a bad
        # card cannot report on the good ones beside it.
        text = card.get("text") if isinstance(card, dict) else None
        if not isinstance(text, str):
            continue
        seen = set()
        for rx in (FUSED_ARTIFACT, FUSED_ARTIFACT_TAIL):
            for m in rx.finditer(text):
                if m.start() in seen:
                    continue
                seen.add(m.start())
                start = max(0, m.start() - 40)
                out.append(f"{card.get('name') or key}: ...{text[start:m.end() + 20]}...")
    return out


def rulebook_html_path():
    """The anchored rulebook. Generated by `rules_cli.py rulebook`."""
    return data_path("rules.html")


def reports_dir():
    path = os.path.join(SKILL, "reports")
    os.makedirs(path, exist_ok=True)
    return path


def source_corpus_dir():
    """Maintainer-only: the markdown `rules_cli.py build` parses.

    Resolution order, first usable wins: an explicit override, the source
    repo's output/, then an Obsidian vault raw/ folder if one is synced.
    """
    for candidate in (
        os.environ.get("RIFTBOUND_CORPUS"),
        os.path.join(REPO, "output"),
        os.environ.get("VAULT_RAW_DIR"),
    ):
        if candidate and all(
            os.path.exists(os.path.join(candidate, f)) for f in REQUIRED_SOURCE
        ):
            return candidate
    raise SystemExit(
        "No source corpus found — this is only needed to REBUILD the rulebook.\n"
        "  Answering questions uses the vendored data/rules.json and needs none of this.\n\n"
        f"  Looked for {', '.join(REQUIRED_SOURCE)} in:\n"
        f"    $RIFTBOUND_CORPUS   ({os.environ.get('RIFTBOUND_CORPUS') or 'unset'})\n"
        f"    {os.path.join(REPO, 'output')}\n"
        f"    $VAULT_RAW_DIR      ({os.environ.get('VAULT_RAW_DIR') or 'unset'})\n\n"
        "  Generate one from the source repo with:  npm run oracle process && npm run oracle extract"
    )


def source_card_files():
    """Maintainer-only: the per-set markdown that `oracle skill-data` folds into cards.json."""
    return sorted(glob.glob(os.path.join(source_corpus_dir(), "cards-*.md")))

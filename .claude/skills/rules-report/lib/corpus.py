"""Where the source corpus lives.

Resolved in this order, first hit wins:

  1. $RIFTBOUND_CORPUS   — explicit override
  2. <repo>/output       — what `npm run oracle process` writes; the default for
                           anyone who clones this repo and runs the pipeline
  3. $VAULT_RAW_DIR      — an Obsidian wiki raw/ folder, if you sync one

Previously this was one hardcoded path into the author's personal Obsidian
vault, which made the skill unusable for anyone else. Resolution is dynamic so
a fresh clone works with no configuration.
"""
import glob
import os

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", "..", "..", ".."))

# Files the corpus must contain to be usable.
REQUIRED = ("core-rules.md", "tournament-rules.md")


def _usable(path):
    return bool(path) and all(os.path.exists(os.path.join(path, f)) for f in REQUIRED)


def corpus_dir():
    for candidate in (
        os.environ.get("RIFTBOUND_CORPUS"),
        os.path.join(REPO, "output"),
        os.environ.get("VAULT_RAW_DIR"),
    ):
        if _usable(candidate):
            return candidate
    raise SystemExit(
        "No Riftbound corpus found.\n"
        f"  Looked for {', '.join(REQUIRED)} in:\n"
        f"    $RIFTBOUND_CORPUS   ({os.environ.get('RIFTBOUND_CORPUS') or 'unset'})\n"
        f"    {os.path.join(REPO, 'output')}\n"
        f"    $VAULT_RAW_DIR      ({os.environ.get('VAULT_RAW_DIR') or 'unset'})\n\n"
        "  Generate one with:  npm run oracle process\n"
        "  See the README for the extraction step that produces the rules markdown."
    )


def card_files():
    return sorted(glob.glob(os.path.join(corpus_dir(), "cards-*.md")))


def image_index_path():
    """name -> image url, written by `npm run oracle card-index`. Optional."""
    return os.path.join(corpus_dir(), "card-index.json")

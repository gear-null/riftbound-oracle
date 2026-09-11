"""Maintainer-only: vendor the chain, showdown and combat primers' transitions.

The spec for `chain.py` and `combat.py` is three rules-report primers whose every
citation has been verified verbatim against the Core Rules. The engine cannot READ them at
runtime — copying the deck-lab folder has to be the whole install (ADR 0004), and
rules-report is a different folder — so the transitions are vendored here into
`goldens/chain-transitions.json` and the selftest walks that.

    python3 engine/vendor_primers.py         # from lib/, inside this repo

Run it after a rules update. It records the primer's corpus stamp, so a vendored
table from an older Core Rules is visible rather than silent, and the selftest
fails if a transition in the table has no check behind it — which is what stops
this copy from quietly falling behind the document it came from.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "goldens", "chain-transitions.json")
#: lib/engine -> lib -> deck-lab -> skills -> rules-report/lib
PRIMERS = os.path.abspath(os.path.join(
    HERE, "..", "..", "..", "rules-report", "lib"))

SOURCES = [("hot-fepr", "hot-fepr-primer.json"),
           ("showdowns", "showdowns-primer.json"),
           ("combat", "combat-primer.json")]


def build():
    out = {"note": "vendored from rules-report's verified primers by "
                   "engine/vendor_primers.py — do not hand-edit",
           "primers": {}, "transitions": []}
    for key, filename in SOURCES:
        path = os.path.join(PRIMERS, filename)
        with open(path, encoding="utf-8") as fh:
            primer = json.load(fh)
        out["primers"][key] = {"topic": primer["topic"], "corpus": primer["corpus"]}
        for step in primer["steps"]:
            for i, exit_ in enumerate(step.get("exits", [])):
                out["transitions"].append({
                    "primer": key,
                    "from": step["id"],
                    "heading": step["heading"],
                    "exit": i,
                    "when": exit_["when"],
                    "goto": exit_.get("goto"),
                    "cites": [c["rule"] for c in exit_.get("cites", [])],
                })
    return out


def main():
    if not os.path.isdir(PRIMERS):
        print("rules-report is not next to this skill — nothing to vendor from.\n"
              "This script is maintainer-only and runs inside the source repo.")
        return 1
    payload = build()
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    print("wrote %d transitions from %d primers -> %s"
          % (len(payload["transitions"]), len(payload["primers"]),
             os.path.relpath(OUT, HERE)))
    return 0


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(HERE))
    sys.exit(main())

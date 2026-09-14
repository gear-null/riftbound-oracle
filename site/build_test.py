#!/usr/bin/env python3
"""Tests for the site generator's two verifiers.

WHY THIS FILE EXISTS SEPARATELY

`build.py` enforces two of this project's own invariants on the website — that
a page draws exactly the transitions its primer declares (invariant 12), and
that the hand-written pages do not state a stale rule count. Both are checks,
and this project's rule is that a check nobody has watched fail is not yet a
check. They lived in `build.py` with nothing exercising them.

They cannot be tested from `selftest.py`: ADR 0004 forbids the answering path
reaching outside the skill folder, and `build.py` sits in the repo. So the site
gets its own tests, run by CI beside the build itself.

    python3 site/build_test.py
"""
import importlib.util
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent

RAN = [0]
FAILED = []


def check(name, ok, detail=""):
    RAN[0] += 1
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{'  — ' + detail if detail else ''}")
    if not ok:
        FAILED.append(name)


def load_build():
    spec = importlib.util.spec_from_file_location("sitebuild", HERE / "build.py")
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except SystemExit:
        pass          # module-level code may exit; we only want its functions
    return mod


def refuses(fn, *args):
    """Return the SystemExit message, or '' when it did not refuse."""
    try:
        fn(*args)
        return ""
    except SystemExit as exc:
        return str(exc)


def main():
    print("site build — verifier tests\n")
    b = load_build()

    primer = json.loads(
        (REPO / ".claude/skills/rules-report/lib/hot-fepr-primer.json")
        .read_text(encoding="utf-8"))
    page = (HERE / "hot-fepr.html").read_text(encoding="utf-8")
    declared = sum(len(s.get("exits") or []) for s in primer["steps"])

    # --- invariant 12, on the page -----------------------------------------
    check("the shipped page agrees with its primer",
          not refuses(b.check_page_declares_no_extra_transitions,
                      "hot-fepr", primer, page))

    dropped = re.sub(r'class="exit-n[^"]*"[^>]*>2<', "", page, count=1)
    check("a transition missing from the page is caught",
          "declares" in refuses(b.check_page_declares_no_extra_transitions,
                                "hot-fepr", primer, dropped))

    invented = page.replace(
        f'>{declared}<', f'>{declared}<span class="exit-n">{declared + 1}</span>', 1)
    check("a transition the primer never declared is caught",
          "declares" in refuses(b.check_page_declares_no_extra_transitions,
                                "hot-fepr", primer, invented))

    # A `structural` exit renders `class="exit-n dashed"`. Matching the class
    # attribute exactly missed every one of them and failed honest pages.
    dashed = page.replace('class="exit-n"', 'class="exit-n dashed"')
    check("a dashed (structural) transition still counts as drawn",
          not refuses(b.check_page_declares_no_extra_transitions,
                      "hot-fepr", primer, dashed))

    # --- a goto that names no step -----------------------------------------
    # It used to fall through to "The procedure ends here" — telling a reader
    # the procedure terminates where the author said it continues. The build
    # refuses now, and this is what watches that refusal happen.
    broken = json.loads(json.dumps(primer))
    for step in broken["steps"]:
        for ex in (step.get("exits") or []):
            if ex.get("goto"):
                ex["goto"] = "no-such-step"
                break
        else:
            continue
        break
    order = {st["id"]: i for i, st in enumerate(broken["steps"])}
    msg = refuses(b.explainer, "hot-fepr", broken, set())
    check("a goto naming no step refuses the build",
          "no step declares" in msg,
          msg[:90] or "the page was built anyway")
    check("the refusal does not silently say the procedure ends",
          "ends here" not in msg.lower() or "no step declares" in msg,
          msg[:60])

    # --- the hand-written corpus claim -------------------------------------
    index = HERE / "index.html"
    original = index.read_text(encoding="utf-8")
    rules = json.loads(
        (REPO / ".claude/skills/rules-report/data/rules.json").read_text(encoding="utf-8"))
    actual = len(rules if isinstance(rules, list) else rules.get("rules", rules))
    try:
        check("the shipped page states the corpus size correctly",
              not refuses(b.check_handwritten_corpus_claims))

        index.write_text(original.replace(f"{actual:,} rules", "9,999 rules", 1),
                         encoding="utf-8")
        check("a stale rule count is caught",
              "9,999" in refuses(b.check_handwritten_corpus_claims))

        # Each of these read as checked and was not: the old pattern demanded a
        # literal ASCII space and a lowercase word.
        for label, shape in (
            ("&nbsp;", f"9,999&nbsp;rules"),
            ("bold", f"<b>9,999</b> rules"),
            ("capitalised", f"9,999 Rules"),
        ):
            index.write_text(original.replace(f"{actual:,} rules", shape, 1),
                             encoding="utf-8")
            check(f"a stale count written with {label} is still caught",
                  "9,999" in refuses(b.check_handwritten_corpus_claims))

        # Losing the claim entirely must not read as passing.
        index.write_text(original.replace(f"{actual:,} rules", "many rules of note", 1)
                         .replace("rules", "guidelines"), encoding="utf-8")
        check("a page that no longer states a count says so, rather than passing",
              "no '<n> rules' claim" in refuses(b.check_handwritten_corpus_claims))
    finally:
        index.write_text(original, encoding="utf-8")

    # The sample reports are demonstrations on a website, not local reports.
    # The masthead's "Portable copy" control — a link to a sibling `report`
    # wrote, or a note naming the CLI to write one — means nothing to a visitor
    # and, left in, tells them to run a tool they do not have.
    for name in ("ruling-flow-counter.html", "primer-hot-fepr.html"):
        page = (HERE / "reports" / name).read_text(encoding="utf-8")
        check(f"{name} carries no portable-copy control",
              'id="portable"' not in page and "rules_cli.py export" not in page,
              "a site visitor was told to run the CLI")
    # ...and the strip is COUNTED, so a renderer that stops emitting the control
    # (or emits two) refuses the build rather than publishing quietly.
    check("the site build refuses a sample with no control to strip",
          "expected exactly one portable-copy control" in refuses(
              lambda: b.strip_portable_control("<html><body>no control</body></html>", "probe")),
          "a changed masthead must be noticed, not absorbed")

    print()
    if FAILED:
        print(f"FAILED {len(FAILED)} of {RAN[0]}: {', '.join(FAILED)}")
        sys.exit(1)
    print(f"all {RAN[0]} site checks passed")
    sys.exit(0)


if __name__ == "__main__":
    main()

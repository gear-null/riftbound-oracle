"""Spike: mechanical citation verification against the parsed rule tree.

The bet: most citation failures are catchable by CODE, with no LLM in the loop.
If true, we can guarantee that a citation reaching the user at least (a) points
at a real rule and (b) quotes it verbatim — the two things unverified
citation pipelines get wrong most often.

Checks, cheapest first:
  E  exists        — the cited id is a real rule at this version
  Q  quote         — the quoted span appears verbatim in that rule (or subtree)
  R  retrieved     — the id was in the retrieved set (not recalled from memory)
  V  version       — the id didn't change meaning between corpus versions
  S  supports      — the rule actually supports the claim   [LLM, not here]
"""
import json, re, sys, unicodedata
from dataclasses import dataclass, field
from typing import List, Optional

from corpus import rules_json as _rules_json_path


def norm(s: str) -> str:
    """Compare on substance: fold unicode punctuation, collapse whitespace."""
    s = unicodedata.normalize("NFKC", s)
    s = (s.replace("‘", "'").replace("’", "'")
          .replace("“", '"').replace("”", '"')
          .replace("–", "-").replace("—", "-")
          .replace(" ", " "))
    return re.sub(r"\s+", " ", s).strip().lower()


class RuleIndex:
    def __init__(self, path=None):
        path = path or _rules_json_path()
        self.rules = {}
        for r in json.load(open(path, encoding="utf-8")):
            self.rules[f'{r["doc"]}:{r["id"]}'] = r
        # Bare-id lookup, for citations written without a doc prefix.
        self.by_id = {}
        for key, r in self.rules.items():
            self.by_id.setdefault(r["id"], []).append(r)

    def get(self, rule_id, doc=None):
        """Look up a rule, never crossing document boundaries.

        The previous `... or hits` fallback made the doc filter advisory: when
        the requested document lacked the id, it returned the OTHER document's
        rule. So a cite written "TR:104.1" resolved to CR:104.1 and rendered
        with a green "verified" stamp attributing Core Rules text to the
        Tournament Rules. 145 ids exist in both documents and they say
        different things, which makes this the highest-stakes mis-attribution
        available. A rule absent from the cited document is a citation failure.
        """
        if ":" in rule_id:
            return self.rules.get(rule_id)
        hits = self.by_id.get(rule_id, [])
        if doc is not None:
            return next((r for r in hits if r["doc"] == doc), None)
        return hits[0] if hits else None

    def subtree_parts(self, rule_id, doc=None):
        """Every block a quote could legitimately come from, kept SEPARATE.

        Blocks are the unit Riot publishes, so they are the unit of matching.
        This used to return one joined string, and joining MANUFACTURES text
        that was never published: a quote welded from the end of one block and
        the start of the next matched the concatenation. That is the cheapest
        possible way to defeat a verbatim gate — a sentence appearing nowhere
        in the rules, stamped verified.

        Descendants' Examples are included, not just the cited rule's own. They
        were omitted, so a quote from a child's Example verified at the child
        and was rejected as "paraphrased" at every ancestor above it.
        """
        r = self.get(rule_id, doc)
        if not r:
            return []
        prefix = r["id"] + "."
        kin = [r] + [x for x in self.rules.values()
                     if x["doc"] == r["doc"] and x["id"].startswith(prefix)]
        parts = []
        for x in kin:
            parts.append(x["text"])
            parts.extend(x.get("examples", []))
        return parts

    def ancestry(self, rule_id, doc=None):
        r = self.get(rule_id, doc)
        chain = []
        while r:
            chain.append(r)
            p = r["parent"]
            r = self.get(p, r["doc"]) if p else None
        return list(reversed(chain))

    # --- topic blocks -----------------------------------------------------
    #
    # Riot writes some topics as a bare heading followed by SIBLING sections
    # rather than children:
    #
    #     467. Scoring                      <- heading, no children
    #     468. Scoring is the act of ...    <- the actual rules, as siblings
    #     469. A player Scores in one of two ways:
    #
    # Rules 315.2.b.2 and 194.1.a both say "see rule 467. Scoring", so anyone
    # following that cross-reference lands on one word and an empty subtree.
    # That reads as "the rules are silent here", which is the most dangerous
    # wrong conclusion this system can reach. `topic_block` finds where the
    # content actually lives.

    @staticmethod
    def _looks_like_heading(rule):
        """A title, not a sentence: 'Scoring', 'Golden Rule', 'Setup'.

        Measured over the corpus this splits the 180 childless top-level
        sections into 80 headings and 100 genuine one-line rules.
        """
        text = rule["text"].strip()
        return not text.endswith((".", ":", ";")) and len(text) < 60

    def _top_sections(self, doc):
        def key(r):
            return [(0, int(s), "") if s.isdigit() else (1, 0, s)
                    for s in r["id"].split(".")]
        return sorted(
            (r for r in self.rules.values()
             if r["doc"] == doc and r.get("depth") == 1),
            key=key,
        )

    def is_topic_heading(self, rule):
        """A heading whose content lives in the sections that follow it."""
        if rule.get("depth") != 1 or not self._looks_like_heading(rule):
            return False
        return not any(
            r.get("parent") == rule["id"] and r["doc"] == rule["doc"]
            for r in self.rules.values()
        )

    def _following_tops(self, rule):
        tops = self._top_sections(rule["doc"])
        for i, r in enumerate(tops):
            if r["id"] == rule["id"]:
                return tops[i + 1:]
        return []

    def topic_block(self, rule):
        """The sections a bare heading is really pointing at.

        Everything following it in document order, up to the next heading.
        Returns [] for anything that is not a childless heading, so a caller
        can read an empty result as "ordinary section, nothing extra".
        """
        if not self.is_topic_heading(rule):
            return []
        block = []
        for r in self._following_tops(rule):
            if self._looks_like_heading(r):
                break
            block.append(r)
        return block

    def topic_contents(self, rule):
        """Sub-headings under a CHAPTER heading — one immediately followed by
        another heading rather than by rules.

        Two levels exist: "463. The Steps of Combat" contains "464. Step 1:
        The Combat Showdown Step", which contains the actual rules. So
        `topic_block` finds nothing for 463 and the reader is back to an empty
        result — and 316.7.e and 348.1 both say "see rule 463", as do two
        tournament rules for 600. Listing the sub-headings gives them
        somewhere to go.

        Returns the headings that FOLLOW it, up to the next chapter — document
        order, not proven containment. Riot's numbering carries no chapter end
        marker, so any stronger claim is wrong somewhere: 649 "Conceding" comes
        after 484 "Sanctioned Modes" without being one. Callers should present
        this as "continues with", and the honest framing is what makes the
        heuristic safe.

        Stops at the first body section and at the next chapter. Skipping body
        sections instead was tried and is worse: it let "463. The Steps of
        Combat" run past its four steps into Layers and Modes of Play, to buy
        one extra entry under "100. Game Concepts". The two chapters anything
        actually cross-references — 463 and 600 — are exactly the ones the
        conservative rule gets right.
        """
        if not self.is_topic_heading(rule) or self.topic_block(rule):
            return []
        contents = []
        for r in self._following_tops(rule):
            if not self._looks_like_heading(r) or self._is_chapter(r):
                break
            contents.append(r)
        return contents

    def _is_chapter(self, rule):
        """A heading whose contents are further headings, not rules."""
        return self.is_topic_heading(rule) and not self.topic_block(rule)


@dataclass
class CitationCheck:
    rule_id: str
    exists: bool
    quote_verbatim: Optional[bool]   # None = no quote supplied
    in_retrieved_set: Optional[bool]  # None = no retrieval set supplied
    problems: list = field(default_factory=list)
    narrowed_to: Optional[str] = None   # tightest rule whose own text has the quote

    @property
    def ok(self):
        """Passing every check that RAN. See `checked` — a cite with no quote
        runs no quote check, so `ok` alone must never be rendered as verified."""
        return self.exists and self.quote_verbatim is not False and self.in_retrieved_set is not False

    @property
    def checked(self):
        """True only when the quote check actually ran and passed.

        `quote_verbatim is None` means no quote was supplied, and `None is not
        False`, so such a cite used to satisfy `ok` and render a green
        "verified" stamp attesting only that the id exists. Omitting the quote
        was therefore the cheapest way to defeat the gate — no fabrication
        needed."""
        return self.ok and self.quote_verbatim is True

    @property
    def cite_as(self):
        """Always cite the tightest rule that actually says the thing."""
        return self.narrowed_to or self.rule_id


def verify_citation(idx: RuleIndex, rule_id: str, quote: Optional[str] = None,
                    retrieved: Optional[set] = None,
                    doc: Optional[str] = None) -> CitationCheck:
    problems = []
    # Accept "CR:194.3" as well as ("194.3", doc="CR"). Without normalising here
    # the narrowing pass compared a prefixed id against bare stored ids, found
    # nothing, and flipped a CORRECT quote to a failure.
    if ":" in rule_id:
        doc, rule_id = rule_id.split(":", 1)
    rule = idx.get(rule_id, doc)
    exists = rule is not None
    if not exists:
        # Localise rather than just reject: the commonest cause is a CR/TR slip,
        # and saying which document holds the id is directly actionable.
        elsewhere = [r["doc"] for r in idx.by_id.get(rule_id, [])]
        if elsewhere and doc:
            problems.append(
                f"rule {rule_id} does not exist in {doc}; it is a "
                f"{'/'.join(sorted(set(elsewhere)))} rule — wrong document")
        else:
            problems.append(f"rule {rule_id} does not exist in this corpus version")
        return CitationCheck(rule_id, False, None, None, problems)

    quote_ok = None
    narrowed_to = None
    if quote:
        needle = norm(quote)
        # `any` over separate blocks, never `in` on a join.
        quote_ok = any(needle in norm(p) for p in idx.subtree_parts(rule_id, doc))

        # NARROWING. A subtree match is too generous: citing 425.1 while quoting
        # 425.1.a.1 passes, which launders a vague citation as a verified one.
        # Rewrite to the deepest rule whose OWN text carries the quote.
        if quote_ok:
            # NORMATIVE TEXT WINS; Examples are only a fallback. Examples
            # routinely restate a NEIGHBOURING rule verbatim, so ranking them
            # equally let an Example's owner outrank the rule whose own text
            # carries the quote — 383.3.a narrowed onto 383.3.a.3, which states
            # the opposite case, under a banner asserting the quote "lives"
            # there. Two passes, text first, keeps attribution honest while
            # still letting the 262 official Examples be cited.
            scope = [
                r for r in idx.rules.values()
                if r["doc"] == rule["doc"]
                and (r["id"] == rule_id or r["id"].startswith(rule_id + "."))
            ]
            own = [r for r in scope if needle in norm(r["text"])]
            if not own:
                own = [r for r in scope
                       if any(needle in norm(e) for e in r.get("examples", []))]
            if own:
                deepest = max(own, key=lambda r: r["depth"])
                if deepest["id"] != rule_id:
                    narrowed_to = deepest["id"]
                    problems.append(
                        f"cite narrowed: quote lives in {narrowed_to}, not {rule_id} itself"
                    )
            else:
                # Verbatim across a rule boundary — spans parent+child text.
                problems.append(
                    f"quote spans multiple rules under {rule_id}; cite the specific one"
                )
                quote_ok = False
        if not quote_ok:
            # Is it verbatim from somewhere ELSE? That's a mis-attribution,
            # a materially different (and more dangerous) error than a paraphrase.
            found_in = [
                k for k, r in idx.rules.items()
                if needle in norm(r["text"])
            ][:3]
            if found_in:
                problems.append(
                    f"quote is not in {rule_id}; it appears in {', '.join(found_in)} — mis-attributed"
                )
            else:
                problems.append(f"quote not found verbatim in {rule_id} or its subtree — paraphrased")

    in_set = None
    if retrieved is not None:
        in_set = rule_id in retrieved or f'{rule["doc"]}:{rule_id}' in retrieved
        if not in_set:
            problems.append(f"{rule_id} was not in the retrieved set — recalled from memory")

    return CitationCheck(rule_id, exists, quote_ok, in_set, problems, narrowed_to)


# ---------------------------------------------------------------- self-test

KNOWN_BAD = [
    # Real citation errors caught during this project, used as regression cases.
    dict(name="wrong sub-clause (Victory Score)", rule_id="194.2.b",
         quote="The Victory Score is 8 points by default.",
         why="cited 194.2.b; the text lives at 194.3"),
    dict(name="inverted id (non-Conquer exemption)", rule_id="471.1.b.1",
         quote="points Gained from sources that are not Conquer are not beholden to these restrictions",
         why="cited 471.1.b.1; the text lives at 471.1.a.1"),
    dict(name="nonexistent rule", rule_id="999.9.z",
         quote=None, why="fabricated id"),
    dict(name="plausible claim, wrong rule", rule_id="106",
         quote="Banishment is part of the Board",
         why="106 does not say this; 108.6 says the opposite"),
    dict(name="stale numbering after renumber", rule_id="343.1",
         quote="Focus passes to the next Player in Turn Order",
         why="content moved to 346.1 in a renumbering"),
]

VAGUE = [
    # Real defect the panel found: a subtree match let a vague cite pass clean.
    dict(name="vague cite, quote lives deeper", rule_id="416",
         quote="Runes are Recycled to the Rune Deck", expect_narrow="416.1.b"),
    dict(name="vague cite of a big section", rule_id="829",
         quote="Banishing the spell in this way is a delayed replacement effect",
         expect_narrow="829.1.b.1"),
]

GOOD = [
    dict(name="correct: Victory Score", rule_id="194.3",
         quote="The Victory Score is 8 points by default."),
    dict(name="correct: non-Conquer exemption", rule_id="471.1.a.1",
         quote="points Gained from sources that are not Conquer are not beholden to these restrictions"),
    dict(name="correct: Flow banish is a delayed replacement", rule_id="829.1.b.1",
         quote="Banishing the spell in this way is a delayed replacement effect"),
    dict(name="correct: tightest cite", rule_id="416.1.b",
         quote="Runes are Recycled to the Rune Deck"),
]


def main():
    idx = RuleIndex()
    print(f"loaded {len(idx.rules)} rules\n")

    print("=== KNOWN-BAD citations (verifier should REJECT all) ===")
    caught = 0
    for c in KNOWN_BAD:
        res = verify_citation(idx, c["rule_id"], c.get("quote"))
        status = "REJECTED" if not res.ok else "*** MISSED ***"
        if not res.ok:
            caught += 1
        print(f"  [{status}] {c['name']}")
        print(f"      cited {c['rule_id']} — {c['why']}")
        for p in res.problems:
            print(f"      -> {p}")
    print(f"\n  caught {caught}/{len(KNOWN_BAD)}\n")

    print("=== KNOWN-GOOD citations (verifier should ACCEPT all) ===")
    passed = 0
    for c in GOOD:
        res = verify_citation(idx, c["rule_id"], c.get("quote"))
        status = "accepted" if res.ok else "*** FALSE REJECT ***"
        if res.ok:
            passed += 1
        print(f"  [{status}] {c['name']} ({c['rule_id']})")
        for p in res.problems:
            print(f"      -> {p}")
    print(f"\n  accepted {passed}/{len(GOOD)}")

    print("\n=== VAGUE citations (should be NARROWED to the tightest rule) ===")
    for c in VAGUE:
        res = verify_citation(idx, c["rule_id"], c["quote"])
        got = res.narrowed_to
        ok = got == c["expect_narrow"]
        print(f"  [{'NARROWED' if ok else '*** FAILED ***'}] cited {c['rule_id']} -> cite_as {res.cite_as}"
              f"  (expected {c['expect_narrow']})")

    print("\n=== retrieval-set check (anti-confabulation) ===")
    res = verify_citation(idx, "471.1.a.1", None, retrieved={"416", "427"})
    print(f"  cited 471.1.a.1 while only 416/427 were retrieved -> ok={res.ok}")
    for p in res.problems:
        print(f"      -> {p}")


if __name__ == "__main__":
    main()

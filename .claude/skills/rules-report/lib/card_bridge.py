"""The card -> rules vocabulary bridge. Backs `rules_cli.py card`.

The problem it solves: questions are asked in CARD vocabulary ("does Windsinger
target across battlefields?") while the rules are written in RULES vocabulary.
Card names essentially never appear in rule text, so searching the rulebook for
a card name finds nothing — which is why this system looks cards up exactly and
navigates the rules, rather than retrieving over them.

The bridge resolves a card name, reads its printed text, and translates it into
rules terms: bracketed keywords map onto glossary sections (805-829) and action
sections by title, and the card's plain text supplies the rest. That turns
"Windsinger" into the sections that actually govern it.

Exactness is the point. A near-miss that silently returns a DIFFERENT card is
worse than no answer, so an inexact resolution is flagged rather than smoothed
over — see the `inexact` path below.
"""
import json, re
from collections import defaultdict

from corpus import load_cards, rules_json

# Card text says [Stun]; the rules title a section "423. Stun". Emoji shortcodes
# (:rb_might:, 543 occurrences) carry meaning too and must be translated, not dropped.
SHORTCODE = {
    "rb_might": "might", "rb_energy": "energy", "rb_power": "power",
    "rb_rune_rainbow": "[A]", "rb_exhaust": "[E]",
    "rb_recycle": "recycle", "rb_trash": "trash",
}

# Domain runes and numbered energy, rendered as the shorthand the rules use so
# the card panel agrees with the rule text quoted beside it and the symbol
# legend can gloss both. Unmapped codes used to be replaced with a space, which
# deleted the cost outright: Blighted Battleaxe read "[Equip] ( : Attach ...)"
# with its price gone, and Astral Heron lost the 2 Energy while the note on the
# same page quoted the errata as "costs [2][A][A] less".
DOMAIN_RUNE = {
    "rb_rune_fury": "[R]", "rb_rune_calm": "[G]", "rb_rune_mind": "[B]",
    "rb_rune_body": "[O]", "rb_rune_chaos": "[P]", "rb_rune_order": "[Y]",
}
SHORTCODE.update(DOMAIN_RUNE)


def _clip(text, limit=300):
    """Trim long card text at a word boundary and SAY that it was trimmed.

    A hard slice at 300 ended one card mid-sentence with no marker, so the
    panel read as the card's complete text when it was not. Silent truncation
    presented as complete is the failure this project exists to avoid.
    """
    if len(text) <= limit:
        return text
    cut = text[:limit]
    space = cut.rfind(" ")
    if space > limit * 0.6:
        cut = cut[:space]
    return cut.rstrip(" ,;:") + " …"


class CardBridge:
    def __init__(self, rules_path=None):
        # Keyed by lowercased name AND by the pre-subtitle base name, so both
        # "Viktor - Machine Herald" and "Viktor" resolve. Built by
        # `oracle skill-data`; see data/cards.json.
        self.cards = load_cards()
        self.term_to_rule = {}
        self._load_rule_titles(rules_path or rules_json())

    def _load_rule_titles(self, rules_json):
        for r in json.load(open(rules_json, encoding="utf-8")):
            if r["depth"] == 1 and r["doc"] == "CR":
                title = r["text"].strip().lower()
                # "Burn Out" and "Burn" are distinct sections; keep both exact.
                if 2 < len(title) < 40:
                    self.term_to_rule.setdefault(title, r["id"])

    def find_cards(self, question):
        """Word-boundary card matches, with partial matches flagged as inexact.

        Substring matching was actively dangerous: "Shadowfang Reaper" — a card
        that does not exist — matched the real card "Shadow" and returned its
        text with no warning. An agent handed the wrong card's text reasons
        confidently about a card the user never mentioned. A tool that says
        nothing is safer than one that quietly substitutes.
        """
        ql = question.lower()
        found, taken = [], []
        for key in sorted(self.cards, key=len, reverse=True):
            if not re.search(rf"(?<![a-z0-9]){re.escape(key)}(?![a-z0-9])", ql):
                continue
            if any(key in t for t in taken):
                continue
            taken.append(key)
            card = dict(self.cards[key])
            # Did the question name something LONGER that merely begins with this
            # card's name? Then this is probably not the card being asked about.
            m = re.search(rf"(?<![a-z0-9]){re.escape(key)}((?:\s+[a-z][a-z'-]+){{1,3}})", ql)
            longer = (key + m.group(1)).strip() if m else None
            card["inexact"] = bool(longer) and longer not in self.cards
            card["asked_as"] = longer or key
            found.append(card)
            if len(found) >= 4:
                break
        return found

    @staticmethod
    def _clean(text):
        """Expand :shortcode: emoji to words.

        Padded with spaces and re-collapsed: adjacent shortcodes are common
        (a two-rune cost is `:rb_rune_rainbow::rb_rune_rainbow:`) and without
        padding they fused into "power any domainpower any domain".
        """
        def sub(m):
            code = m.group(1)
            if code in SHORTCODE:
                return f" {SHORTCODE[code]} "
            # ":rb_energy_2:" -> "[2]", the same shorthand the rules print.
            n = re.fullmatch(r"rb_energy_(\d+)", code)
            if n:
                return f" [{n.group(1)}] "
            # Anything unrecognised keeps its name rather than vanishing; a
            # visible oddity is recoverable, a deleted cost is not.
            return f" [{code}] "

        text = re.sub(r":([a-z_0-9]+):", sub, text)
        text = re.sub(r"[ \t]{2,}", " ", text)
        # Padding the shortcodes leaves gaps against neighbouring punctuation:
        # "[2] [R] : Double" and "( [1] [R] :". Close them back up.
        text = re.sub(r"\s+([:.,)])", r"\1", text)
        return re.sub(r"([(\[])\s+", r"\1", text).strip()

    def card_terms(self, card):
        """Rules vocabulary implied by a card: its keywords and its effect words."""
        body = self._clean(card["text"])
        # Digits belong in the class: [Assault 2] and [Shield 3] never matched
        # a letters-only pattern, which also made the next line — stripping a
        # trailing number — dead code. 69 cards lost 84 glossary links to this.
        kws = [k.strip().lower() for k in re.findall(r"\[([A-Za-z][A-Za-z0-9 ]{2,20})\]", body)]
        kws = [re.sub(r"\s+\d+$", "", k) for k in kws]
        rules = []
        terms = []
        for k in dict.fromkeys(kws):
            terms.append(k)
            if k in self.term_to_rule:
                rules.append(self.term_to_rule[k])
        return {"name": card["name"], "image": card.get("image"),
                "stats": card.get("stats") or {},
                "ambiguous": card.get("ambiguous") or [],
                "incomplete": card.get("incomplete"),
                "inexact": card.get("inexact", False),
                "asked_as": card.get("asked_as", card["name"]),
                "keywords": list(dict.fromkeys(terms)),
                "rule_sections": list(dict.fromkeys(rules)),
                "text": _clip(re.sub(r"\s+", " ", body).strip())}

    def plan(self, question):
        """Translate a card-vocabulary question into a rules-vocabulary query."""
        cards = self.find_cards(question)
        bridged = [self.card_terms(c) for c in cards]
        kw_terms, sections = [], []
        for b in bridged:
            kw_terms += b["keywords"]
            sections += b["rule_sections"]
        return {"cards": bridged,
                "keyword_terms": list(dict.fromkeys(kw_terms)),
                "rule_sections": list(dict.fromkeys(sections))}


if __name__ == "__main__":
    import sys
    b = CardBridge()
    print(f"cards indexed: {len(b.cards)}   rule-title terms: {len(b.term_to_rule)}")
    q = sys.argv[1] if len(sys.argv) > 1 else \
        "Does Blighted Battleaxe unattach damage persist to opponent's turn?"
    p = b.plan(q)
    print(f"\nQ: {q}")
    for c in p["cards"]:
        print(f"  card: {c['name']}")
        print(f"        keywords: {c['keywords']}")
        print(f"        -> rules: {c['rule_sections']}")
        print(f"        text: {c['text'][:150]}")
    print(f"  bridged terms: {p['keyword_terms']}")

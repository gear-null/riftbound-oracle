#!/usr/bin/env python3
"""Tests for the vocabulary census.

    python3 -m unittest discover -s engine-train

Every case here is a bug the census actually had. A clause splitter is exactly
the kind of code that looks right on the card you happened to read and is wrong
on the one you did not, and the failure mode is silent: the counts still come
out, they are just counts of something else.

The last test is the one that matters most. `unclassified` is the instrument
that makes the coverage number mean anything, and an instrument that cannot
register a reading is not an instrument — so there is a test that puts text
into the bucket on purpose.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import census  # noqa: E402


def clauses(text, card="T"):
    census.install_tag_selector(census.load_pool()[0])
    return [census.classify(c) for c in census.segment(card, text)]


def kinds(text):
    return [(c.kind, c.text) for c in clauses(text)]


def buckets(text):
    out = []
    for c in clauses(text):
        out.extend(c.bucket)
    return out


class Normalisation(unittest.TestCase):
    def test_both_symbol_notations_fold_together(self):
        """Riftcodex sends `:rb_energy_1:`; Riot's errata prints `[1]`."""
        api = census.normalise("Pay :rb_energy_1::rb_rune_chaos: and :rb_might:.")
        errata = census.normalise("Pay [1][P] and [M].")
        self.assertEqual(api, errata)
        self.assertIn("{1}{P}", api)

    def test_retired_might_shorthand(self):
        """CR 135.2.e.3: [S] is Might's previous shorthand; one card still has it."""
        self.assertEqual(census.normalise("+2 [S]"), "+2 {M}")

    def test_run_together_sentences_are_separated(self):
        """Upstream serves `Draw 2.[Level 6]` with no space after the stop."""
        self.assertEqual(census.normalise("Draw 2.[Level 6]"), "Draw 2. [Level 6]")
        self.assertIn(") E", census.normalise("(reminder)Each player draws."))

    def test_reminder_text_is_removed_and_returned(self):
        body, reminders = census.split_reminder(
            census.normalise("[Assault 2] (+2 :rb_might: while I'm an attacker.)"))
        self.assertEqual(body, "[Assault 2]")
        self.assertEqual(len(reminders), 1)
        self.assertIn("attacker", reminders[0])


class Segmentation(unittest.TestCase):
    def test_multi_event_trigger_keeps_all_its_events(self):
        """`When this is played, discarded, or killed` is ONE trigger, 3 events.

        Splitting at the first comma produced the trigger `when this is played`
        and the instruction `discarded, or killed, draw 1`.
        """
        got = kinds("When this is played, discarded, or killed, draw 1.")
        self.assertEqual(got[0][0], "trigger")
        self.assertEqual(got[0][1], "When this is played, discarded, or killed")
        self.assertEqual(got[1], ("effect", "draw 1"))
        self.assertEqual(
            set(clauses("When this is played, discarded, or killed, draw 1.")[0].bucket),
            {"play_self", "discard_trigger", "die"})

    def test_enumerated_types_do_not_close_the_trigger(self):
        got = kinds("When you play a unit, gear, or activated ability with "
                    "Energy cost :rb_energy_7: or more, draw 1.")
        self.assertTrue(got[0][1].endswith("or more"), got[0][1])

    def test_quoted_granted_ability_is_not_an_activated_cost(self):
        """A colon after a symbol is not automatically a cost line.

        `While you control this battlefield, friendly legends have ":rb_exhaust::
        Attach…"` was read as the cost `While you control this battlefield`.
        """
        got = kinds('While you control this battlefield, friendly legends have '
                    '":rb_exhaust:: Attach an Equipment you control to a unit '
                    'you control."')
        self.assertEqual(got[0][0], "condition")
        self.assertEqual(got[0][1], "While you control this battlefield")
        self.assertNotIn("cost", [k for k, _ in got[:1]])

    def test_real_activated_cost_still_splits(self):
        got = kinds(":rb_energy_1::rb_rune_fury:, Recycle a unit from your "
                    "trash, :rb_exhaust:: Draw 1.")
        self.assertEqual([k for k, _ in got], ["cost", "cost", "cost", "effect"])
        self.assertEqual(got[-1][1], "Draw 1")

    def test_keyword_binder_gates_the_ability_it_marks(self):
        """CR 135.2.e.7: `[>]` binds the keyword to what follows it."""
        got = clauses("[Empowered][>] I have +1 :rb_might:.")
        self.assertEqual(got[0].kind, "keyword")
        self.assertEqual(got[0].bucket, ["Empowered"])
        self.assertEqual(got[1].gate, "Empowered")
        self.assertEqual(got[1].bucket, ["give_might"])

    def test_bracketed_game_action_is_not_a_keyword(self):
        """`[Stun]` is CR 423, not one of the 25 keywords of CR 805-829.

        Peeling it off as a keyword left `a unit` behind as a fragment.
        """
        got = kinds("[Stun] a unit.")
        self.assertEqual(got, [("effect", "Stun a unit")])
        self.assertIn("stun", buckets("[Stun] a unit."))

    def test_unbracketed_keyword_from_errata_text(self):
        """Riot's errata articles drop the brackets: `Ganking (I can move…)`."""
        got = clauses("Ganking (I can move from battlefield to battlefield.)")
        self.assertEqual([(c.kind, c.bucket) for c in got], [("keyword", ["Ganking"])])

    def test_empower_the_action_is_not_empower_the_keyword(self):
        """`Empower` is both CR 441 and CR 827; only one of them is a keyword."""
        got = clauses("Empower me.")
        self.assertEqual(got[0].kind, "effect")
        self.assertIn("empower", got[0].bucket)

    def test_cost_within_an_instruction_splits(self):
        """CR 355.10.c.1's `[do X] to [do Y]`."""
        got = kinds("you may exhaust me to channel 1 rune")
        self.assertEqual(got, [("cost", "you may exhaust me"),
                               ("effect", "channel 1 rune")])

    def test_a_destination_is_not_a_cost(self):
        self.assertEqual(kinds("Move an enemy gear to your base."),
                         [("effect", "Move an enemy gear to your base")])

    def test_additional_cost_is_not_split_at_its_to(self):
        got = kinds("You may pay :rb_energy_1: as an additional cost to play me.")
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0][0], "effect")

    def test_and_joins_instructions_but_not_list_items(self):
        self.assertEqual(len(kinds("Buff me and draw 1.")), 2)
        self.assertEqual(
            len(kinds("Give it +1 :rb_might: for each of the following tags "
                      "among your units — Bird, Cat, Dog, and Poro.")), 1)


class Classification(unittest.TestCase):
    def test_primitives_carry_the_rule_that_defines_them(self):
        by_id = {row[0]: row[1] for row in census.PRIMITIVES}
        self.assertEqual(by_id["draw"], "413")
        self.assertEqual(by_id["pay"], "444")
        # Recall is CR 455, outside the 413-444 game-action block, and is
        # explicitly not a Move (CR 456).
        self.assertEqual(by_id["recall"], "455")
        self.assertNotEqual(by_id["recall"], by_id["move"])

    def test_every_cr_game_action_413_to_444_has_a_primitive(self):
        have = {row[1] for row in census.PRIMITIVES if row[1]}
        missing = [str(n) for n in range(413, 445) if str(n) not in have]
        self.assertEqual(missing, [])

    def test_keyword_kinds_cover_exactly_the_cr_glossary(self):
        self.assertEqual(len(census.KEYWORD_KIND), 25)
        self.assertEqual(sorted(v[0] for v in census.KEYWORD_KIND.values()),
                         [str(n) for n in range(805, 830)])

    def test_triggered_keywords_count_as_triggers(self):
        """CR 808: Deathknell is a Triggered Ability keyword."""
        self.assertIn("Deathknell", census.TRIGGERED_KEYWORDS)
        self.assertNotIn("Ganking", census.TRIGGERED_KEYWORDS)

    def test_fallback_primitives_yield_to_specific_ones(self):
        """`becomes` must not fire alongside a primitive that named the action."""
        self.assertEqual(buckets("Its base Might becomes 5 this turn."), ["set_stat"])
        self.assertNotIn("set_stat", buckets("draw 1"))

    def test_replacement_is_flagged_by_the_words_cr_369_names(self):
        for text, kind in [("give it +4 :rb_might: this turn instead", "instead"),
                           ("If a friendly unit would die", "would"),
                           ("Units you play this turn enter ready", "enters_modified")]:
            hit = [c.replacement for c in clauses(text) if c.replacement]
            self.assertIn(kind, hit, text)


class TheInstrument(unittest.TestCase):
    def test_unclassified_is_reachable(self):
        """The bucket must be able to register a reading.

        If no input can land here, the coverage number in §1 is decoration.
        """
        got = clauses("Flarb the wibbly quux.")
        self.assertEqual([c.kind for c in got], ["unclassified"])
        self.assertEqual(got[0].text, "Flarb the wibbly quux")

    def test_residue_reports_an_unnamed_verb(self):
        res = clauses("Draw 1 and flarb a unit.")[-1].residue
        self.assertIn("flarb", res)

    def test_residue_does_not_report_words_another_table_explains(self):
        """`unit` is a selector, not missing vocabulary."""
        res = clauses("Kill a friendly unit at a battlefield.")[0].residue
        self.assertEqual(res, [])

    def test_report_is_reproducible(self):
        pool, raw = census.load_pool()
        names, version, digest, lists = census.load_gauntlet()
        meta = {"pool": len(pool), "aliases": len(raw), "errata": 0,
                "ambiguous_aliases": 0, "version": version, "digest": digest,
                "lists": lists, "tags": 0}
        a = census.render(census.Census("gauntlet", pool, names),
                          census.Census("all", pool, set(pool)), meta)
        b = census.render(census.Census("gauntlet", pool, names),
                          census.Census("all", pool, set(pool)), meta)
        self.assertEqual(a, b)

    def test_the_field_is_the_one_deck_cli_reports(self):
        names, version, digest, lists = census.load_gauntlet()
        self.assertEqual(version, "gauntlet-2026-09")
        self.assertEqual(lists, 95)
        self.assertEqual(len(names), 396)
        self.assertEqual(len(digest), 12)


if __name__ == "__main__":
    unittest.main()

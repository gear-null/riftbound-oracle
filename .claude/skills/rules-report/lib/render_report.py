"""Render a verified answer.json into a self-contained interactive HTML report.

Design: "Marginalia" — the report IS the rulebook page. Official rule text is the
primary content in document order; the model is demoted to margin notes tethered
to the exact spans it relies on. Verification is not a step the reader performs,
it is the layout.

Grafted in after judging:
  - typed holding line   : the one-line answer decomposes into grounded/inferred
                           spans, each an exact substring, each linking to its note
  - crux + if_false      : exactly one note is load-bearing and says what happens
                           if it is wrong, collapsing the audit from N notes to 1
  - weakest link         : confidence is min() over notes, not an average — a chain
                           is as strong as its weakest step
  - counterargument      : the opposing reading stated at full strength, by rule,
                           then rejected. A reader who has read the contrary rule
                           will not believe the holding until it is confronted.
  - verdict downgrade    : if any note the holding depends on fails verification,
                           the disposition is forced to UNSETTLED. The model must
                           not be able to outrun its own verifier.

file:// constraints respected: no network, no clipboard API (execCommand fallback),
print handler opens <details> and restores their prior state afterwards. The theme is
committed dark rather than following prefers-color-scheme — this document has one
intended appearance on screen and inverts wholesale for paper.
"""
import html, json, os, re, sys
from verify_citations import RuleIndex, verify_citation
from render_rulebook import anchor as rulebook_anchor

# Reports live in reports/, the rulebook in data/ — one copy, linked relatively,
# so the pair keeps working offline and survives being moved or shared together.
RULEBOOK = "../data/rules.html"

BASIS = {
    "grounded":   ("●", "A rule states this in so many words"),
    "structural": ("▲", "No single rule says this; it follows from the rules below"),
    "gap":        ("○", "The rules are silent on this"),
    # Holding spans say "inferred" where notes say "structural" — accept both.
    "inferred":   ("▲", "No single rule says this; it follows from the rules below"),
}
RANK = {"grounded": 3, "structural": 2, "inferred": 2, "gap": 1}

# The disposition is a CSS class as well as a label, so it is a closed set. It
# was unvalidated, and a value containing spaces produced several classes at
# once, quietly disabling the print sheet that is keyed on the same name.
#
# ANSWER is the open-question case: "how much?", "what happens?", "in what
# order?" have no one-word verdict, and forcing one produced a shipped example
# that answered "How much energy does Vi cost?" with YES. The report leads with
# the holding line instead, and prints no plate word at all — which is what
# keeps YES/NO meaningful, because they now only appear where they are real.
DISPOSITIONS = ("YES", "NO", "DEPENDS", "UNSETTLED", "ANSWER")


def esc(s):
    """Escape for HTML, accepting whatever the answer JSON happens to hold.

    `s or ""` was wrong twice over: it raised on a non-string (card stats are
    numbers now) and it blanked a legitimate zero, so a 0-Energy card would
    have rendered with no cost at all.
    """
    return html.escape("" if s is None else str(s), quote=True)


def _check(c, idx, where, problems):
    rid = c["rule"].split(":", 1)[-1]
    doc = c["rule"].split(":", 1)[0] if ":" in c["rule"] else None
    res = verify_citation(idx, rid, c.get("quote"), doc=doc)

    # An unprefixed id resolves in whichever document holds it — 790 ids exist
    # only in TR. Stamping those "CR" put Tournament Rules text in front of a
    # judge labelled Core Rules, with a copy-cite button that said so and a
    # rulebook link to an anchor that does not exist. RuleIndex.get was fixed
    # never to cross documents; `doc or "CR"` reintroduced the same
    # mis-attribution one layer up, so take the doc from the resolved rule.
    # Resolve the doc from the id as WRITTEN, not from the narrowed one.
    # `verify_citation` narrows only within the rule's own document, so the doc
    # cannot change under narrowing — but `idx.get(narrowed_id, None)` is
    # first-hit-wins across documents, so a bare TR id whose narrowed descendant
    # also exists in CR would have flipped to CR, printed CR's ancestry, and
    # stamped it verified. Not reachable in today's corpus (checked: 0 of 790
    # TR-only ids have a CR-first descendant), but one rules update would do it.
    resolved = idx.get(rid, doc) or idx.get(res.cite_as or rid, doc)
    actual_doc = doc or (resolved["doc"] if resolved else None)
    if actual_doc is None:
        actual_doc = "CR"
    elif doc is None and actual_doc != "CR":
        problems.append(
            f'{where}: citation {rid} has no document prefix and exists only in '
            f'{actual_doc} — write it as {actual_doc}:{rid}')
    doc = actual_doc
    # `checked`, not `ok`: a cite with no quote passes `ok` vacuously.
    c["verified"] = res.checked
    if res.ok and not res.checked:
        problems.append(f"{where}: citation {rid} has no quote — the verbatim check never ran")
    c["cite_as"] = f'{doc}:{res.cite_as}'
    # The ORIGIN, not the destination. `cite_as` is overwritten with the
    # narrowed id just above, so recording res.narrowed_to here printed
    # "CR 416.1.b — narrowed from 416.1.b": impossible on its face, and the
    # vague id the model actually wrote was nowhere on the page.
    c["narrowed"] = rid if res.narrowed_to else None
    c["problems"] = res.problems
    if not res.ok:
        problems.append(f'{where}: {"; ".join(res.problems)}')
    # `checked`, not `ok`. The citation stamp already used `checked`, so a
    # quote-less cite rendered a ✗ UNVERIFIED plate beside a note still marked
    # verified and a verdict never downgraded — the two halves of the page
    # disagreeing about the same citation. Omitting the quote is the cheapest
    # way to defeat the verbatim gate; it must not also buy a clean verdict.
    return res.ok and res.checked


def place_spans(line, spans):
    """The single decision about which spans render, and where.

    `_check_holding` used to reason about pairwise first-occurrence ranges while
    `holding_html` placed spans with a monotonic cursor. Two ways of answering
    the same question, so they disagreed: two spans carrying the SAME text, on a
    line where that text occurs once, passed the pairwise guard (which exempts
    identical ranges as harmless) and then lost one to the cursor — rendered as
    unmarked prose, no link, no superscript, zero problems reported.

    Both callers now run this, so a span the renderer will drop is a span the
    verifier has already refused.
    """
    placed, dropped, cur = [], [], 0
    for sp in sorted(spans, key=lambda s: line.find(s.get("text", ""))):
        text = sp.get("text", "")
        i = line.find(text, cur) if text else -1
        if i < 0:
            dropped.append(sp)
            continue
        placed.append((i, sp))
        cur = i + len(text)
    return placed, dropped


# ── checks shared by every document kind ────────────────────────────────
#
# A ruling and a primer are different documents making the same promises about
# provenance, so these run over both. They were inlined in `verify_answer` until
# the primer arrived; extracting them was the alternative to a second copy that
# would drift, which is exactly how three tally comprehensions once disagreed.
# Each keeps the comment recording the defect it exists to prevent.


def check_corpus_stamp(ans, idx, problems):
    """The masthead's "CR 2026-07-16 · TR 2026-07-16" is provenance.

    It came from the answer file — i.e. from the model — with nothing to check
    it against. Every rule in the index carries its own version, so a stamp that
    contradicts the corpus it was verified against is free to detect. With the
    copy-cite date reading from the same block, both provenance claims on the
    page derived from unverified input.
    """
    # `corpus` is model-authored like everything else. `.get("corpus", {}).get`
    # assumed a dict, so `"corpus": "2026-07-16"` — a plausible thing to write —
    # raised AttributeError here, and this runs BEFORE check_required_keys, so
    # the crash pre-empted the very message that would have explained it.
    if ans.get("corpus") is not None and not isinstance(ans.get("corpus"), dict):
        problems.append(
            f'corpus must be an object with CR, TR and generated, not '
            f'{type(ans["corpus"]).__name__}')
        ans["corpus"] = {}

    for key in ("CR", "TR"):
        # Scoped PER DOCUMENT. Built across both and reused, the union let a
        # swapped pair validate: CR stamped with TR's date and vice versa, both
        # wrong for their own document, and the wrong one reaching the copy-cite
        # string this file elsewhere calls "the artifact a judge pastes".
        stamped = {r.get("version") for r in idx.rules.values()
                   if r.get("doc") == key and r.get("version")}
        claimed = ans.get("corpus", {}).get(key)
        if claimed and stamped and claimed not in stamped:
            problems.append(
                f"corpus.{key} claims {claimed}, but this index was built from "
                f'{" / ".join(sorted(stamped))}')


def check_considered_rejected(ans, idx, problems):
    """"Considered and rejected" is read as evidence of thoroughness.

    So an id invented here buys more credibility than one in a note. It reached
    the page entirely unverified: no quote to check, but the rule must at least
    exist and be addressed by the document it names.
    """
    for i, cr in enumerate(ans.get("considered_rejected", []), 1):
        # Untrusted model JSON. A list of bare strings used to raise
        # AttributeError here, and the crash hid every problem found after it —
        # including a hallucinated quote in a note.
        if not isinstance(cr, dict):
            problems.append(
                f"considered_rejected {i}: expected an object with `rule` and "
                f"`why`, got {type(cr).__name__}")
            continue
        ref = str(cr.get("rule", ""))
        # `why` is rendered beside the rule and was validated nowhere, so an
        # entry with only a `rule` verified clean and printed an em-dash into
        # empty space — "considered and rejected" is read as evidence of
        # thoroughness, and a blank reason is the cheapest possible way to buy it.
        if not str(cr.get("why", "")).strip():
            problems.append(f"considered_rejected {i}: no `why` — a rule id with "
                            "no reason beside it is not evidence of anything")
        cdoc, crid = (ref.split(":", 1) if ":" in ref else (None, ref))
        if not crid:
            problems.append(f"considered_rejected {i}: no rule id")
            continue
        # Resolved WITHOUT the doc filter first, so a wrong prefix reports the
        # real document instead of "does not exist" — `idx.get` already filters
        # by doc, which made the mismatch branch unreachable.
        found = idx.get(crid, cdoc) or idx.get(crid, None)
        if not found:
            problems.append(
                f"considered_rejected {i}: {ref} does not exist at this corpus version")
        elif cdoc and found["doc"] != cdoc:
            problems.append(
                f'considered_rejected {i}: {ref} is in {found["doc"]}, not {cdoc}')
        elif not cdoc and found["doc"] != "CR":
            # Same rule the citation path enforces: 790 ids exist only in TR, and
            # a bare one reads as CR to every reader of the page.
            problems.append(
                f'considered_rejected {i}: {ref} exists only in {found["doc"]} — '
                f'write it as {found["doc"]}:{ref}')


def check_card_sections(ans, idx, problems):
    """Every rule id a resolved card links to must exist at this corpus version."""
    for c in resolve_cards(ans):
        for sec in (c.get("rule_sections") or []):
            if isinstance(sec, str) and not idx.get(str(sec), "CR"):
                problems.append(
                    f'card {c.get("name", "?")}: rule_sections names {sec}, which '
                    "does not exist at this corpus version")


def check_rules_checked(items, idx, problems, label=None):
    """`rules_checked` is the evidence an abstention offers for itself.

    A fabricated id here buys the strongest claim in the document: that the
    rules do not address something. It was rendered as "Rules searched" without
    ever being checked.

    Runs over a ruling's notes, a primer's steps AND a primer's transitions —
    and transitions carry no `id`, so `item.get("id", "?")` reported every one
    of them as `?: rules_checked names ...`, unattributable. `label` supplies
    the name the caller already knows ("s2 transition 1"), which is the same
    string it passes to `_check` two lines earlier.
    """
    for n, item in enumerate(items, 1):
        where = label(n) if callable(label) else (label or item.get("id", "?"))
        # Normalised here, in the one function that already walks these, so no
        # document kind can verify a list it then cannot render. `rules_checked`
        # is rendered with " · ".join(), which needs strings — and this check
        # str()s each ref for the lookup, so a list of plain integers verified
        # clean and died in the renderer. The verifier certifying an answer it
        # cannot render is the two halves disagreeing about what a valid answer
        # is, and rc=0 is what the product sells.
        refs = [str(x) for x in (item.get("rules_checked") or [])]
        if refs:
            item["rules_checked"] = refs
        elif "rules_checked" in item:
            item.pop("rules_checked")
        for ref in refs:
            rdoc, rrid = (ref.split(":", 1) if ":" in ref else (None, ref))
            if not rrid or not idx.get(rrid, rdoc):
                problems.append(
                    f"{where}: rules_checked names {ref}, which does not "
                    "exist at this corpus version")


def check_unique_ids(items, label, problems):
    """Ids are the addressing scheme, so they have to be unique.

    Every anchor on the page is `#<id>`, and a browser resolves a repeated id to
    the FIRST match — so a duplicate silently sent every superscript and rail row
    to the wrong item, while the verifier validated against the second.
    """
    ids = [n.get("id") for n in items]
    dupes = sorted({i for i in ids if i and ids.count(i) > 1})
    if dupes:
        problems.append(
            f"duplicate {label} id(s) {', '.join(dupes)} — every link to them "
            "resolves to the first, so the others are unreachable")


def check_required_keys(ans, keys, problems):
    """Keys a document cannot be missing and still mean anything.

    On the ruling path these are also the keys `render` subscripts, so the check
    is what stops a KeyError halfway through writing the page — the verifier
    certifying an answer it cannot render is the two halves disagreeing about
    what a valid answer is, and rc=0 is what the product sells.

    The primer reads three of its four with `.get`, deliberately: `--force`
    exists to look at a document this check has already rejected, so the
    renderer must survive their absence. There the check is about meaning, not
    about crashing — a primer with no `topic` is not a primer.
    """
    for key in keys:
        if key not in ans:
            problems.append(f"answer is missing required key {key!r}")
    for key in ("CR", "TR", "generated"):
        if isinstance(ans.get("corpus"), dict) and key not in ans["corpus"]:
            problems.append(f"corpus.{key} is missing")


def check_cites(item, where, problems):
    """Drop citations that are not shaped like citations, after reporting them.

    `cites` was the one untrusted list nothing guarded. A bare string raised
    TypeError inside `_check` and an entry with no `rule` raised KeyError — and
    because both abort verification where they occur, every problem found after
    them was never printed, including a hallucinated quote two notes down. The
    same reasoning already applies to `considered_rejected` and to a primer's
    steps: report, drop, keep checking.
    """
    cites = item.get("cites")
    if cites is None:
        return []
    if not isinstance(cites, list):
        problems.append(f"{where}: `cites` must be a list of "
                        '{"rule": ..., "quote": ...} objects, not '
                        f"{type(cites).__name__}")
        item["cites"] = []
        return []
    kept = []
    for i, c in enumerate(cites, 1):
        if not isinstance(c, dict):
            problems.append(f"{where}: citation {i} is a {type(c).__name__}, not an "
                            'object with `rule` and `quote`')
        elif not str(c.get("rule", "")).strip():
            problems.append(f"{where}: citation {i} names no rule")
        else:
            kept.append(c)
    item["cites"] = kept
    return kept


def _check_holding(ans):
    """Enforce the holding line's invariants.

    Evaluation showed error concentrating here: answers with a correct body and
    a loose one-line summary. The holding line is the part most people read, so
    it gets checked hardest. Previously a span that wasn't a substring was
    silently skipped at render time — a wrong claim rendered as plain prose.
    """
    problems = []
    h = ans.get("holding", {})
    line = h.get("line", "")
    spans = h.get("spans", [])
    by_id = {n["id"]: n for n in ans["notes"]}

    if not line:
        return ["holding.line is empty"]
    if not spans:
        return ["holding.line has no typed spans — the summary is unaccountable prose"]

    covered = 0
    for sp in spans:
        # Spans are model-generated too. Note bases are validated and coerced
        # a few lines below; spans were not, so an unknown value reached
        # holding_html and raised KeyError mid-render.
        if sp.get("basis") not in BASIS:
            problems.append(
                f'holding span "{str(sp.get("text", ""))[:30]}" has unknown basis '
                f'{sp.get("basis")!r}')
            sp["basis"] = "inferred"
        text = sp.get("text", "")
        if text not in line:
            problems.append(f'holding span "{text[:40]}" is not a substring of holding.line')
            continue
        # No pairwise overlap reasoning here. It compared FIRST occurrences
        # while placement uses a monotonic cursor, so the two disagreed and it
        # rejected answers the renderer places perfectly — telling the author to
        # "make the spans disjoint" when they already were. The place_spans
        # backstop below is the single authority, as round 3 intended.
        covered += len(text)

        note = by_id.get(sp.get("note"))
        if not note:
            problems.append(f'holding span "{text[:30]}" points at unknown note {sp.get("note")}')
            continue
        # A span may not claim more support than the note it rests on.
        # A span may never claim MORE support than the note it rests on. The
        # guard used to fire only for `grounded`, so an inferred span over a gap
        # note rendered "it follows from the rules below" against "the rules are
        # silent on this" — a RANK 1 -> 2 upgrade on the line everyone reads.
        if note and RANK.get(sp.get("basis"), 0) > RANK.get(note.get("basis"), 0):
            problems.append(
                f'holding span "{text[:30]}" claims {sp.get("basis")} but '
                f'{note["id"]} is {note.get("basis")}')
        if sp.get("basis") == "grounded":
            if note["basis"] != "grounded":
                problems.append(
                    f'holding span "{text[:30]}" claims grounded but {note["id"]} is {note["basis"]}')
            elif not note.get("verified", True):
                problems.append(
                    f'holding span "{text[:30]}" claims grounded but {note["id"]} has a failed citation')

    # Whatever the pairwise reasoning above concluded, this is the authority:
    # any span the renderer cannot place would render as unmarked prose.
    # Identical duplicate spans reach here having passed every earlier guard,
    # because the overlap test exempts identical ranges as harmless — they are
    # harmless to that test and fatal to the placement cursor.
    for sp in place_spans(line, spans)[1]:
        problems.append(
            f'holding span "{str(sp.get("text", ""))[:30]}" cannot be placed — '
            "it duplicates or overlaps another span; only one would render")

    # Substantive uncovered text is where loose summaries hide.
    words = len([w for w in line.split() if len(w) > 3])
    if words and covered / max(len(line), 1) < 0.30:
        problems.append(
            f"holding.line is only {covered * 100 // max(len(line), 1)}% covered by typed spans — "
            "decompose the claim rather than asserting it as prose")
    return problems


def verify_answer(ans, idx):
    """Verify EVERY citation in the document, narrow vague ones, grade each note.

    Counterargument citations get the same treatment as supporting ones — an
    unverified contrary rule is at least as dangerous, since it is the text a
    skeptical reader will go check first.
    """
    problems = []
    # The answer is model-generated JSON, i.e. untrusted input. Coerced BEFORE
    # anything reads note["basis"] — the gap-note check below and _check_holding
    # both do, so a note missing the key raised KeyError mid-verification and
    # produced no report at all. The span-level guard was already placed before
    # its first use; this was the one spot where the pattern stayed inverted.
    # A crash means no report, and anyone who later wraps this in try/except
    # turns the verifier into a no-op.
    for n in ans["notes"]:
        if n.get("basis") not in RANK:
            problems.append(f'{n.get("id", "?")}: unknown basis {n.get("basis")!r}')
            n["basis"] = "gap"

    for note in ans["notes"]:
        note_ok = True
        for c in note.get("cites", []):
            if not _check(c, idx, note["id"], problems):
                note_ok = False
        note["verified"] = note_ok
        # Abstention is held to the same standard as assertion: a note claiming
        # the rules are silent must show what it searched.
        if note["basis"] == "gap" and not note.get("rules_checked"):
            problems.append(f'{note["id"]}: gap note must list rules_checked')
        # GROUNDED specifically. Omitting the quote was already refused as the
        # cheapest way to defeat the verbatim gate; omitting the whole citation
        # is cheaper still, and bought the stamp "● grounded — a rule states
        # this in so many words" on a note showing no rule at all.
        #
        # Scoped to `grounded` because the other two bases legitimately assert
        # without a rule of their own: `structural` means "no single rule says
        # this; it follows from the rules below", which may be the rules cited
        # by NEIGHBOURING notes, and `gap` pays for its abstention with
        # rules_checked above. Grounded has no such out — it is the claim that a
        # rule says it, so it must show the rule.
        if note["basis"] == "grounded" and not note.get("cites"):
            problems.append(
                f'{note["id"]}: basis \'grounded\' asserts a rule states this, '
                "but cites none")
            note_ok = False
            note["verified"] = False
        if note.get("crux") and not note.get("if_false"):
            problems.append(f'{note["id"]}: crux note must state if_false')

    # A fabricated counterargument citation is at least as dangerous as a
    # fabricated supporting one — it is the text a sceptical reader checks
    # first. Previously its result was computed and then discarded.
    ca_failed = False
    for i, ca in enumerate(ans.get("counterargument", []), 1):
        for c in ca.get("cites", []):
            if not _check(c, idx, f"counterargument {i}", problems):
                ca_failed = True

    check_corpus_stamp(ans, idx, problems)

    check_considered_rejected(ans, idx, problems)

    # Each of these carries its reason in its own docstring now. Three of the
    # comments stayed behind when the bodies moved and ended up labelling the
    # call that happened to follow them — the `rules_checked` narrative sat over
    # check_card_sections, and the "keys render() subscripts" narrative over the
    # disposition check, which is a closed-set validation and not that at all.
    # A comment attached to the wrong statement is worse than none: it is read.
    check_card_sections(ans, idx, problems)
    check_rules_checked(ans["notes"], idx, problems)
    check_unique_ids(ans["notes"], "note", problems)

    # The disposition is a CSS class as well as a label, so it is a closed set.
    # An unvalidated value containing spaces produced several classes at once
    # and quietly disabled the print sheet keyed on the same name.
    _disp = ans.get("holding", {}).get("disposition")
    if _disp not in DISPOSITIONS:
        problems.append(
            f"holding.disposition is {_disp!r}; it must be one of "
            f"{', '.join(DISPOSITIONS)} — it is a CSS class as well as a label")

    check_required_keys(ans, ("question", "corpus"), problems)
    for n in ans["notes"]:
        if not n.get("claim"):
            problems.append(f'{n.get("id", "?")}: no claim')
        # Rendered with " · ".join(), which needs strings.
        n["rules_checked"] = [str(x) for x in (n.get("rules_checked") or [])] or None
        if n["rules_checked"] is None:
            n.pop("rules_checked")

    cruxes = [n["id"] for n in ans["notes"] if n.get("crux")]
    if len(cruxes) != 1:
        problems.append(f"exactly one note must be crux, found {len(cruxes)}: {cruxes or 'none'}")

    problems += _check_holding(ans)

    notes = ans["notes"]
    if not notes:
        problems.append("answer has no notes")
        ans["_weakest"], ans["_strength"] = "-", "gap"
        ans["_problems"] = problems
        # Guarded exactly as the load-bearing branch below is. Setting _forced
        # unconditionally made an answer that was ALREADY UNSETTLED render the
        # banner "forced to UNSETTLED (was UNSETTLED)", which reads as a
        # verification failure rather than an author's honest abstention.
        if ans["holding"]["disposition"] != "UNSETTLED":
            ans["holding"]["_forced"] = ans["holding"]["disposition"]
            ans["holding"]["disposition"] = "UNSETTLED"
        return ans
    # Gap notes INCLUDED. They were excluded, which made the verdict plate and
    # the rail both overstate: an answer with nine grounded notes and one gap
    # reported a grounded weakest link while printing the ○ Gap row beside it.
    # RANK scores gap below structural for exactly this comparison, and both
    # SKILL.md and this module's docstring say min() over notes. A gap in the
    # chain is a gap in the chain.
    graded = notes
    weakest = min(graded, key=lambda n: RANK[n["basis"]])
    ans["_weakest"] = weakest["id"]
    ans["_strength"] = weakest["basis"]

    # The model must not outrun its verifier.
    load_bearing_failed = any(not n["verified"] for n in notes) or ca_failed
    if load_bearing_failed and ans["holding"]["disposition"] != "UNSETTLED":
        ans["holding"]["_forced"] = ans["holding"]["disposition"]
        ans["holding"]["disposition"] = "UNSETTLED"
    ans["_problems"] = problems
    return ans


def all_cites(ans):
    """Every citation the verifier checked — the notes' AND the counterargument's.

    One definition, because three copies of this comprehension had already
    drifted apart. `render` counted both sources; `main`'s console summary and
    `rules_cli.cmd_verify` counted only the notes, so the same answer file
    reported "9/9 verified" on the terminal and "12/12" in the headline of the
    report it had just written.

    Both sources belong in the tally: a failed counterargument cite forces
    UNSETTLED exactly as a failed note cite does, so a metric that omits it can
    read all-clear on a report the verifier demonstrably rejected.
    """
    return [c for src in list(ans["notes"]) + list(ans.get("counterargument", []))
            for c in src.get("cites", [])]


def note_number(note_id):
    """"n12" -> "12". Falls back to the raw id for anything unnumbered."""
    digits = "".join(ch for ch in str(note_id) if ch.isdigit())
    return digits or str(note_id)


def holding_html(h):
    """Type the holding line: every span must be an exact substring of the line.

    Each span carries a superscript note number, the way a citation works in
    prose. Previously the only marker was a `⌁` on inferred spans, so a reader
    could see THAT a claim was underwritten but not WHICH note underwrote it —
    the link existed, but its destination was invisible until clicked.
    """
    line, spans = h["line"], h.get("spans", [])

    # Walk the line in DOCUMENT order, not the order the model happened to list
    # spans in. A monotonic cursor silently dropped any span written out of
    # order: viktor-answer.json lists "Zero Recruits" third though it opens the
    # line, so the literal answer to the question rendered as unmarked prose —
    # no link, no superscript, and it was the crux and the weakest link.
    placed, _dropped = place_spans(line, spans)

    out, cur = [], 0
    for i, sp in placed:
        out.append(esc(line[cur:i]))
        # A `gap` span used to fall into the sp-inferred branch: the rules are
        # silent on this, drawn with the dotted blue mark that means "it follows
        # from the rules below" — a strength upgrade (RANK 1 -> 2) on the one
        # line everyone reads, and one that now contradicts the key's ○ Gap row.
        cls = {"grounded": "sp-grounded", "gap": "sp-gap"}.get(sp["basis"], "sp-inferred")
        # The glyph still separates basis at a glance, for a reader who is not
        # going to chase the number.
        glyph = {"grounded": "", "gap": "○"}.get(sp["basis"], "⌁")
        num = note_number(sp["note"])
        out.append(
            f'<a class="{cls}" href="#{esc(sp["note"])}" '
            f'title="{esc(BASIS[sp["basis"]][1])} — see note {esc(num)}">'
            f'{esc(sp["text"])}</a>'
            f'<a class="noteref" href="#{esc(sp["note"])}" '
            f'aria-label="note {esc(num)}"><sup>{esc(glyph)}{esc(num)}</sup></a>'
        )
        cur = i + len(sp["text"])
    out.append(esc(line[cur:]))
    return "".join(out)


def cite_html(c, idx, corpus):
    rid = c["cite_as"].split(":", 1)[-1]
    doc = c["cite_as"].split(":", 1)[0]
    chain = idx.ancestry(rid, doc)
    stamp = ("verified" if c["verified"] else "UNVERIFIED")
    scls = "ok" if c["verified"] else "bad"
    narrow = (f'<div class="narrowed">narrowed from {esc(c["narrowed"])} — '
              f'now cites the tightest rule that says it</div>' if c.get("narrowed") else "")
    probs = "".join(f'<div class="prob">{esc(p)}</div>' for p in c.get("problems", [])
                    if not p.startswith("cite narrowed"))
    # The date comes from the answer's corpus block, like the masthead. It was
    # a hardcoded literal, so the next rules update would have moved the
    # masthead while every copy-cite button kept asserting the old version —
    # and the copy-cite string is the artifact a judge pastes into a dispute.
    # NOT `or next(iter(corpus.values()))`. corpus holds `generated` alongside
    # CR/TR, so a dict-order fallback asserted the report's build date as the
    # rules version. An unstated version must read as unstated: this string is
    # what a judge pastes into a dispute, so a wrong date is worse than none.
    dated = corpus.get(doc) or "version unstated"
    full = f'{doc} {rid} ({"Core Rules" if doc == "CR" else "Tournament Rules"}, {dated}): "{c.get("quote","")}"'
    # Every ancestor row links to its own anchor, not just the cited rule: the
    # useful move after reading a citation is usually "show me the parent".
    anchored = "".join(
        f'<li class="{"anc-target" if r["id"] == rid else ""}" style="--d:{r["depth"]}">'
        f'<a class="anc-link" href="{RULEBOOK}#{esc(rulebook_anchor(doc, r["id"]))}">'
        f'<code>{esc(r["id"])}</code></a> <span>{esc(r["text"])}</span></li>'
        for r in chain
    )
    # The stamp reads the same in colour and in greyscale: verified carries a
    # check on a hairline plate, UNVERIFIED inverts to solid Mist on Ink. A
    # reader who cannot separate the two hues still cannot miss the failure.
    tick = "&#10003;" if c["verified"] else "&#10007;"
    return f'''<details class="cite plate">
<summary><code class="cite-id">{esc(doc)} {esc(rid)}</code>
  <span class="stamp {scls}">{tick} {stamp}</span></summary>
<div class="cite-body">
{narrow}{probs}
<ol class="ancestry">{anchored}</ol>
<div class="cite-actions">
  <a class="rulebook-link" href="{RULEBOOK}#{esc(rulebook_anchor(doc, rid))}"
     title="Open {esc(doc)} {esc(rid)} in the full rulebook">Open in rulebook &rarr;</a>
  <button class="copy" data-cite="{esc(full)}">Copy cite</button>
</div>
</div></details>'''


LEGEND_MARKER = "<!--LEGEND-->"

# Viewers that render untrusted HTML — Claude Desktop's preview, artifact panes —
# apply a CSP that blocks remote images, so a linked card renders as the
# "artwork offline" placeholder even though the network is fine. Inlining the
# bytes makes the report self-contained and therefore viewable anywhere, at the
# cost of roughly 1MB per card. Off by default: a local browser loads the URL
# happily and a lean file is nicer to keep.
EMBED_ART = os.environ.get("RIFTBOUND_EMBED_ART", "").lower() in ("1", "true", "yes")


def embed_image(url, timeout=15):
    """Fetch an image and return it as a data: URI, or None on any failure.

    Never raises and never blocks for long: artwork is a nicety, and a report
    that fails to render because a CDN was slow would be a much worse trade.
    """
    if not url:
        return None
    try:
        import base64, urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "riftbound-oracle"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            blob = resp.read()
        ctype = "image/png" if url.lower().split("?")[0].endswith(".png") else "image/jpeg"
        return f"data:{ctype};base64,{base64.b64encode(blob).decode('ascii')}"
    except Exception:
        return None


def legend_html(page_html, idx):
    """A key to the bracketed shorthand this report actually uses.

    Built from the finished page rather than from the answer object, so it
    covers every token a reader can see — quoted rule text and card text
    included, not just what the model wrote.

    Deliberately a key, not a substitution: `[A]` stays `[A]` in the text. The
    point is a reader who gradually stops needing the legend and can then read
    Riot's own PDFs unaided, which replacing the shorthand with glyphs would
    quietly prevent.
    """
    from symbols import build_legend, is_number_token, number_rule, scan

    legend = build_legend(list(idx.rules.values()))
    # Unescape after stripping tags: the keyword marker [>] is written into the
    # page as `[&gt;]`, so scanning the raw HTML silently never matched it —
    # the one symbol a reader is least likely to guess.
    # Strip script/style BODIES first. Removing only tags left their text
    # content in the scan, and the overlay JS contains `m[1]` and `m[2]` — so
    # every report shipped a fabricated "[1] · [2] = that much Energy" row
    # citing CR 429.5, for symbols that appear nowhere on the page. A legend
    # entry is a citation; inventing one is the failure this project exists to
    # prevent.
    body = re.sub(r"<(script|style)\b.*?</\1>", " ", page_html, flags=re.S | re.I)
    visible = html.unescape(re.sub(r"<[^>]+>", " ", body))
    used = scan(visible, legend)
    if not used:
        return ""

    def row(token, meaning, rule, colour):
        style = f' style="color:{colour}"' if colour else ""
        link = (f'<a class="sym-rule" href="{RULEBOOK}#{esc(rulebook_anchor("CR", rule))}">'
                f'CR {esc(rule)}</a>')
        return (f'<div class="sym-row"><code class="sym"{style}>[{esc(token)}]</code>'
                f'<span class="sym-mean">{esc(meaning)}</span>{link}</div>')

    rows = []
    # Numbers first — the most common token and the least guessable. Shown as
    # the literal amounts on the page rather than an "[N]" placeholder, so the
    # key needs no convention of its own to decode.
    for token in sorted((t for t in used if is_number_token(t)), key=int):
        amount = int(token)
        # Dropped rather than cited to a rule that no longer defines this.
        _nr = number_rule(idx)
        if not _nr:
            continue
        rows.append(row(token, f"{amount} Energy", _nr, None))
    for token in sorted(t for t in used if not is_number_token(t)):
        e = legend[token]
        rows.append(row(token, e["meaning"], e["rule"], e["colour"]))

    return (
        '<h2 id="symbols" data-od-id="sec-symbols">Symbols used here</h2>'
        '<div class="legend plate">' + "".join(rows) + "</div>"
        '<p class="legend-note">Shorthand is left as Riot prints it, so this key '
        'becomes unnecessary with use. Each entry links to the rule that defines it.</p>'
    )


def resolve_cards(ans):
    """Turn the answer's `cards` list into renderable card records.

    The agent supplies names — `"cards": ["Astral Heron"]` — and lookup happens
    here against the skill's vendored card data. That split is deliberate: the
    agent should not be inventing artwork URLs or retyping printed text, which
    are exactly the things it would get subtly wrong.

    A name that does not resolve is kept and marked, never dropped. Silently
    omitting a card the answer discusses would leave the reader thinking the
    card was never considered.
    """
    names = ans.get("cards") or []
    if not names:
        return []

    # A failure to LOAD the card data is not a statement about any card. It
    # used to be one: every name then missed the lookup and rendered "not found
    # — no card by this name", which asserts the card does not exist in
    # Riftbound. A reader would go and re-type the name. SKILL.md forbids the
    # model from converting a data gap into a rules gap; the renderer must not
    # do it either. Kept non-fatal — the rules argument above is unaffected and
    # is the part worth reading — but said plainly, and on stderr so whoever
    # generated it knows the corpus is the problem and not their spelling.
    bridge, unavailable = None, ""
    try:
        from card_bridge import CardBridge
        bridge = CardBridge()
    except (Exception, SystemExit) as err:
        unavailable = f"{type(err).__name__}: {err}"
        print(f"  card data could not be loaded ({unavailable}) — "
              "card panels will say so rather than report the cards missing",
              file=sys.stderr)

    # The realistic failure is not an exception. `corpus.load_cards` swallows
    # OSError and ValueError and returns {}, so a deleted, empty or corrupt
    # cards.json builds a CardBridge with an EMPTY index that falls straight
    # through to "no card by this name" — the guard above never fires. An empty
    # index is a data failure, not 1037 simultaneous typos.
    if bridge is not None and not getattr(bridge, "cards", None):
        unavailable = "card data is missing, empty or unreadable"
        bridge = None
        print(f"  {unavailable} — card panels will say so rather than report "
              "the cards missing", file=sys.stderr)

    out = []
    for entry in names:
        # Accept a bare name or an object. An object is still looked up and
        # ENRICHED rather than passed through: a hand-written entry that
        # predates the card data would otherwise render "no artwork" beside a
        # card whose art we hold, which reads as a missing image rather than as
        # a stale answer file.
        supplied = entry if isinstance(entry, dict) else {}
        name = str(supplied.get("name") or (entry if not isinstance(entry, dict) else ""))
        if not name:
            out.append({"name": "(unnamed card entry)", "unresolved": True})
            continue

        card = bridge.cards.get(name.lower()) if bridge else None
        if card:
            resolved = bridge.card_terms(card)
            # Anything explicitly supplied wins; the lookup only fills gaps.
            # FILL, never override. The lookup is exact and the record is
            # vendored from Riot's data; a supplied field that disagrees is
            # either stale or invented, and SKILL.md tells the author not to
            # supply text or images at all ("those are exactly the fields you
            # would get subtly wrong"). Overriding let an answer render an
            # invented ability beside genuine artwork, under an errata banner
            # claiming the fabrication was the corrected wording.
            for k, v in supplied.items():
                if not v or resolved.get(k):
                    continue
                # Shape matters: `rule_sections` is iterated and `stats` is
                # keyed, so a string here renders one link per CHARACTER —
                # "829" became three links to CR-8, CR-2 and CR-9.
                if k == "stats" and not isinstance(v, dict):
                    continue
                if k == "rule_sections" and not isinstance(v, (list, tuple)):
                    continue
                resolved[k] = v
            out.append(resolved)
        elif supplied:
            # An object for a card that does not exist is still a nonexistent
            # card. Passing it through rendered an invented card as real,
            # which is precisely what find_cards refuses to do for names.
            supplied = dict(supplied)
            supplied["unresolved"] = True
            if unavailable:
                supplied.pop("unresolved")
                supplied["unavailable"] = unavailable
            out.append(supplied)
        elif unavailable:
            out.append({"name": name, "unavailable": unavailable})
        else:
            out.append({"name": name, "unresolved": True})
    return out


def stats_html(stats):
    """Numbers and classifications as a row of chips.

    These arrived as a markdown string once — `**Energy:** 4 | **Might:** 3` —
    and rendered with the asterisks showing, because nothing here parses
    markdown. They are structured now, so presentation is a layout decision.
    """
    # An answer file may supply a card object, so this is untrusted input like
    # everything else here. A crash means no report at all, and iterating a
    # string domain produced one chip per LETTER — four "classifications"
    # reading F, u, r, y.
    if not isinstance(stats, dict):
        return ""
    chips = []
    for key, label in (("energy", "Energy"), ("might", "Might"), ("power", "Power")):
        v = stats.get(key)
        if isinstance(v, bool) or v is None:
            continue
        chips.append(f'<span class="chip"><b>{esc(v)}</b> {esc(label)}</span>')
    for key in ("type", "rarity"):
        v = stats.get(key)
        if v and isinstance(v, str):
            chips.append(f'<span class="chip chip-q">{esc(v)}</span>')
    dom = stats.get("domain")
    for d in ([dom] if isinstance(dom, str) else (dom or [])):
        if isinstance(d, str) and d:
            chips.append(f'<span class="chip chip-d">{esc(d)}</span>')
    return f'<span class="card-stats">{"".join(chips)}</span>' if chips else ""


def card_notice(c):
    """The "do not trust this text" banners under a card's printed rules text.

    The two are INDEPENDENT and can both apply: a card can be erratum'd by a
    rules update AND have text the API serves short. Assigning the second
    instead of appending it dropped the errata notice on exactly those cards,
    telling the reader the text was merely incomplete when it was also stale.
    """
    out = ""
    if c.get("errata"):
        out += (f'<span class="card-errata">Text updated by {esc(c["errata"])} — '
                "the card database still serves the older wording.</span>")
    # Coerced: a bare string iterates per CHARACTER and rendered
    # "This name matches 3 cards — Z, e, d." Same defect already closed for
    # `stats` and `rule_sections`.
    amb = c.get("ambiguous") or []
    if isinstance(amb, str):
        amb = [amb]
    if len(amb) > 1:
        others = ", ".join(str(n) for n in amb)
        # Names the printing actually shown, and says ABOVE — the notice is the
        # last element in the panel, so "shown below" pointed at nothing.
        out += (f'<span class="card-gap">This name matches {len(amb)} cards — '
                f'{esc(others)}. Shown above is <b>{esc(str(c.get("name", "")))}</b>'
                " — check the answer means that one.</span>")
    if c.get("incomplete"):
        out += (f'<span class="card-gap">Printed text incomplete — {esc(c["incomplete"])}. '
                "Read it from the card image.</span>")
    return out


def cards_html(ans):
    """Card artwork beside printed text, for every card the answer names.

    Artwork is referenced by URL from Riot's CDN, never copied into the repo.
    A missing image degrades to a labelled placeholder rather than a broken
    <img>; remote URLs are fine because these reports are local files.
    """
    cards = resolve_cards(ans)
    if not cards:
        return ""
    out = []
    for c in cards:
        img = c.get("image")
        if img and EMBED_ART:
            # The fallback to the remote URL stays — a report that fails to
            # render because a CDN was slow is a worse trade, as embed_image
            # says. But it is not silent: EMBED_ART is set precisely BECAUSE
            # the reader's viewer blocks remote images, so falling back hands
            # them the "artwork offline" placeholder the flag existed to
            # prevent, with nothing to explain why it did not work.
            embedded = embed_image(img)
            if not embedded:
                print(f"  could not embed artwork for {c.get('name', '?')} — "
                      "falling back to the CDN URL, which a viewer that blocks "
                      "remote images will not load", file=sys.stderr)
            img = embedded or img
        if c.get("unavailable"):
            art = (
                '<div class="card-art card-art--none">data unavailable'
                "<span>the card database did not load — this is not a "
                "statement about the card</span></div>"
            )
        elif c.get("unresolved"):
            art = (
                '<div class="card-art card-art--none">not found'
                "<span>no card by this name</span></div>"
            )
        elif img:
            # Artwork lives on Riot's CDN, so an offline reader has a URL that
            # cannot load. Without a handler the <img> collapsed to a ~26px
            # strip of alt text; the documented "labelled placeholder" only
            # ever appeared when the URL was absent entirely.
            art = (
                f'<img class="card-art" src="{esc(img)}" alt="{esc(c["name"])} card artwork"'
                ' loading="lazy" referrerpolicy="no-referrer"'
                ' onerror="this.replaceWith(Object.assign(document.createElement(\'div\'),'
                '{className:\'card-art card-art--none\',textContent:\'artwork offline\'}))">'
            )
        else:
            art = (
                '<div class="card-art card-art--none">no artwork'
                "<span>rebuild with <code>oracle skill-data</code></span></div>"
            )

        # Keywords a card prints map onto glossary sections; linking them lets a
        # reader jump from "[Equip]" straight to the rule defining Equip.
        secs = "".join(
            f'<a class="card-rule" href="{RULEBOOK}#{esc(rulebook_anchor("CR", s))}">{esc(s)}</a>'
            for s in (c.get("rule_sections") or [])
        )
        secs = f'<span class="card-rules">governed by {secs}</span>' if secs else ""

        # The artwork sits directly beside this text. Where the source data is
        # short, the two visibly disagree, so the panel has to say which one is
        # incomplete rather than letting the reader assume the text is whole.
        gap = card_notice(c)

        # Model-generated JSON: the name key exists but need not be a string.
        slug = re.sub(r"[^a-z0-9]+", "-", str(c.get("name", "")).lower()).strip("-") or "card"
        out.append(
            f'<figure class="card plate" data-od-id="card-{esc(slug)}">' + art
            + '<figcaption>'
            + f'<b class="card-name">{esc(c["name"])}</b>'
            + stats_html(c.get("stats"))
            + f'<span class="card-text">{esc(c.get("text", ""))}</span>'
            + gap + secs + "</figcaption></figure>"
        )
    return ('<h2 id="cards" data-od-id="sec-cards">Cards referenced</h2>'
            '<div class="cards">' + "".join(out) + "</div>")


# The identity mark, inlined so the report stays one file. Original geometry —
# a chamfered bezel, a gold shell with a Mist specular arc, a Mind Blue core —
# deliberately derivative of the Runeterra register without reproducing any of
# Riot's marks. See the design system's logo usage rules.
# The masthead carries ONE element for the portable copy, in one of three
# states. The renderers emit the "not built" form; `attach_portable` upgrades
# it to a link once the sibling file exists; `export` rewrites it to a badge so
# the portable copy does not link to a sibling it may have travelled without.
# Matched by id rather than by state, because standalone `export` can be run on
# a report that has already been upgraded.
PORTABLE_SLOT = re.compile(r'<(a|span) class="portable[^"]*" id="portable"[^>]*>.*?</\1>', re.S)


def portable_link(portable_name):
    """The masthead control, once the portable sibling exists.

    `download` so a click SAVES the file rather than navigating into it — the
    reader wants something to send, not a second tab that looks identical to the
    one they are on. The href is relative and bare because both files live in
    the same reports/ directory, and that is the only layout `report` writes.
    """
    return (f'<a class="portable is-built" id="portable" href="{portable_name}" '
            f'download="{portable_name}" title="One self-contained file: every cited '
            f'rule and card image travels inside it">Portable copy &#8595;</a>')


def portable_note(stem):
    """The masthead control when no portable sibling could be built."""
    return (f'<span class="portable is-unbuilt" id="portable" title="Artwork could not be '
            f'fetched, so no self-contained copy was written">portable copy not built '
            f'&mdash; <code>rules_cli.py export {stem}.html</code></span>')


PORTABLE_BADGE = '<span class="portable is-portable" id="portable">portable copy</span>'


MARK = (
    '<svg class="mark" viewBox="0 0 96 96" role="img" aria-label="Riftbound Oracle">'
    '<path d="M22 10 L74 10 L86 22 L86 74 L74 86 L22 86 L10 74 L10 22 Z" fill="none"'
    ' stroke="#c8aa6e" stroke-width="2.5"/>'
    '<circle cx="48" cy="48" r="25" fill="none" stroke="#c8aa6e" stroke-width="3"/>'
    '<path d="M30.61 43.34 A18 18 0 0 1 43.34 30.61" fill="none" stroke="#e4f1f5"'
    ' stroke-width="3" stroke-linecap="round"/>'
    '<path d="M48 37 L50.4 45.6 L59 48 L50.4 50.4 L48 59 L45.6 50.4 L37 48 L45.6 45.6 Z"'
    ' fill="#3c8fe0"/></svg>'
)

# The 24px cut of the same mark: below 48px the meridian and pips close up, so
# only the chamfered bezel and the core survive.
FAVICON = (
    "data:image/svg+xml,"
    "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E"
    "%3Cpath d='M6 2 L18 2 L22 6 L22 18 L18 22 L6 22 L2 18 L2 6 Z' fill='none'"
    " stroke='%23c8aa6e' stroke-width='1.75'/%3E"
    "%3Cpath d='M12 6.5 L13.2 10.8 L17.5 12 L13.2 13.2 L12 17.5 L10.8 13.2 L6.5 12"
    " L10.8 10.8 Z' fill='%233c8fe0'/%3E%3C/svg%3E"
)

# The rail's symbols jump can only be written once the legend is known, and the
# legend is derived from the finished page. Same trick as LEGEND_MARKER.
RAILSYM_MARKER = "<!--RAILSYM-->"

# Shown once, under the verdict, instead of repeating the same sentence under
# every note. One to three lines — only the bases actually in use — that a
# reader absorbs and then stops needing.
KEY_ROWS = (
    ("grounded", "Grounded", "A rule states this in so many words."),
    ("structural", "Structural", "No single rule says this; it follows from the rules cited."),
    ("gap", "Gap", "The rules are silent — the note shows what was searched."),
)


def basis_key_html(notes, spans=()):
    """The basis key, limited to the bases this answer actually uses.

    Spans count, not just notes. `_check_holding` constrains only grounded
    spans, so an `inferred` span may point at a `grounded` note — and deriving
    the key from notes alone then printed a dotted mark on the verdict line,
    the one line everyone reads, with no row explaining it.
    """
    used = ({n["basis"] for n in notes} | {s.get("basis") for s in spans}) - {None}
    used |= {"structural"} if "inferred" in used else set()
    rows = "".join(
        f'<div class="key-item k-{k}"><b>{BASIS[k][0]} {label}</b>{esc(why)}</div>'
        for k, label, why in KEY_ROWS if k in used
    )
    return f'<div class="key" data-od-id="basis-key">{rows}</div>' if rows else ""


def clip(text, limit=58):
    """Shorten a claim for the rail without cutting a word in half."""
    text = " ".join(str(text).split())
    if len(text) <= limit:
        return text
    # rfind returns -1 when no space falls inside the limit, and text[:-1] then
    # kept all but the last character — a 100-char claim rendered in full with
    # an ellipsis falsely claiming it had been shortened. Cut hard instead.
    cut = text.rfind(" ", 0, limit)
    return text[:cut if cut > 0 else limit].rstrip(" ,;:—-") + "…"


def rail_html(ans, jumps):
    """A sticky index of the argument.

    The report is one long column of dense conditional prose, and the reader's
    real question while scrolling is "which claim am I in, and is it the one
    everything rests on". The rail answers both without leaving the page: it
    restates the verdict, and marks the crux and the current note.
    """
    h = ans["holding"]
    rows = []
    for n in ans["notes"]:
        is_crux = bool(n.get("crux"))
        badge = '<span class="rail-crux">crux</span>' if is_crux else ""
        rows.append(
            f'<a class="rail-note{" is-crux" if is_crux else ""}" href="#{esc(n["id"])}" '
            f'title="{esc(n["claim"])}">'
            f'<span class="n">{esc(note_number(n["id"]))}</span>'
            f'<span class="t">{esc(clip(n["claim"]))}{badge}</span></a>'
        )
    notes = "".join(rows)
    jump_html = "".join(f'<a class="rail-jump" href="{href}">{esc(label)}</a>'
                        for href, label in jumps)

    return f'''<aside class="rail" data-od-id="rail" aria-label="Report contents">
  <div class="rail-plate plate">
    <h4>The ruling</h4>
    <span class="rail-disp{" is-lead" if h["disposition"] == "ANSWER" else ""}">{
      esc(clip(h.get("line", ""), 64)) if h["disposition"] == "ANSWER"
      else esc(h["disposition"])}</span>
    <p class="rail-meta">Weakest link <a class="weakref" href="#{esc(ans["_weakest"])}">note
      {esc(note_number(ans["_weakest"]))}</a> · {esc(ans["_strength"])}</p>
  </div>
  <nav class="rail-nav">
    <h4>The claims</h4>
    {notes}
  </nav>
  <nav class="rail-nav">{jump_html}{RAILSYM_MARKER}</nav>
</aside>'''


# The stylesheet lives outside the page f-string on purpose: every `{` in CSS
# would otherwise have to be doubled, which is how the old sheet became
# unreadable and therefore unmaintained.
#
# Riftbound — Runeterra Visual Language. The artwork is painterly, the chrome is
# crisp: nothing that carries information sits on a gradient. The only gradient
# in the sheet is the 1px lit edge of a chamfered frame.
_CSS = """
:root{
 --ink-900:#060b14; --ink-800:#0a1428; --ink-700:#0f1e33; --ink-600:#16293f;
 --ink-500:#1e3a52; --mist-100:#e4f1f5; --slate-300:#7a96a8; --slate-400:#4a6a80;
 --gold-700:#785a28; --gold-500:#c8aa6e; --blue:#3c8fe0;
 --bg:var(--ink-900); --surface:var(--ink-700); --well:var(--ink-800);
 --fg:var(--mist-100); --muted:var(--slate-300); --line:var(--gold-700);
 --rule:var(--ink-500); 
 /* Riot's Beaufort and TT Norms are proprietary and not redistributed; Cinzel
    and Barlow are the design system's open stand-ins. A report is a local file
    with no network, so what actually renders is the declared fallback. */
 --display:"Beaufort for LOL",Cinzel,Georgia,"Times New Roman",serif;
 --body:"TT Norms Pro Compact",Barlow,system-ui,-apple-system,"Segoe UI","Helvetica Neue",Arial,sans-serif;
 --plate:"Barlow Semi Condensed",Inter,system-ui,-apple-system,"Segoe UI",sans-serif;
 --ch:10px;
 --wash:color-mix(in oklch,var(--gold-500) 12%,transparent);
 --lift:color-mix(in oklch,var(--ink-700) 88%,var(--mist-100));
 --sink:color-mix(in oklch,var(--ink-900) 70%,transparent);
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--fg);font:400 17px/1.65 var(--body);
 padding-bottom:5rem}
::selection{background:var(--gold-700);color:var(--mist-100)}
/* Rules prose is dense and conditional; a one-word last line is where a reader
   loses the thread of a conditional. Browsers that lack it simply wrap as usual. */
h1,.hline,.detail,.reframe,.why,.counter h3,.note-head h3,ul.plain li,.foot{text-wrap:pretty}

/* A fixed turbulence grain is what makes crisp chrome and painterly art read as
   one surface. 3.5%, overlay, never intercepting a click. */
.grain{position:fixed;inset:0;z-index:100;pointer-events:none;opacity:.035;mix-blend-mode:overlay;
 background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='160' height='160'><filter id='g'><feTurbulence type='fractalNoise' baseFrequency='0.8' numOctaves='4' stitchTiles='stitch'/></filter><rect width='160' height='160' filter='url(%23g)'/></svg>")}

/* Chamfers, not radii — the cheapest way to signal Runeterra with no artwork.
   The frame is a real 1px hairline: the element's background IS the frame, and
   a clipped pseudo-element inset by 1px paints the surface back over it. A
   plain border cannot do this, because clip-path cuts the border at the
   chamfer and leaves the corner open. */
.plate{position:relative;isolation:isolate;padding:1px;background:var(--line);
 filter:drop-shadow(0 1px 0 var(--sink));
 clip-path:polygon(var(--ch) 0,100% 0,100% calc(100% - var(--ch)),calc(100% - var(--ch)) 100%,0 100%,0 var(--ch))}
.plate::after{content:"";position:absolute;inset:1px;z-index:-1;background:var(--surface);
 clip-path:polygon(calc(var(--ch) - 1px) 0,100% 0,100% calc(100% - var(--ch) + 1px),calc(100% - var(--ch) + 1px) 100%,0 100%,0 calc(var(--ch) - 1px))}

.wrap{max-width:66rem;margin:0 auto;padding:0 1.5rem}
.layout{display:grid;grid-template-columns:minmax(0,44rem) 15.5rem;gap:3rem;align-items:start}
main{min-width:0}

/* ── masthead ───────────────────────────────────────────────────────── */
.masthead{background:var(--well);border-bottom:1px solid var(--rule)}
.masthead-in{display:flex;align-items:center;gap:.8rem;padding:.85rem 0;flex-wrap:wrap}
.mark{width:32px;height:32px;flex:none;display:block}
.wordmark{display:flex;flex-direction:column;gap:.22rem;line-height:1}
.wordmark .eyebrow{font:600 .58rem/1 var(--plate);letter-spacing:.24em;text-transform:uppercase;
 color:var(--slate-300)}
/* The display face is set in caps only, and only three times on the page: here,
   on the disposition, and on the rail's restatement of it. Cinzel's lowercase is
   not what the register is for. */
.wordmark b{font:600 1.02rem/1 var(--display);letter-spacing:.15em;text-transform:uppercase;
 color:var(--gold-500)}
.unofficial{align-self:center;padding:.42em .7em;border:1px solid var(--line);
 font:600 .58rem/1 var(--plate);letter-spacing:.16em;text-transform:uppercase;color:var(--slate-300)}
.corpus{margin-left:auto;text-align:right;font:500 .68rem/1.6 var(--plate);letter-spacing:.1em;
 text-transform:uppercase;color:var(--slate-300)}
.corpus b{color:var(--fg);font-weight:600}

/* ── the question ───────────────────────────────────────────────────── */
.label{display:block;font:600 .64rem/1 var(--plate);letter-spacing:.17em;text-transform:uppercase;
 color:var(--slate-300)}
.ask{padding-top:2.6rem}
h1{margin:.75rem 0 0;font:500 1.5rem/1.34 var(--body);max-width:34ch;color:var(--fg)}
.reframe{margin:1.1rem 0 0;padding-top:.9rem;border-top:1px solid var(--rule);
 color:var(--muted);font-size:1rem;max-width:68ch}
.reframe .label{margin-bottom:.35rem}

/* ── the verdict: the one panel that gets the whole design budget ───── */
.verdict{--ch:14px;margin:1.9rem 0 0;padding:1.5rem 1.6rem 1.35rem;
 background:linear-gradient(148deg,var(--gold-500) 0%,var(--gold-700) 42%,var(--gold-700) 100%)}
.verdict.d-UNSETTLED{background:linear-gradient(148deg,var(--mist-100) 0%,var(--gold-700) 48%,var(--gold-700) 100%)}
.verdict-head{display:flex;align-items:center;gap:1.1rem;flex-wrap:wrap}
.disp{font:700 clamp(1.55rem,4.4vw,2.3rem)/1 var(--display);letter-spacing:.1em;
 text-transform:uppercase;color:var(--fg)}
.disp.UNSETTLED{background:var(--mist-100);color:var(--ink-900);padding:.1em .3em;letter-spacing:.07em}
.hairline{flex:1 1 2rem;height:1px;background:var(--line)}
.tally{font:600 .7rem/1.5 var(--plate);letter-spacing:.11em;text-transform:uppercase;
 color:var(--muted);white-space:nowrap}
.tally b{color:var(--fg)}
.hline{margin:1.15rem 0 0;font-size:1.2rem;line-height:1.55;max-width:68ch}
/* An open question has no one-word verdict, so the sentence IS the headline and
   is set at the weight the plate word would have carried. */
.hline.is-lead{margin-top:.35rem;font-size:clamp(1.24rem,2.6vw,1.5rem);line-height:1.42;
 color:var(--fg);text-wrap:balance}
.sp-grounded{color:inherit;text-decoration:none;border-bottom:2px solid var(--gold-500)}
.sp-inferred{color:inherit;text-decoration:none;border-bottom:2px dotted var(--blue)}
.sp-gap{color:inherit;text-decoration:none;border-bottom:2px dotted var(--muted)}
.sp-grounded:hover,.sp-inferred:hover,.sp-gap:hover{background:var(--wash);color:var(--fg)}
.noteref{color:var(--blue);text-decoration:none;font:700 .95em/1 var(--plate);padding-left:.12em}
.noteref:hover{color:var(--fg)}
.strength{display:flex;flex-wrap:wrap;gap:.35rem 1.7rem;margin-top:1.3rem;padding-top:.95rem;
 border-top:1px solid var(--rule);font:500 .78rem/1.6 var(--plate);letter-spacing:.05em;
 color:var(--muted)}
.metric{display:flex;gap:.5rem;align-items:baseline}
.metric .label{display:inline;letter-spacing:.14em}
.metric b{color:var(--fg);font-weight:600}
.weakref{color:var(--blue);text-decoration:none;border-bottom:1px dotted var(--blue)}
.weakref:hover{color:var(--fg);border-bottom-color:var(--fg)}
.forced{flex-basis:100%;margin-top:.35rem;padding:.6rem .75rem;background:var(--mist-100);
 color:var(--ink-900);font:600 .72rem/1.5 var(--plate);letter-spacing:.07em;text-transform:uppercase}

/* ── how to read a basis, stated once ───────────────────────────────── */
.key{display:flex;flex-wrap:wrap;gap:.5rem;margin:.85rem 0 0}
.key-item{flex:1 1 12.5rem;padding:.65rem .75rem;background:var(--well);
 border:1px solid var(--rule);font-size:.82rem;line-height:1.5;color:var(--muted)}
.key-item b{display:block;margin-bottom:.28rem;font:600 .65rem/1 var(--plate);
 letter-spacing:.14em;text-transform:uppercase}
.k-grounded b{color:var(--gold-500)}
.k-structural b{color:var(--blue)}
.k-gap b{color:var(--slate-300)}

/* ── section rules ──────────────────────────────────────────────────── */
h2{display:flex;align-items:center;gap:.95rem;margin:3rem 0 1.15rem;scroll-margin-top:1.5rem;
 font:600 .74rem/1 var(--plate);letter-spacing:.17em;text-transform:uppercase;color:var(--gold-500)}
h2::after{content:"";flex:1;height:1px;background:var(--line);opacity:.5}

/* ── notes ──────────────────────────────────────────────────────────── */
.note{--ch:9px;display:grid;grid-template-columns:2.9rem minmax(0,1fr);margin:.85rem 0;
 scroll-margin-top:1.5rem}
.note.is-crux,.note:target{background:linear-gradient(148deg,var(--gold-500) 0%,var(--gold-700) 45%,var(--gold-700) 100%)}
.note-n{display:flex;justify-content:center;padding:1.05rem .4rem;
 border-right:1px solid var(--rule);font:600 .95rem/1 var(--plate);
 font-variant-numeric:tabular-nums;color:var(--slate-300)}
.b-grounded .note-n{color:var(--gold-500)}
.b-structural .note-n{color:var(--blue)}
.b-inferred .note-n{color:var(--blue)}
/* Restates the base colour rather than changing it: a gap is deliberately the
   quietest note on the page, and writing it out makes that a decision instead
   of an omission that looks identical to a forgotten rule. */
.b-gap .note-n{color:var(--slate-300)}
.note-body{padding:1rem 1.15rem 1.1rem;min-width:0}
.note-head{display:flex;gap:.8rem;align-items:flex-start;flex-wrap:wrap}
.note-head h3{flex:1 1 15rem;margin:0;font:500 1.02rem/1.45 var(--body);max-width:68ch}
.note-tags{display:flex;gap:.4rem;flex-wrap:wrap}
.basis-chip{font:600 .63rem/1 var(--plate);letter-spacing:.12em;text-transform:uppercase;
 border:1px solid var(--rule);padding:.42em .55em;color:var(--muted);white-space:nowrap}
.b-grounded .basis-chip{color:var(--gold-500);border-color:var(--line)}
.b-structural .basis-chip{color:var(--blue);border-color:color-mix(in oklch,var(--blue) 42%,transparent)}
.b-inferred .basis-chip{color:var(--blue);border-color:color-mix(in oklch,var(--blue) 42%,transparent)}
.b-gap .basis-chip{color:var(--muted);border-color:var(--rule)}
.crux{font:700 .63rem/1 var(--plate);letter-spacing:.14em;text-transform:uppercase;
 border:1px solid var(--gold-500);color:var(--gold-500);padding:.42em .55em;white-space:nowrap}
.detail{margin:.8rem 0 0;font-size:.97rem;max-width:68ch;color:var(--fg)}
.iffalse{margin:.9rem 0 0;padding:.75rem .85rem;background:var(--well);border:1px solid var(--line);
 font-size:.93rem;max-width:68ch}
.iffalse b{display:block;margin-bottom:.3rem;font:600 .64rem/1 var(--plate);letter-spacing:.14em;
 text-transform:uppercase;color:var(--gold-500)}
.checked{margin:.85rem 0 0;font:500 .74rem/1.6 var(--plate);letter-spacing:.07em;color:var(--muted)}
.checked b{margin-right:.5rem;font-weight:600;letter-spacing:.14em;text-transform:uppercase;
 color:var(--slate-300)}

/* ── citations ──────────────────────────────────────────────────────── */
.cites{display:flex;flex-direction:column;gap:.4rem;margin-top:.95rem}
.cite{--ch:7px;background:var(--rule);filter:none}
.cite::after{background:var(--well)}
.cite summary{display:flex;align-items:center;gap:.6rem;padding:.55rem .7rem;min-height:36px;
 cursor:pointer;list-style:none}
.cite summary::-webkit-details-marker{display:none}
.cite summary::before{content:"+";width:.7rem;font:600 .9rem/1 var(--plate);color:var(--slate-300)}
.cite[open] summary::before{content:"\\2013"}
.cite summary:hover{background:var(--lift)}
.cite summary:hover::before{color:var(--fg)}
.cite-id{flex:1;font:600 .78rem/1 var(--plate);letter-spacing:.09em;color:var(--fg);
 font-variant-numeric:tabular-nums}
.stamp{font:600 .62rem/1 var(--plate);letter-spacing:.12em;text-transform:uppercase;
 padding:.4em .55em;white-space:nowrap}
.stamp.ok{color:var(--blue);border:1px solid color-mix(in oklch,var(--blue) 42%,transparent)}
/* A failed citation inverts. It is the one thing on the page that must survive
   a glance, a greyscale printer and a reader who does not know the palette. */
.stamp.bad{background:var(--mist-100);color:var(--ink-900);border:1px solid var(--mist-100)}
.cite-body{padding:.15rem .8rem .8rem;border-top:1px solid var(--rule)}
.ancestry{list-style:none;margin:.7rem 0;padding:0}
.ancestry li{padding:.35rem 0 .35rem calc(.75rem + var(--d) * .95rem);font-size:.9rem;
 line-height:1.5;color:var(--muted);border-left:1px solid var(--slate-400)}
.ancestry li.anc-target{background:var(--wash);border-left-color:var(--gold-500);color:var(--fg)}
.ancestry code{margin-right:.5rem;font:600 .82rem/1 var(--plate);letter-spacing:.04em;
 font-variant-numeric:tabular-nums;color:var(--blue)}
.anc-link{text-decoration:none;border-bottom:1px dotted transparent}
.anc-link:hover{border-bottom-color:var(--fg)}
.anc-link:hover code{color:var(--fg)}
.narrowed{margin:.6rem 0;font-size:.85rem;line-height:1.5;color:var(--gold-500)}
.prob{margin:.6rem 0;padding:.45rem .6rem;background:var(--wash);border-left:2px solid var(--mist-100);
 font-size:.85rem;line-height:1.5;color:var(--fg)}
.cite-actions{display:flex;gap:.55rem;flex-wrap:wrap;align-items:center}
.rulebook-link,.copy{display:inline-flex;align-items:center;min-height:34px;padding:.6em .85em;
 border:1px solid var(--rule);background:transparent;color:var(--fg);cursor:pointer;
 text-decoration:none;font:600 .66rem/1 var(--plate);letter-spacing:.12em;text-transform:uppercase}
.rulebook-link:hover,.copy:hover{background:var(--lift);border-color:var(--gold-500);color:var(--fg)}

/* ── counterargument ────────────────────────────────────────────────── */
.counter{--ch:9px;margin:.85rem 0;padding:1.1rem 1.2rem;background:var(--rule)}
.counter::after{background:var(--well)}
.counter h3{margin:.45rem 0 1rem;font:500 1.05rem/1.55 var(--body);color:var(--fg);max-width:68ch}
.counter .why{margin:.45rem 0 0;font-size:.95rem;color:var(--muted);max-width:68ch}
.counter .cites{margin-top:1rem}

/* ── plain lists ────────────────────────────────────────────────────── */
ul.plain{list-style:none;margin:.5rem 0 0;padding:0}
ul.plain li{position:relative;padding:.7rem 0 .7rem 1.2rem;border-bottom:1px solid var(--rule);
 font-size:.95rem;max-width:68ch}
ul.plain li:last-child{border-bottom:0}
ul.plain li::before{content:"";position:absolute;left:0;top:1.25rem;width:5px;height:5px;
 background:var(--gold-700);transform:rotate(45deg)}
ul.plain code{font:600 .84rem/1 var(--plate);letter-spacing:.05em;color:var(--blue)}

/* ── cards ──────────────────────────────────────────────────────────── */
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(12.5rem,1fr));gap:.9rem}
.card{--ch:8px;margin:0;display:flex;flex-direction:column;overflow:hidden}
.card-art{width:100%;height:auto;display:block;background:var(--well)}
.card-art--none{aspect-ratio:744/1039;display:flex;flex-direction:column;align-items:center;
 justify-content:center;gap:.4rem;padding:1rem;text-align:center;color:var(--fg);
 font:600 .68rem/1.4 var(--plate);letter-spacing:.12em;text-transform:uppercase}
.card-art--none span{font:400 .72rem/1.45 var(--body);letter-spacing:0;text-transform:none;
 color:var(--muted)}
.card figcaption{display:flex;flex-direction:column;gap:.35rem;padding:.7rem .75rem .8rem;
 border-top:1px solid var(--rule)}
.card-name{font:600 .9rem/1.35 var(--body)}
.card-stats{display:flex;flex-wrap:wrap;gap:.25rem}
.chip{font:600 .62rem/1 var(--plate);letter-spacing:.09em;text-transform:uppercase;
 border:1px solid var(--rule);padding:.35em .48em;color:var(--muted);white-space:nowrap}
.chip b{color:var(--fg);font-weight:700}
.chip-d{border-color:var(--line);color:var(--gold-500)}
.card-text{font-size:.79rem;line-height:1.55;color:var(--muted)}
.card-errata,.card-gap{display:block;margin-top:.3rem;padding:.45rem .55rem;
 font-size:.74rem;line-height:1.5}
.card-errata{border-left:2px solid var(--gold-700);background:var(--well);color:var(--muted)}
.card-gap{border-left:2px solid var(--mist-100);background:var(--wash);color:var(--fg)}
.card-rules{display:block;margin-top:.15rem;font:500 .64rem/1.6 var(--plate);letter-spacing:.1em;
 text-transform:uppercase;color:var(--slate-300)}
.card-rule{margin-right:.4rem;color:var(--blue);text-decoration:none;
 border-bottom:1px dotted var(--blue)}
.card-rule:hover{color:var(--fg);border-bottom-color:var(--fg)}

/* ── symbol legend ──────────────────────────────────────────────────── */
.legend{display:grid;grid-template-columns:auto 1fr auto;gap:.55rem 1.1rem;align-items:baseline;
 padding:1.05rem 1.15rem}
.sym-row{display:contents}
.sym{justify-self:start;font:700 .95rem/1 var(--plate);color:var(--fg)}
.sym-mean{font-size:.9rem}
.sym-rule{white-space:nowrap;font:600 .72rem/1 var(--plate);letter-spacing:.07em;color:var(--blue);
 text-decoration:none;border-bottom:1px dotted var(--blue)}
.sym-rule:hover{color:var(--fg);border-bottom-color:var(--fg)}
.legend-note{margin:.8rem 0 0;font-size:.85rem;color:var(--muted);max-width:68ch}

/* ── the rail ───────────────────────────────────────────────────────── */
.rail{position:sticky;top:1.6rem;align-self:start;max-height:calc(100vh - 3.2rem);
 overflow-y:auto;padding-bottom:1rem;scrollbar-width:thin;
 scrollbar-color:var(--ink-500) transparent}
.rail h4{margin:0 0 .55rem;font:600 .63rem/1 var(--plate);letter-spacing:.17em;
 text-transform:uppercase;color:var(--slate-300)}
.rail-plate{--ch:8px;padding:.95rem 1rem}
/* An open question restates its ANSWER as the sentence, not the token — the
   token never appears anywhere a reader can see it. */
.rail-disp.is-lead{font:600 .82rem/1.4 var(--body);letter-spacing:.01em;text-transform:none}
.rail-disp{display:block;font:700 1.15rem/1 var(--display);letter-spacing:.1em;
 text-transform:uppercase;color:var(--fg)}
.rail-meta{margin:.7rem 0 0;font:500 .73rem/1.6 var(--plate);letter-spacing:.05em;color:var(--muted)}
.rail-nav{display:flex;flex-direction:column;margin-top:1.4rem}
.rail-note{display:grid;grid-template-columns:1.3rem minmax(0,1fr);gap:.45rem;
 padding:.45rem .55rem;border-left:1px solid transparent;text-decoration:none;
 color:var(--muted);font-size:.79rem;line-height:1.4}
.rail-note .n{font:600 .72rem/1.4 var(--plate);font-variant-numeric:tabular-nums;
 color:var(--slate-300)}
.rail-note.is-crux .n{color:var(--gold-500)}
.rail-crux{display:inline-block;margin-left:.4rem;font:700 .58rem/1 var(--plate);
 letter-spacing:.13em;text-transform:uppercase;color:var(--gold-500)}
.rail-note:hover{background:var(--lift);color:var(--fg);border-left-color:var(--slate-400)}
.rail-note.here{background:var(--wash);color:var(--fg);border-left-color:var(--gold-500)}
.rail-jump{padding:.45rem .55rem;border-left:1px solid transparent;text-decoration:none;
 color:var(--muted);font:600 .68rem/1.4 var(--plate);letter-spacing:.1em;text-transform:uppercase}
.rail-jump:hover{background:var(--lift);color:var(--fg);border-left-color:var(--slate-400)}

/* ── rulebook overlay ───────────────────────────────────────────────── */
.rb-overlay{position:fixed;inset:0;z-index:120;padding:3vh 3vw;display:flex;align-items:center;
 justify-content:center;background:color-mix(in oklch,var(--ink-900) 84%,transparent)}
.rb-overlay[hidden]{display:none}
.rb-panel{--ch:12px;width:min(62rem,96vw);height:min(88vh,58rem);display:flex;flex-direction:column;
 overflow:hidden}
.rb-panel::after{background:var(--ink-600)}
.rb-bar{display:flex;align-items:center;gap:.9rem;padding:.6rem .8rem;
 border-bottom:1px solid var(--rule)}
.rb-title{flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
 font:600 .74rem/1.4 var(--plate);letter-spacing:.12em;text-transform:uppercase;color:var(--fg)}
.rb-pop{white-space:nowrap;font:600 .67rem/1 var(--plate);letter-spacing:.11em;text-transform:uppercase;
 color:var(--blue);text-decoration:none;border-bottom:1px dotted var(--blue)}
.rb-pop:hover{color:var(--fg);border-bottom-color:var(--fg)}
.portable{margin-left:auto;align-self:center;white-space:nowrap;font:600 .67rem/1 var(--plate);letter-spacing:.11em;text-transform:uppercase}
.portable.is-built{color:var(--blue);text-decoration:none;border-bottom:1px dotted var(--blue)}
.portable.is-built:hover{color:var(--fg);border-bottom-color:var(--fg)}
.portable.is-unbuilt{color:var(--muted);text-transform:none;letter-spacing:0;font-weight:500}
.portable.is-unbuilt code{font:inherit;color:var(--fg)}
.portable.is-portable{color:var(--muted)}
@media(max-width:720px){.portable{margin-left:0;flex-basis:100%}}
.rb-close{width:34px;height:34px;flex:none;font-size:1.15rem;line-height:1;cursor:pointer;
 background:transparent;border:1px solid var(--rule);color:var(--muted)}
.rb-close:hover{background:var(--lift);border-color:var(--gold-500);color:var(--fg)}
.rb-frame{flex:1;width:100%;border:0;background:var(--ink-900)}

/* ── footer ─────────────────────────────────────────────────────────── */
.foot{margin-top:3.5rem;padding-top:1.1rem;border-top:1px solid var(--rule);
 font-size:.8rem;line-height:1.6;color:var(--muted)}

/* ── focus, always visible ──────────────────────────────────────────── */
a:focus-visible,button:focus-visible,summary:focus-visible{outline:2px solid var(--gold-500);
 outline-offset:2px}
.skip{position:absolute;left:-9999px}
.skip:focus{position:fixed;left:1rem;top:1rem;z-index:200;padding:.75em 1em;
 background:var(--ink-700);border:1px solid var(--gold-500);color:var(--fg);text-decoration:none;
 font:600 .68rem/1 var(--plate);letter-spacing:.12em;text-transform:uppercase}

@media(max-width:1060px){
 .layout{grid-template-columns:minmax(0,1fr)}
 .rail{display:none}
}
@media(max-width:720px){
 body{font-size:16px}
 .hline{font-size:1.08rem}
 .note{grid-template-columns:minmax(0,1fr)}
 .note-n{justify-content:flex-start;padding:.65rem .9rem;border-right:0;
  border-bottom:1px solid var(--rule)}
 .cards{grid-template-columns:repeat(auto-fill,minmax(9.5rem,1fr))}
 .legend{grid-template-columns:auto 1fr}
 .sym-rule{grid-column:2;justify-self:start}
 .corpus{margin-left:0;text-align:left;flex-basis:100%}
}
@media(pointer:coarse){
 .rulebook-link,.copy,.rb-close,.cite summary{min-height:44px}
}
@media(prefers-reduced-motion:reduce){*{transition:none!important;scroll-behavior:auto!important}}

/* Judges print these. Paper inverts the whole system: the ground becomes white,
   ink becomes text, and gold drops to Gold 700 because Gold 500 on white is
   2.23:1. Every value below is still a palette token — nothing new is invented
   for print. */
@media print{
 /* color-scheme:dark makes the UA paint the canvas near-black wherever the
    page background is transparent — on paper that produced a black sheet with
    black text. Paper is a light surface; say so before anything else. */
 :root{color-scheme:light;
  --bg:transparent;--surface:transparent;--well:transparent;--fg:var(--ink-900);
  --muted:var(--slate-400);--line:var(--gold-700);--rule:var(--slate-400);
  --blue:var(--ink-700);--wash:transparent;--lift:transparent;--sink:transparent;
  /* Raw palette tokens have to be remapped too, not just the semantic ones.
     Anything reaching for a palette value DIRECTLY kept its dark-ground colour
     on paper: gold-500 at 2.23:1, slate-300 at 3.11:1, mist-100 at 1.15:1.
     The worst of it inverted the argument — .sp-grounded (gold-500) all but
     vanished while .sp-inferred (--blue, correctly remapped) printed at
     16.75:1, so the inferred half of the verdict line looked the better
     supported one. */
  --gold-500:var(--gold-700);--slate-300:var(--slate-400);--mist-100:var(--slate-400)}
 html,body{background:transparent}
 body{color:var(--fg);font-size:11pt;padding-bottom:0}
 .grain,.rail,.rb-overlay,.copy,.rulebook-link,.skip,.unofficial{display:none!important}
 .masthead{background:transparent}
 .plate{background:transparent;border:1px solid var(--line);clip-path:none;filter:none}
 .plate::after{display:none}
 /* .verdict.d-UNSETTLED outranks a bare .verdict, so it has to be named. */
 .verdict,.verdict.d-UNSETTLED,.note.is-crux,.note:target{background:transparent}
 .disp{color:var(--fg)}
 .disp.UNSETTLED,.forced,.stamp.bad{background:transparent;color:var(--fg);
  border:1.5pt solid var(--fg)}
 .wordmark b,.k-grounded b,.iffalse b,h2,.crux,.chip-d,.card-rules{color:var(--gold-700)}
 .note,.cite,.card,.counter,.key-item{break-inside:avoid}
 h2{break-after:avoid}
 a{color:var(--fg)}
 .layout{display:block}
}
"""

_JS = """
// file:// has no clipboard API in Chrome — the execCommand fallback is mandatory.
document.addEventListener('click', function(e){
  var b = e.target.closest('.copy'); if(!b) return;
  var t = b.dataset.cite, done = function(){ b.textContent='Copied'; setTimeout(function(){b.textContent='Copy cite';},1200); };
  try { if(navigator.clipboard && window.isSecureContext) { navigator.clipboard.writeText(t).then(done); return; } } catch(_){}
  var ta=document.createElement('textarea'); ta.value=t; ta.style.position='fixed'; ta.style.opacity=0;
  document.body.appendChild(ta); ta.select();
  try { document.execCommand('copy'); done(); } catch(_){ b.textContent='Copy failed'; }
  document.body.removeChild(ta);
});
// Jumping to a note from the holding line should open its citations.
window.addEventListener('hashchange', function(){
  var el=document.querySelector(location.hash); if(!el) return;
  el.querySelectorAll('details').forEach(function(d){d.open=true;});
});
// Judges print things; printed <details> must not hide the evidence.
window.addEventListener('beforeprint', function(){
  document.querySelectorAll('details').forEach(function(d){d.dataset.wasOpen=d.open?'1':'';d.open=true;});
});
window.addEventListener('afterprint', function(){
  document.querySelectorAll('details').forEach(function(d){d.open=d.dataset.wasOpen==='1';});
});

// The rail marks the claim you are currently reading. Purely an orientation
// aid: if IntersectionObserver is missing the rail still works as a link list.
(function(){
  var links=[].slice.call(document.querySelectorAll('.rail-note'));
  if(!links.length || !window.IntersectionObserver) return;
  var map={}, seen={};
  links.forEach(function(a){ map[a.getAttribute('href').slice(1)]=a; });
  var io=new IntersectionObserver(function(entries){
    entries.forEach(function(en){ seen[en.target.id]=en.isIntersecting; });
    // Pick the note occupying MOST of the reading band, not the first one that
    // happens to touch it. Taking the topmost meant a claim whose last 14px
    // were still in the band beat the claim actually filling it, so the rail
    // lagged one behind what you were reading — the opposite of the point.
    // None at all is a valid answer: above the first note and below the last,
    // a leftover highlight points at a claim you have scrolled away from.
    var top=innerHeight*0.12, bot=innerHeight*0.32, current=null, best=0;
    Object.keys(map).forEach(function(id){
      if(!seen[id]) return;
      var el=document.getElementById(id); if(!el) return;
      var r=el.getBoundingClientRect();
      var overlap=Math.min(r.bottom,bot)-Math.max(r.top,top);
      if(overlap>best){ best=overlap; current=id; }
    });
    links.forEach(function(l){ l.classList.remove('here'); });
    if(current) map[current].classList.add('here');
  },{rootMargin:'-12% 0px -68% 0px'});
  // '.step' is a primer's equivalent of a ruling's '.note'. Both use
  // '.rail-note' links, so one observer serves both documents.
  document.querySelectorAll('.note, .step').forEach(function(n){ io.observe(n); });
})();

// Reading a cited rule should not cost you your place in the argument, so the
// rulebook opens OVER the report. An iframe, not fetch: file:// forbids XHR
// between local files, while an iframe loads and honours the #fragment
// natively. Nothing scripts INTO the frame — cross-origin rules forbid it for
// file:// and we do not need it.
(function(){
  var ov=document.getElementById('rb-overlay'), fr=document.getElementById('rb-frame'),
      ttl=document.getElementById('rb-title'), pop=document.getElementById('rb-pop'), last=null;
  function open(href, label){
    last=document.activeElement; ttl.textContent=label||'Rulebook'; pop.href=href;
    fr.src=href;                 // reassigning src re-navigates, so a second
    ov.hidden=false;             // citation scrolls to ITS rule, not the first
    document.body.style.overflow='hidden';
    document.getElementById('rb-close').focus();
  }
  function close(){
    ov.hidden=true; fr.src='about:blank';
    document.body.style.overflow='';
    if(last && last.focus) last.focus();
  }
  document.addEventListener('click', function(e){
    var a=e.target.closest('a.rulebook-link, a.anc-link, a.card-rule, a.sym-rule');
    if(a){
      // Modified and middle clicks keep their normal meaning; the href is real.
      if(e.metaKey||e.ctrlKey||e.shiftKey||e.altKey||e.button!==0) return;
      e.preventDefault();
      var href=a.getAttribute('href'), m=/#([A-Z]{2})-(.+)$/.exec(href);
      open(href, m ? m[1]+' '+decodeURIComponent(m[2]) : 'Rulebook');
      return;
    }
    if(e.target.closest('#rb-close') || e.target===ov) close();
  });
  document.addEventListener('keydown', function(e){ if(e.key==='Escape' && !ov.hidden) close(); });
})();
"""


def render(ans, idx, stem="report"):
    h = ans["holding"]
    corpus = ans["corpus"]
    disp = h["disposition"]
    forced = h.get("_forced")

    note_blocks = []
    for n in ans["notes"]:
        glyph, why = BASIS[n["basis"]]
        crux = '<span class="crux">Crux</span>' if n.get("crux") else ""
        iff = (f'<div class="iffalse"><b>If this is wrong</b>{esc(n["if_false"])}</div>'
               if n.get("if_false") else "")
        checked = (f'<div class="checked"><b>Rules searched</b>'
                   f'{esc(" · ".join(n["rules_checked"]))}</div>'
                   if n.get("rules_checked") else "")
        cites = "".join(cite_html(c, idx, corpus) for c in n.get("cites", []))
        note_blocks.append(f'''<section class="note plate b-{n["basis"]}{" is-crux" if n.get("crux") else ""}"
    id="{esc(n["id"])}" data-od-id="note-{esc(n["id"])}">
  <div class="note-n" aria-hidden="true">{esc(note_number(n["id"]))}</div>
  <div class="note-body">
    <div class="note-head">
      <h3>{esc(n["claim"])}</h3>
      <span class="note-tags"><span class="basis-chip" title="{esc(why)}">{glyph} {esc(n["basis"])}</span>{crux}</span>
    </div>
    {f'<p class="detail">{esc(n["detail"])}</p>' if n.get("detail") else ""}
    {iff}{checked}
    {f'<div class="cites">{cites}</div>' if cites else ""}
  </div>
</section>''')

    counter = "".join(f'''<section class="counter plate" data-od-id="counter-{i}">
  <span class="label">The opposing reading</span>
  <h3>“{esc(c["reading"])}”</h3>
  <span class="label">Why it loses</span>
  <p class="why">{esc(c["why_it_loses"])}</p>
  {f'<div class="cites">{"".join(cite_html(x, idx, corpus) for x in c.get("cites", []))}</div>'
   if c.get("cites") else ""}
</section>''' for i, c in enumerate(ans.get("counterargument", []), 1))

    rejected = "".join(
        f'<li><code>{esc(r["rule"])}</code> — {esc(r["why"])}</li>'
        for r in ans.get("considered_rejected", []))

    openq = "".join(f'<li>{esc(q)}</li>' for q in ans.get("open_questions", []))

    # The template supplies "As the rules see it:", and an author who also
    # writes it gets it twice. Cheap to strip, and the alternative is relying
    # on every future answer remembering a convention the schema does not show.
    reframe = re.sub(r"^\s*as the rules see it\s*:\s*", "", ans.get("reframe", ""),
                     flags=re.I)

    problems = "".join(f'<li>{esc(p)}</li>' for p in ans.get("_problems", []))
    _cites = all_cites(ans)
    ncites = len(_cites)
    nverified = sum(1 for c in _cites if c["verified"])

    cards_block = cards_html(ans)
    key = basis_key_html(ans["notes"], h.get("spans", []))
    # Passed as data, not as five same-typed positional flags whose declared
    # order differed from the order the rail emitted them in. Transposing two
    # produced a wrong rail with no error and nothing to fail a test on.
    rail = rail_html(ans, [
        (href, label) for href, label, present in (
            ("#cards", "Cards referenced", cards_block),
            ("#against", "The argument against", counter),
            ("#rejected", "Considered and rejected", rejected),
            ("#unsettled", "The rules do not settle", openq),
            ("#problems", "Verification problems", problems),
        ) if present
    ])
    forced_html = (
        '<div class="forced">Verdict forced to UNSETTLED — a cited rule failed '
        f'verification (was {esc(forced)})</div>' if forced else "")

    page = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark">
<title>Ruling — {esc(ans["question"][:60])}</title>
<link rel="icon" href="{FAVICON}">
<style>{_CSS}</style></head>
<body>
<div class="grain" aria-hidden="true"></div>
<a class="skip" href="#ruling">Skip to the ruling</a>

<header class="masthead" data-od-id="masthead">
  <div class="wrap masthead-in">
    {MARK}
    <span class="wordmark"><span class="eyebrow">Riftbound</span><b>Oracle</b></span>
    <span class="unofficial">Unofficial rules companion</span>
    <span class="corpus">CR <b>{esc(corpus["CR"])}</b> &middot; TR <b>{esc(corpus["TR"])}</b><br>
      corpus built {esc(corpus["generated"])} &middot; offline</span>
    {portable_note(stem)}
  </div>
</header>

<div class="wrap layout">
<main data-od-id="report">

<section class="ask" data-od-id="question">
  <span class="label">The question</span>
  <h1>{esc(ans["question"])}</h1>
  <p class="reframe"><span class="label">As the rules see it</span>{esc(reframe)}</p>
</section>

<section class="verdict plate d-{esc(disp)}" id="ruling" data-od-id="ruling">
  <div class="verdict-head">
    {"" if disp == "ANSWER" else f'<span class="disp {esc(disp)}">{esc(disp)}</span>'}
    <span class="hairline" aria-hidden="true"></span>
    <span class="tally"><b>{nverified}/{ncites}</b> citations verified verbatim</span>
  </div>
  <p class="hline{" is-lead" if disp == "ANSWER" else ""}">{holding_html(h)}</p>
  <div class="strength">
    <span class="metric"><span class="label">Weakest link</span>
      <a class="weakref" href="#{esc(ans["_weakest"])}">note {esc(note_number(ans["_weakest"]))}</a>
      <b>{esc(ans["_strength"])}</b></span>
    <span class="metric"><span class="label">Confidence</span>the lowest link, never an average</span>
    {forced_html}
  </div>
</section>

{key}

{cards_block}

<h2 id="reasoning" data-od-id="sec-reasoning">Reasoning</h2>
{"".join(note_blocks)}

{f'<h2 id="against" data-od-id="sec-against">The argument against, and why it loses</h2>{counter}' if counter else ""}
{f'<h2 id="rejected" data-od-id="sec-rejected">Considered and rejected</h2><ul class="plain">{rejected}</ul>' if rejected else ""}
{f'<h2 id="unsettled" data-od-id="sec-unsettled">The rules do not settle</h2><ul class="plain">{openq}</ul>' if openq else ""}
{f'<h2 id="problems" data-od-id="sec-problems">Verification problems</h2><ul class="plain">{problems}</ul>' if problems else ""}
<!--LEGEND-->

<footer class="foot" data-od-id="footer">
  Riftbound Oracle is an unofficial fan project, not endorsed by, affiliated with or
  sponsored by Riot Games. Rule text is quoted from Riot&rsquo;s Comprehensive Rules and
  Tournament Rules; card artwork is loaded from Riot&rsquo;s CDN and is not redistributed
  here.
</footer>

</main>
{rail}
</div>

<div id="rb-overlay" class="rb-overlay" hidden>
  <div class="rb-panel plate" role="dialog" aria-modal="true" aria-label="Rulebook">
    <div class="rb-bar">
      <span class="rb-title" id="rb-title">Rulebook</span>
      <a class="rb-pop" id="rb-pop" href="{RULEBOOK}" target="_blank" rel="noopener">Open full page &#8599;</a>
      <button class="rb-close" id="rb-close" aria-label="Close">&times;</button>
    </div>
    <iframe class="rb-frame" id="rb-frame" title="Rulebook"></iframe>
  </div>
</div>

<script>{_JS}</script></body></html>'''

    # The legend reflects what is actually on the page, so it is computed from
    # the finished page and substituted last.
    legend = legend_html(page, idx)
    # The rail can only offer the symbols jump once we know the legend exists;
    # a jump to a section that was never emitted is worse than no jump.
    railsym = ('<a class="rail-jump" href="#symbols">Symbols used here</a>'
               if legend else "")
    return page.replace(LEGEND_MARKER, legend).replace(RAILSYM_MARKER, railsym)


def main():
    # Flags filtered out of the positionals. `--force` was bound as argv[2],
    # so the documented escape hatch wrote to a file called "--force" while
    # leaving the previous all-green report.html untouched beside it.
    pos = [a for a in sys.argv[1:] if not a.startswith("--")]
    src = pos[0] if pos else "answer.json"
    out = pos[1] if len(pos) > 1 else "report.html"
    ans = json.load(open(src, encoding="utf-8"))
    idx = RuleIndex()
    ans = verify_answer(ans, idx)
    # The gate lives here, not only in `rules_cli.py report`. A sibling caller
    # that skipped it produced a byte-identical-looking artifact carrying a
    # green badge over a fabricated citation.
    if ans["_problems"] and "--force" not in sys.argv:
        print("VERIFICATION FAILED — refusing to render:", file=sys.stderr)
        for pb in ans["_problems"]:
            print(f"  ! {pb}", file=sys.stderr)
        sys.exit(1)
    # Render first, then write. `open(out,"w")` truncates on open, so a crash
    # inside render() used to destroy the previous good report at that path —
    # which matters most in the re-verify-a-saved-ruling flow, where the file
    # being overwritten is the artifact you were checking.
    html_out = render(ans, idx, stem=os.path.splitext(os.path.basename(out))[0])
    tmp = out + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(html_out)
        os.replace(tmp, out)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    _cites = all_cites(ans)
    ncites = len(_cites)
    nver = sum(1 for c in _cites if c["verified"])
    print(f"wrote {out}")
    print(f"  disposition : {ans['holding']['disposition']}"
          + (f" (forced from {ans['holding']['_forced']})" if ans['holding'].get('_forced') else ""))
    print(f"  citations   : {nver}/{ncites} verified")
    print(f"  weakest link: {ans['_weakest']} ({ans['_strength']})")
    for p in ans["_problems"]:
        print(f"  ! {p}")


if __name__ == "__main__":
    main()

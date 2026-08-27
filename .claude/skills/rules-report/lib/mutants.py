#!/usr/bin/env python3
"""Mutation battery — proves the selftest can actually fail.

WHY THIS EXISTS

Seven rounds of review on this skill found the same thing twice, and the second
time it was the dominant category: **checks that could not fail**. A legend
check that harvested its tokens from the page and compared them against that
same page. A probe satisfied by the explanatory comment sitting above the rule
it was probing for. An `all()` over a collection nobody asserted was non-empty.
An assertion that an identifier appears in source text, which passes whether or
not the code is ever called.

Every one of those was green while the exact defect it was named for was live.
The suite's headline number kept growing and its meaning did not.

So: a check that has never been observed to fail is not yet a check. This file
reintroduces each defect the suite claims to catch, runs the suite against the
damaged copy, and asserts the right check goes red. A mutant that SURVIVES is a
check that is lying.

Usage:  python3 rules_cli.py mutants
        python3 mutants.py            (same thing)

Nothing here touches the working tree — every mutant is applied to a throwaway
copy of the whole skill folder. That is not fastidiousness: an earlier review
sweep ran a truncating build whose output path resolved back to the real
`data/rules.html` and destroyed it.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
# The repo the skill lives in, when it lives in one — `build` parses source
# markdown from here. A standalone install has neither the sources nor any
# mutant that needs them.
REPO_ROOT = os.path.abspath(os.path.join(SKILL, "..", "..", ".."))


# Each mutant: reintroduce ONE defect, name the check that must catch it.
# `regen` rebuilds the rulebook after mutating, for defects that only show up in
# the generated artifact.
MUTANTS = [
    # ---- the verbatim gate itself -------------------------------------------
    # The round-6 regression exactly: BOTH the joined haystack and the joined
    # narrowing text. Either half alone is caught by the other, so a one-sided
    # mutant survives while proving nothing.
    dict(name="reintroduce the round-6 joined haystack AND joined narrowing",
         file="verify_citations.py",
         find="quote_ok = any(needle in norm(p) for p in idx.subtree_parts(rule_id, doc))",
         repl="quote_ok = needle in norm(' '.join(idx.subtree_parts(rule_id, doc)))",
         also=('            own = [r for r in scope if needle in norm(r["text"])]\n'
               '            if not own:\n'
               '                own = [r for r in scope\n'
               '                       if any(needle in norm(e) for e in r.get("examples", []))]',
               '            own = [r for r in scope\n'
               '                   if needle in norm(" ".join([r["text"]] + list(r.get("examples", []))))]'),
         expect="spliced across a block boundary"),
    dict(name="rank Examples equal to normative text when narrowing",
         file="verify_citations.py",
         find='            own = [r for r in scope if needle in norm(r["text"])]\n'
              '            if not own:\n'
              '                own = [r for r in scope\n'
              '                       if any(needle in norm(e) for e in r.get("examples", []))]',
         repl='            own = [r for r in scope\n'
              '                   if needle in norm(" ".join([r["text"]] + list(r.get("examples", []))))]',
         expect="normative text outranks an Example"),
    dict(name="drop descendants' Examples from the subtree",
         file="verify_citations.py",
         find="            parts.extend(x.get(\"examples\", []))",
         repl="            parts.extend(x.get(\"examples\", []) if x[\"id\"] == r[\"id\"] else [])",
         expect="descendant Example verifies at every ancestor"),
    dict(name="accept a citation whose quote was never checked",
         file="render_report.py",
         find="    return res.ok and res.checked",
         repl="    return res.ok",
         expect="quote-less citation downgrades its note"),

    # ---- claims the page makes ----------------------------------------------
    dict(name="let a grounded note assert with no citation",
         file="render_report.py",
         find='        if note["basis"] == "grounded" and not note.get("cites"):',
         repl="        if False:",
         expect="grounded note with no citations"),
    dict(name="exclude gap notes from the weakest link",
         file="render_report.py",
         find="    graded = notes",
         repl='    graded = [n for n in notes if n["basis"] != "gap"] or notes',
         expect="gap note is the weakest link"),
    dict(name="let a span out-rank the note it points at",
         file="render_report.py",
         find='        if note and RANK.get(sp.get("basis"), 0) > RANK.get(note.get("basis"), 0):',
         repl="        if False:",
         expect="span cannot claim more support"),
    dict(name="stop verifying considered_rejected ids",
         file="render_report.py",
         find="        found = idx.get(crid, cdoc) or idx.get(crid, None)",
         repl='        found = idx.get(crid, cdoc) or idx.get(crid, None) or {"doc": cdoc or "CR"}',
         expect="fabricated considered_rejected id"),
    dict(name="stop verifying rules_checked ids",
         file="render_report.py",
         find="            if not rrid or not idx.get(rrid, rdoc):",
         repl="            if False:",
         expect="fabricated rules_checked id"),
    # Anchored on `check_unique_ids`, which is where this moved when the primer
    # arrived and both kinds needed it. The battery reported the mutant STALE
    # the moment the block left `verify_answer` — which is the battery doing its
    # job: a mutant whose anchor no longer exists is testing nothing.
    dict(name="allow duplicate note ids",
         file="render_report.py",
         find="    if dupes:",
         repl="    if False:",
         expect="duplicate note ids"),
    dict(name="let answer fields override the vendored card record",
         file="render_report.py",
         find="            for k, v in supplied.items():\n"
              "                if not v or resolved.get(k):\n"
              "                    continue",
         repl="            for k, v in supplied.items():\n"
              "                if not v:\n"
              "                    continue",
         expect="override the vendored card text"),
    dict(name="report an empty card index as a missing card",
         file="render_report.py",
         find='    if bridge is not None and not getattr(bridge, "cards", None):',
         repl="    if False:",
         expect="EMPTY card index"),

    # ---- provenance ----------------------------------------------------------
    dict(name="hardcode the rules date in the copy-cite string",
         file="render_report.py",
         find='    dated = corpus.get(doc) or "version unstated"',
         repl='    dated = "2026-07-16"',
         expect="citation dates follow the corpus"),
    dict(name="name the narrowing destination instead of the origin",
         file="render_report.py",
         find='    c["narrowed"] = rid if res.narrowed_to else None',
         repl='    c["narrowed"] = res.narrowed_to',
         expect="names where it came FROM"),

    # ---- the legend ----------------------------------------------------------
    dict(name="let <script> bodies feed the symbol legend",
         file="render_report.py",
         find='body = re.sub(r"<(script|style)\\b.*?</\\1>", " ", page_html, flags=re.S | re.I)',
         repl='body = re.sub(r"<(script)\\b.*?</\\1>", " ", page_html, flags=re.S | re.I)',
         expect="style bodies do not reach the legend"),

    # ---- the printed page ----------------------------------------------------
    dict(name="drop the light canvas from the rulebook print sheet",
         file="render_rulebook.py",
         find="color-scheme:light;",
         repl="",
         expect="print sheet declares a light canvas"),
    dict(name="remap a print token to something illegible on white",
         file="render_report.py",
         find=" --gold-500:var(--gold-700);",
         repl=" --gold-500:var(--mist-100);",
         expect="legible on white"),

    # ---- the rulebook artifact ----------------------------------------------
    dict(name="emit the rulebook in raw input order",
         file="render_rulebook.py",
         find="    for d in by_doc:\n        by_doc[d].sort(key=lambda r: id_sort_key(r[\"id\"]))",
         repl="    pass",
         expect="rendered rulebook is in numeric id order",
         regen=True),
    dict(name="truncate the rulebook before rendering it",
         file="render_rulebook.py",
         find="    page = render_rulebook(rules, version)\n    tmp = out + \".tmp\"",
         repl="    open(out, \"w\").close()\n    page = render_rulebook(rules, version)\n    tmp = out + \".tmp\"",
         expect="crash inside the rulebook render"),

    # ---- the CLI contract ----------------------------------------------------
    dict(name="bind --force as the positional output path",
         file="render_report.py",
         find='    pos = [a for a in sys.argv[1:] if not a.startswith("--")]\n'
              '    src = pos[0] if pos else "answer.json"\n'
              '    out = pos[1] if len(pos) > 1 else "report.html"',
         repl='    src = sys.argv[1] if len(sys.argv) > 1 else "answer.json"\n'
              '    out = sys.argv[2] if len(sys.argv) > 2 else "report.html"',
         expect="mistaken for the output path"),
    # ---- the research path -------------------------------------------------
    dict(name="report a rejected FTS query as 'no matches'",
         file="retrieve.py",
         find='            words = re.findall(r"\\w+", fts_query)',
         repl='            words = []',
         also=("            raise BadQuery(str(e)) from e",
               "            return [], fts_query"),
         expect="which exists"),
    dict(name="clip rule text at 110 chars again",
         file="rules_cli.py",
         find='            print(f"    {line}")',
         repl='            print(f"    {line[:110]}"); break',
         expect="clause that reverses a rule"),
    dict(name="clip the section title to 22 chars again",
         file="rules_cli.py",
         find="        print(f\"{h['uid']:18} [{h['section']}. {h['section_title']}]\")",
         repl="        print(f\"{h['uid']:18} [{h['section']}. {h['section_title'][:22]}]\")",
         expect="does not clip the section title"),
    dict(name="order rule children lexicographically again",
         file="rules_cli.py",
         find='        for k in sorted(kids, key=lambda x: _idkey(x["id"])):',
         repl='        for k in sorted(kids, key=lambda x: x["id"]):',
         expect="children in numeric order"),
    dict(name="order the retriever's children by SQL rid again",
         file="retrieve.py",
         find='            "SELECT * FROM rule WHERE doc=? AND parent=?", (row["doc"], row["rid"])',
         repl='            "SELECT * FROM rule WHERE doc=? AND parent=? ORDER BY rid",\n            (row["doc"], row["rid"])',
         also=('        return sorted(rows, key=lambda x: sort_key(x["rid"]))', "        return rows"),
         expect="retriever orders children numerically"),
    dict(name="let a whitespace-only quote verify",
         file="verify_citations.py",
         find="    if quote is not None and not norm(quote):",
         repl="    if False:",
         expect="whitespace"),
    dict(name="narrow away from a rule that hosts the quote",
         file="verify_citations.py",
         find='            if any(r["id"] == rule_id for r in own):\n                own = [r for r in own if r["id"] == rule_id]',
         repl="            pass",
         expect="cited rule keeps its own quote"),
    dict(name="pick one home arbitrarily when several tie",
         file="verify_citations.py",
         find="                if len(tied) > 1:",
         repl="                if False:",
         expect="ambiguous quote home"),

    dict(name="let a rail claim render unclipped",
         file="render_report.py",
         find='    cut = text.rfind(" ", 0, limit)\n'
              '    return text[:cut if cut > 0 else limit].rstrip(" ,;:—-") + "…"',
         repl='    return text[:text.rfind(" ", 0, limit)].rstrip(" ,;:—-") + "…"',
         expect="shortened even with no early space"),

    # ---- round 10 -----------------------------------------------------------
    dict(name="recognise only the singular `Example:`, so a plural list is absorbed "
              "into the rule's normative text and becomes quotable as the rule",
         file="parse_rules.py",
         find='EXAMPLE_RE = re.compile(r"^\\s*Examples?:\\s*(.*)$")',
         repl='EXAMPLE_RE = re.compile(r"^\\s*Example:\\s*(.*)$")',
         expect="Examples list as normative text",
         rebuild=True),
    dict(name="weld the items of an Examples list into one string, manufacturing a "
              "sentence Riot never published",
         file="parse_rules.py",
         find="            if in_example_list and cur_example and _ITEM_START.match(stripped):",
         repl="            if False:",
         expect="each item stands alone",
         rebuild=True),

    # ---- round 9 blockers ---------------------------------------------------
    dict(name="resolve a missing answer file against lib/, delivering a shipped sample",
         file="rules_cli.py",
         find='        full = os.path.abspath(a)\n        if not os.path.exists(full):',
         repl='        full = a if not os.path.exists(a) else os.path.abspath(a)\n        if False:',
         expect="refused, not substituted"),
    dict(name="rewrite a rejected query silently, so hits answer a question nobody asked",
         file="rules_cli.py",
         find='    if ran != query:',
         repl='    if False:',
         expect="rewritten query says so"),
    dict(name="prefer a phrase rewrite over implicit AND, returning the complement of the query",
         file="retrieve.py",
         find='            for form in ([" ".join(words), \'"\' + " ".join(words) + \'"\'] if words else []):',
         repl='            for form in ([\'"\' + " ".join(words) + \'"\'] if words else []):',
         expect="finds the rule holding both words"),
    dict(name="dead-end `rule` on a topic heading, which reads as 'the rules are silent'",
         file="rules_cli.py",
         find="        if not kids and idx.is_topic_heading(r):",
         repl="        if False:",
         expect="points at where its content lives"),
    dict(name="stamp the corpus from a hardcoded literal instead of the document's own date",
         file="parse_rules.py",
         find="    return raw",
         repl="    return RULES_VERSION",
         expect="read from the document, not hardcoded"),

    # ---- round 9: merged from a parallel coverage sweep ---------------------
    # Each of these was verified by its author to make the named check FAIL.
    # Coverage before merging was 32 of 192 checks ever observed to fail.

    dict(name='Rulebook section ids drop the doc prefix, so CR and TR rules with the same number collide on one anchor',
         file='render_rulebook.py',
         find='f\'<section class="r d{min(depth, 6)}" id="{esc(anchor(doc, rid))}">\'',
         repl='f\'<section class="r d{min(depth, 6)}" id="{esc(rid)}">\'',
         expect='every rule gets an anchor'),
    dict(name='_linkify turns every in-text rule reference into a link, including the 4 TR references whose targets do not exist in this corpus',
         file='render_rulebook.py',
         find='        if rid not in known:\n            return rid',
         repl='        if False:\n            return rid',
         expect='no rulebook link points at a missing anchor'),
    dict(name='The report links at a rulebook filename the generator never writes (a rename of the generated page)',
         file='render_report.py',
         find='RULEBOOK = "../data/rules.html"',
         repl='RULEBOOK = "../data/rulebook.html"',
         expect='report emits rulebook links'),
    dict(name="render_report re-derives the anchor format locally instead of importing render_rulebook's, so the two modules drift apart",
         file='render_report.py',
         find='from render_rulebook import anchor as rulebook_anchor',
         repl='from render_rulebook import anchor as _rb_anchor\n\n\ndef rulebook_anchor(doc, rule_id):\n    return f"{doc}:{rule_id}"',
         expect='every report link resolves in the rulebook'),
    dict(name='The overlay stops intercepting a.card-rule and a.sym-rule, so those citations navigate the reader out of the report',
         file='render_report.py',
         find="closest('a.rulebook-link, a.anc-link, a.card-rule, a.sym-rule')",
         repl="closest('a.rulebook-link, a.anc-link')",
         expect='overlay intercepts every class'),
    dict(name='The overlay title regex is generalised away from the anchor format, degrading every panel title',
         file='render_report.py',
         find='m=/#([A-Z]{2})-(.+)$/.exec(href)',
         repl='m=/#(.+)$/.exec(href)',
         expect='overlay title regex still matches'),
    dict(name='The console citation tally counts only the notes again, so the terminal and the report it just wrote disagree',
         file='render_report.py',
         find='    _cites = all_cites(ans)\n    ncites = len(_cites)\n    nver = sum(1 for c in _cites if c["verified"])',
         repl='    _cites = [c for n in ans["notes"] for c in n.get("cites", [])]\n    ncites = len(_cites)\n    nver = sum(1 for c in _cites if c["verified"])',
         expect='counts every citation the verifier checked'),
    dict(name='The report headline counts only the notes, omitting the counterargument citations the verifier checked',
         file='render_report.py',
         find='    _cites = all_cites(ans)\n    ncites = len(_cites)\n    nverified = sum(1 for c in _cites if c["verified"])',
         repl='    _cites = [c for n in ans["notes"] for c in n.get("cites", [])]\n    ncites = len(_cites)\n    nverified = sum(1 for c in _cites if c["verified"])',
         expect='headline agrees with the console'),
    dict(name='all_cites drops the counterargument entirely, so console and headline agree on the same wrong number',
         file='render_report.py',
         find='    return [c for src in list(ans["notes"]) + list(ans.get("counterargument", []))\n            for c in src.get("cites", [])]',
         repl='    return [c for src in list(ans["notes"])\n            for c in src.get("cites", [])]',
         expect='reaches the counterargument path'),
    dict(name='The incomplete-text notice assigns over the errata notice instead of appending, dropping the stale-text warning on cards that carry both',
         file='render_report.py',
         find='    if c.get("incomplete"):\n        out += (f\'<span class="card-gap">Printed text incomplete',
         repl='    if c.get("incomplete"):\n        out = (f\'<span class="card-gap">Printed text incomplete',
         expect="erratum'd AND short shows both notices"),
    dict(name="The no-notes path sets _forced unconditionally, so an author's honest UNSETTLED renders as 'forced to UNSETTLED (was UNSETTLED)'",
         file='render_report.py',
         find='        if ans["holding"]["disposition"] != "UNSETTLED":\n            ans["holding"]["_forced"] = ans["holding"]["disposition"]\n            ans["holding"]["disposition"] = "UNSETTLED"\n        return ans',
         repl='        ans["holding"]["_forced"] = ans["holding"]["disposition"]\n        ans["holding"]["disposition"] = "UNSETTLED"\n        return ans',
         expect='already-UNSETTLED answer with no notes is not marked forced'),
    dict(name="card_notice emits an empty notice wrapper unconditionally, so a clean card carries a 'do not trust this text' element",
         file='render_report.py',
         find='    out = ""\n    if c.get("errata"):',
         repl='    out = \'<span class="card-gap"></span>\'\n    if c.get("errata"):',
         expect='a card with neither shows no notice'),
    dict(name="Retriever.search returns the sqlite Cursor instead of fetchall()'s rows, so a zero-hit search is truthy and reads as a hit",
         file='retrieve.py',
         find='            return self.con.execute(self._SQL, (fts_query, limit)).fetchall()',
         repl='            return self.con.execute(self._SQL, (fts_query, limit))',
         expect='genuinely absent term still returns nothing'),
    dict(name='A PEP-604 union annotation on a dataclass field, which raises TypeError at class creation on Python 3.9',
         file='verify_citations.py',
         find='    quote_verbatim: Optional[bool]   # None = no quote supplied',
         repl='    quote_verbatim: bool | None   # None = no quote supplied',
         expect='PEP-604 unions in annotations'),
    dict(name='`rules_cli.py rule` stops printing children at all, so the agent reads a rule stripped of the sub-rules that qualify it',
         file='rules_cli.py',
         find='        kids = [x for x in idx.rules.values()\n                if x["doc"] == doc and x["parent"] == rid]\n        for k in sorted(kids, key=lambda x: _idkey(x["id"])):\n            print(f"   {\'  \' * (k[\'depth\'] - 1)}{k[\'id\']}. {k[\'text\']}")',
         repl='        pass',
         expect='child-order check saw children'),
    dict(name='The console tally line is reworded so the citation count can no longer be read off it',
         file='render_report.py',
         find='    print(f"  citations   : {nver}/{ncites} verified")',
         repl='    print(f"  verified {nver} of {ncites} citations")',
         expect='the console reports a citation tally'),
    dict(name='RuleIndex.get falls back across documents when the requested doc lacks the id — a CR rule cited as TR resolves and renders Core Rules text stamped Tournament Rules',
         file='verify_citations.py',
         find='            return next((r for r in hits if r["doc"] == doc), None)\n        return hits[0] if hits else None',
         repl='            return next((r for r in hits if r["doc"] == doc), None) or (hits[0] if hits else None)\n        return hits[0] if hits else None',
         expect='rejects a CR rule cited as TR'),
    dict(name="CitationCheck.checked stops requiring the quote check to have run, so omitting the quote buys a green 'verified' stamp attesting only that the id exists",
         file='verify_citations.py',
         find='        return self.ok and self.quote_verbatim is True',
         repl='        return self.ok',
         expect="a cite with no quote is not 'checked'"),
    dict(name="verify_citation stops splitting a 'CR:194.3' prefix, so the narrowing pass compares a prefixed id against bare stored ids and flips a CORRECT quote to a failure",
         file='verify_citations.py',
         find='    if ":" in rule_id:\n        doc, rule_id = rule_id.split(":", 1)\n    rule = idx.get(rule_id, doc)',
         repl='    rule = idx.get(rule_id, doc)',
         expect='accepts the doc-prefixed cite form'),
    dict(name='narrowing is computed but never recorded, so a vague cite (829) passes through as written instead of being tightened to the rule that actually says it (829.1.b.1)',
         file='verify_citations.py',
         find='                    narrowed_to = deepest["id"]',
         repl='                    narrowed_to = None',
         expect='narrows a vague cite to the tightest rule'),
    dict(name="CitationCheck.ok drops the verbatim-quote result, so 'ok' means only that the id resolves — the four historical mis-citations (194.2.b, 471.1.b.1, 343.1) all pass",
         file='verify_citations.py',
         find='        return self.exists and self.quote_verbatim is not False and self.in_retrieved_set is not False',
         repl='        return self.exists and self.in_retrieved_set is not False',
         expect='rejects known-bad citations'),
    dict(name="RANK demotes 'structural' below 'inferred', so a legitimate inferred span resting on a structural note is wrongly reported as claiming more support than its note",
         file='render_report.py',
         find='RANK = {"grounded": 3, "structural": 2, "inferred": 2, "gap": 1}',
         repl='RANK = {"grounded": 3, "structural": 1, "inferred": 2, "gap": 1}',
         expect='known-good answer passes'),
    dict(name="both holding-span rank guards removed, so a span may claim more support than the note it rests on (a grounded span over a structural note renders as 'a rule states this')",
         file='render_report.py',
         find='        if note and RANK.get(sp.get("basis"), 0) > RANK.get(note.get("basis"), 0):\n            problems.append(\n                f\'holding span "{text[:30]}" claims {sp.get("basis")} but \'\n                f\'{note["id"]} is {note.get("basis")}\')\n        if sp.get("basis") == "grounded":\n            if note["basis"] != "grounded":\n                problems.append(\n                    f\'holding span "{text[:30]}" claims grounded but {note["id"]} is {note["basis"]}\')\n            elif not note.get("verified", True):',
         repl='        if sp.get("basis") == "grounded":\n            if False:\n                pass\n            elif not note.get("verified", True):',
         expect='rejects a span claiming more support than its note'),
    dict(name='the holding-line coverage floor is weakened from 30% to 2%, so a one-line summary that is almost entirely untyped prose passes as accountable',
         file='render_report.py',
         find='    if words and covered / max(len(line), 1) < 0.30:',
         repl='    if words and covered / max(len(line), 1) < 0.02:',
         expect='rejects an under-decomposed holding line'),
    dict(name='the crux check only rejects too MANY cruxes, so an answer with no crux at all passes and the report names no load-bearing claim',
         file='render_report.py',
         find='    if len(cruxes) != 1:',
         repl='    if len(cruxes) > 1:',
         expect='requires exactly one crux'),
    dict(name='a failed COUNTERARGUMENT citation result is computed and discarded, so a fabricated contrary rule no longer forces the verdict to UNSETTLED',
         file='render_report.py',
         find='            if not _check(c, idx, f"counterargument {i}", problems):\n                ca_failed = True',
         repl='            _check(c, idx, f"counterargument {i}", problems)',
         expect='a failed COUNTERARGUMENT cite forces UNSETTLED'),
    dict(name="note basis is no longer validated/coerced before first use, so an unknown basis in model JSON raises KeyError at RANK[n['basis']] and no report is produced at all",
         file='render_report.py',
         find='    for n in ans["notes"]:\n        if n.get("basis") not in RANK:\n            problems.append(f\'{n.get("id", "?")}: unknown basis {n.get("basis")!r}\')\n            n["basis"] = "gap"',
         repl='    pass',
         expect='an unknown note basis is reported, not crashed'),
    dict(name='a failed note citation no longer forces UNSETTLED — only counterargument failures do — so a fabricated supporting rule keeps its confident YES/NO verdict',
         file='render_report.py',
         find='    load_bearing_failed = any(not n["verified"] for n in notes) or ca_failed',
         repl='    load_bearing_failed = ca_failed',
         expect='forces UNSETTLED when a citation fails'),
    dict(name="the document label reverts to the id as written (defaulting to CR), so a bare TR-only id such as 104.1 is stamped 'CR:104.1' and Tournament Rules text reaches the reader labelled Core Rules",
         file='render_report.py',
         find='    actual_doc = doc or (resolved["doc"] if resolved else None)',
         repl='    actual_doc = doc',
         expect='a TR-only bare id is labelled TR, not CR'),
    dict(name='a citation written without a document prefix that exists only in TR is no longer reported as a problem, so the report renders green instead of refusing',
         file='render_report.py',
         find='    elif doc is None and actual_doc != "CR":\n        problems.append(\n            f\'{where}: citation {rid} has no document prefix and exists only in \'\n            f\'{actual_doc} — write it as {actual_doc}:{rid}\')',
         repl='    elif False:\n        pass',
         expect='a missing document prefix is reported'),
    dict(name="place_spans loses its document-order sort, so the monotonic cursor drops any span the model listed out of order (viktor's crux, which opens the line, renders as unmarked prose)",
         file='render_report.py',
         find='    for sp in sorted(spans, key=lambda s: line.find(s.get("text", ""))):',
         repl='    for sp in spans:',
         expect='every span renders even when listed out of document order'),
    dict(name='the unplaceable-span backstop is removed, so overlapping or duplicate holding spans verify clean while one of them silently fails to render',
         file='render_report.py',
         find='    for sp in place_spans(line, spans)[1]:\n        problems.append(',
         repl='    for sp in []:\n        problems.append(',
         expect='overlapping holding spans fail verification'),
    dict(name='the superscript note reference is emitted only for spans that carry a glyph, so grounded spans link to their note invisibly — the reader can no longer see WHICH note underwrites the claim',
         file='render_report.py',
         find='            f\'{esc(sp["text"])}</a>\'\n            f\'<a class="noteref" href="#{esc(sp["note"])}" \'\n            f\'aria-label="note {esc(num)}"><sup>{esc(glyph)}{esc(num)}</sup></a>\'',
         repl='            f\'{esc(sp["text"])}</a>\'\n            + (f\'<a class="noteref" href="#{esc(sp["note"])}" \'\n               f\'aria-label="note {esc(num)}"><sup>{esc(glyph)}{esc(num)}</sup></a>\' if glyph else "")',
         expect='a clean answer renders every one of its spans'),
    dict(name='The wrapped-cross-reference veto no longer recognises a trailing document code, so "...during gameplay. See CR" / "128. Privacy for information types." is read as a rule definition and TR:128 is fabricated again.',
         file='parse_rules.py',
         find='    r"(?:\\s+also)?(?:\\s+rules?)?(?:\\s+(?:CR|TR))?"',
         repl='    r"(?:\\s+also)?(?:\\s+rules?)?"',
         expect='fabricated as a rule'),
    dict(name='A repeated rule id is recognised as a continuation, but its text is appended to the rule that OWNS the id instead of the rule currently being read — the exact corruption that put a sentence from TR:705.3.b into TR:704.',
         file='parse_rules.py',
         find='            if rid in rules:\n                vetoed.append((n, line[:70]))\n                if cur_example is not None:\n                    cur_example.append(line.strip())\n                elif cur:\n                    rules[cur]["text"] += " " + line.strip()',
         repl='            if rid in rules:\n                vetoed.append((n, line[:70]))\n                if cur_example is not None:\n                    cur_example.append(line.strip())\n                elif cur:\n                    rules[rid]["text"] += " " + line.strip()',
         expect='does not corrupt the original rule'),
    dict(name='The reference-cue veto fires on a bare preposition again, so ordinary prose that wraps on "in"/"to" swallows the next genuine rule into the previous one (false veto = silent rule deletion).',
         file='parse_rules.py',
         find='    r"|(?:in|to|under|from)\\s+(?:rules?|CR|TR)"',
         repl='    r"|(?:in|to|under|from)"',
         expect="prose wrap on 'in'"),
    dict(name='A blank line terminates an Example again (PDF page breaks fall mid-example), so the example\'s tail is appended to the RULE\'s own text — the CR:431.2.d "randomizing it as normal, then chooses an opponent to gain 1 point" bleed.',
         file='parse_rules.py',
         find='            # runs until the next rule definition or the next Example.\n            continue',
         repl='            # runs until the next rule definition or the next Example.\n            flush_example()\n            continue',
         expect='blank line inside an Example'),
    dict(name="_looks_like_heading loses the sentence-punctuation discriminator, so any short rule ending in a full stop is treated as a heading and 467 Scoring's topic block is truncated to a single section.",
         file='verify_citations.py',
         find='        return not text.endswith((".", ":", ";")) and len(text) < 60',
         repl='        return len(text) < 60',
         expect='its block resolves to the sibling rules'),
    dict(name='is_topic_heading drops the childless requirement, so an ordinary section that happens to carry a short title (CR:829 Flow) is redirected to sibling sections it does not own.',
         file='verify_citations.py',
         find='        return not any(\n            r.get("parent") == rule["id"] and r["doc"] == rule["doc"]\n            for r in self.rules.values()\n        )',
         repl='        return True',
         expect='a section with children is not treated as a heading'),
    dict(name='topic_block stops at nothing, so a bare heading\'s block runs to the end of the document and the agent is handed dozens of unrelated sections as "where the content lives".',
         file='verify_citations.py',
         find='            if self._looks_like_heading(r):\n                break',
         repl='            if False:\n                break',
         expect='the block stops at the next heading'),
    dict(name='topic_contents skips body sections instead of stopping at them — the approach the docstring records as tried and worse — so CR:463 The Steps of Combat runs past its four steps into Layers and Modes of Play.',
         file='verify_citations.py',
         find='            if not self._looks_like_heading(r) or self._is_chapter(r):\n                break',
         repl='            if self._is_chapter(r):\n                break\n            if not self._looks_like_heading(r):\n                continue',
         expect='a chapter listing does not run past its own topic'),
    dict(name='topic_contents no longer stops at the next chapter, so TR:600 Competition Formats lists chapter 700 Enforcement and Penalties and everything under it as part of its own topic.',
         file='verify_citations.py',
         find=' or self._is_chapter(r)',
         repl='',
         expect='a contents listing stops at the next chapter'),
    dict(name='_is_chapter is simplified to "any heading", so topic_contents breaks on the first sub-heading it meets and every chapter heading resolves to nothing — a cross-reference to 463 or TR:600 reads as silence.',
         file='verify_citations.py',
         find='        return self.is_topic_heading(rule) and not self.topic_block(rule)',
         repl='        return self.is_topic_heading(rule)',
         expect='no heading resolves to nothing at all'),
    dict(name='The child test uses an id prefix instead of parent equality (mirroring subtree_parts but forgetting the dot), so every rule matches itself, nothing is ever a heading, and 467 Scoring resolves to an empty subtree = "the rules say nothing".',
         file='verify_citations.py',
         find='            r.get("parent") == rule["id"] and r["doc"] == rule["doc"]',
         repl='            r["id"].startswith(rule["id"]) and r["doc"] == rule["doc"]',
         expect='467 Scoring is recognised as a bare heading'),
    dict(name='is_topic_heading stops consulting the heading heuristic and trusts childlessness alone, so a full-sentence one-line rule (CR:002 "Card text supersedes rules text...") is presented as a heading pointing elsewhere.',
         file='verify_citations.py',
         find='        if rule.get("depth") != 1 or not self._looks_like_heading(rule):\n            return False',
         repl='        if rule.get("depth") != 1:\n            return False',
         expect='a childless one-line RULE is not treated as a heading'),
    dict(name='the symbol legend scans raw HTML without unescaping entities, so the keyword marker written as [&gt;] is never found',
         file='render_report.py',
         find='    visible = html.unescape(re.sub(r"<[^>]+>", " ", body))\n    used = scan(visible, legend)',
         repl='    visible = re.sub(r"<[^>]+>", " ", body)\n    used = scan(visible, legend)',
         expect='HTML-escaped symbol still reaches the legend'),
    dict(name='drop the CR 135.2.e.7 fallback that derives the [>] keyword marker, so the least guessable symbol vanishes from the key',
         file='symbols.py',
         find='    if "135.2.e.7" in by_id:\n        legend.setdefault(">", {',
         repl='    if False and "135.2.e.7" in by_id:\n        legend.setdefault(">", {',
         expect='non-domain symbols are derived'),
    dict(name='a `gap` span on the verdict line is drawn with the dotted structural mark again — RANK 1 rendered as RANK 2 on the one line everyone reads',
         file='render_report.py',
         find='        cls = {"grounded": "sp-grounded", "gap": "sp-gap"}.get(sp["basis"], "sp-inferred")',
         repl='        cls = {"grounded": "sp-grounded"}.get(sp["basis"], "sp-inferred")',
         expect='gap span is not drawn as a structural one'),
    dict(name='derive the basis key from the notes alone, so an inferred span over a grounded note prints a mark the key never explains',
         file='render_report.py',
         find='    used = ({n["basis"] for n in notes} | {s.get("basis") for s in spans}) - {None}',
         repl='    used = {n["basis"] for n in notes} - {None}',
         expect='key explains every mark the verdict line'),
    dict(name='a string `domain` stat is iterated per character again, rendering four chips reading F, u, r, y',
         file='render_report.py',
         find='    for d in ([dom] if isinstance(dom, str) else (dom or [])):',
         repl='    for d in (dom or []):',
         expect='a string domain is one chip'),
    dict(name='a boolean stat value is rendered as a number, so `energy: true` prints as a cost',
         file='render_report.py',
         find='        if isinstance(v, bool) or v is None:\n            continue',
         repl='        if v is None:\n            continue',
         expect='boolean is not rendered as a stat value'),
    dict(name='an unresolvable card name is silently dropped instead of marked, so the reader thinks the card was never considered',
         file='render_report.py',
         find='        else:\n            out.append({"name": name, "unresolved": True})\n    return out',
         repl='        else:\n            continue\n    return out',
         expect='an unresolvable name is marked'),
    dict(name="delete main()'s verification gate, shipping a rendered report over a fabricated citation",
         file='render_report.py',
         find='    if ans["_problems"] and "--force" not in sys.argv:',
         repl='    if False and ans["_problems"] and "--force" not in sys.argv:',
         expect='fabricated citation exits non-zero'),
    dict(name="an unmapped :rb_energy_N: shortcode collapses to a space, deleting a card's printed cost from the panel",
         file='card_bridge.py',
         find='            n = re.fullmatch(r"rb_energy_(\\d+)", code)\n            if n:\n                return f" [{n.group(1)}] "',
         repl='            n = None\n            if n:\n                return f" [{n.group(1)}] "\n            return " "',
         expect='no card loses its printed cost'),
    dict(name='long card text is hard-sliced with no truncation marker, so a card cut mid-sentence reads as its complete text',
         file='card_bridge.py',
         find='    cut = text[:limit]\n    space = cut.rfind(" ")\n    if space > limit * 0.6:\n        cut = cut[:space]\n    return cut.rstrip(" ,;:") + " …"',
         repl='    return text[:limit]',
         expect='long card text is marked as truncated'),
    dict(name='esc() reverts to `s or ""`, blanking a legitimate zero so a 0-Energy card renders with no cost at all',
         file='render_report.py',
         find='    return html.escape("" if s is None else str(s), quote=True)',
         repl='    return html.escape(str(s or ""), quote=True)',
         expect='a zero stat is not blanked'),
    dict(name='card_terms drops the `ambiguous` alias list, so one printing renders as though it were the card the answer means',
         file='card_bridge.py',
         find='                "ambiguous": card.get("ambiguous") or [],',
         repl='                "ambiguous": [],',
         expect='ambiguous card name says so on the page'),
    dict(name='print the whole derived legend instead of only the symbols on the page — every report carries rows glossing symbols the reader cannot see',
         file='render_report.py',
         find='    used = scan(visible, legend)\n    if not used:',
         repl='    used = set(legend)\n    if not used:',
         expect='every legend entry names a symbol on the page'),
    dict(name='the rail prints the weakest-link strength where the verdict belongs (a copy-paste from the line directly below it), so the rail contradicts the verdict plate beside it',
         file='render_report.py',
         find='      else esc(h["disposition"])}</span>',
         repl='      else esc(ans["_strength"].upper())}</span>',
         expect='the rail restates the verified verdict'),
    dict(name='the legend heading loses its id="symbols" anchor while the rail still emits a #symbols jump — a dead in-page link on every report with a legend',
         file='render_report.py',
         find='        \'<h2 id="symbols" data-od-id="sec-symbols">Symbols used here</h2>\'',
         repl='        \'<h2 data-od-id="sec-symbols">Symbols used here</h2>\'',
         expect='every in-page link resolves'),
    dict(name='skip the legend substitution when the legend is empty, leaving the raw <!--LEGEND--> comment in the shipped page',
         file='render_report.py',
         find='    return page.replace(LEGEND_MARKER, legend).replace(RAILSYM_MARKER, railsym)',
         repl='    if not legend:\n        return page.replace(RAILSYM_MARKER, railsym)\n    return page.replace(LEGEND_MARKER, legend).replace(RAILSYM_MARKER, railsym)',
         expect='legend placeholder is always substituted'),
    dict(name='an unknown holding-span basis is silently coerced to `inferred` with no problem reported, so an invented basis buys a structural mark',
         file='render_report.py',
         find='        if sp.get("basis") not in BASIS:\n            problems.append(\n                f\'holding span "{str(sp.get("text", ""))[:30]}" has unknown basis \'\n                f\'{sp.get("basis")!r}\')\n            sp["basis"] = "inferred"',
         repl='        if sp.get("basis") not in BASIS:\n            sp["basis"] = "inferred"',
         expect='unknown holding-span basis is reported'),
    dict(name='every citation gets the green `verified` stamp regardless of what the verifier concluded — the --force escape hatch stops showing which cite failed',
         file='render_report.py',
         find='    scls = "ok" if c["verified"] else "bad"',
         repl='    scls = "ok"',
         expect='--force renders but marks the citation failed'),
    dict(name='note_number returns the raw id instead of its digits, so every superscript note ref renders as "n12" rather than "12"',
         file='render_report.py',
         find='    digits = "".join(ch for ch in str(note_id) if ch.isdigit())\n    return digits or str(note_id)',
         repl='    digits = "".join(ch for ch in str(note_id) if ch.isdigit())\n    return str(note_id)',
         expect='note ids reduce to numbers'),
    dict(name='a note whose basis is missing or invalid is coerced to `gap` with no problem reported, so a malformed note renders as an honest abstention',
         file='render_report.py',
         find='        if n.get("basis") not in RANK:\n            problems.append(f\'{n.get("id", "?")}: unknown basis {n.get("basis")!r}\')\n            n["basis"] = "gap"',
         repl='        if n.get("basis") not in RANK:\n            n["basis"] = "gap"',
         expect='note missing its basis is reported'),
    dict(name='pin a legend row to a hardcoded rule id that a renumber has removed — the exact fabricated-citation shape the derived legend exists to prevent',
         file='symbols.py',
         find='            "meaning": described[">"], "rule": "135.2.e.7", "colour": None,',
         repl='            "meaning": described[">"], "rule": "999.9.z", "colour": None,',
         expect='every legend entry cites a real rule'),
    dict(name='EMBED_ART becomes the raw env string, so RIFTBOUND_EMBED_ART=0 or =false silently turns artwork embedding ON',
         file='render_report.py',
         find='EMBED_ART = os.environ.get("RIFTBOUND_EMBED_ART", "").lower() in ("1", "true", "yes")',
         repl='EMBED_ART = os.environ.get("RIFTBOUND_EMBED_ART", "")',
         expect='artwork embedding is off unless'),
    dict(name='look a card up without lowercasing the name, so the vendored lowercase index misses every properly-cased name and real cards render "no card by this name"',
         file='render_report.py',
         find='        card = bridge.cards.get(name.lower()) if bridge else None',
         repl='        card = bridge.cards.get(name) if bridge else None',
         expect='named card resolves to text + artwork'),
    dict(name='a card database that failed to load reports every card as nonexistent again — a tooling failure converted into a factual claim about the corpus',
         file='render_report.py',
         find='        elif unavailable:\n            out.append({"name": name, "unavailable": unavailable})',
         repl='        elif False:\n            out.append({"name": name, "unavailable": unavailable})',
         expect='unreadable card data is not reported'),
    dict(name='stats_html trusts any non-None value, so a model-supplied string stats field ("4 Energy") crashes the render and produces no report',
         file='render_report.py',
         find='    if not isinstance(stats, dict):\n        return ""',
         repl='    if stats is None:\n        return ""',
         expect='stats_html survives'),
    dict(name='the domain shorthands are derived from the wrong CR section (a renumber not followed through), so all six colour symbols disappear from the legend',
         file='symbols.py',
         find='        if not rid.startswith("134.2."):',
         repl='        if not rid.startswith("134.3."):',
         expect='all six domain shorthands are derived'),
    dict(name="trust the answer's corpus stamp instead of cross-checking it against the versions the index was built from, so the masthead asserts an unverified rules version",
         file='render_report.py',
         find='        if claimed and stamped and claimed not in stamped:',
         repl='        if False and claimed and stamped and claimed not in stamped:',
         expect='corpus stamp contradicting the index'),

    dict(name='truncate the output file before rendering, so a crash inside render '
              'leaves a 0-byte report where a good one used to be',
         file='render_report.py',
         find='    html_out = render(ans, idx)',
         repl='    open(out, "w").close()\n    html_out = render(ans, idx)',
         expect='crash inside render leaves the previous report intact'),

    # ---- disposition vocabulary ---------------------------------------------
    dict(name='accept any string as a disposition again, so a value with spaces '
              'becomes several bogus CSS classes and disables the print sheet',
         file='render_report.py',
         find='    if _disp not in DISPOSITIONS:',
         repl='    if False:',
         expect='outside the vocabulary is refused'),
    dict(name='print a verdict word on an open question, so "how much energy?" is '
              'headlined with a token that means nothing',
         file='render_report.py',
         find='    {"" if disp == "ANSWER" else f\'<span class="disp {esc(disp)}">{esc(disp)}</span>\'}',
         repl='    <span class="disp {esc(disp)}">{esc(disp)}</span>',
         expect='prints no verdict word'),
    dict(name='stop promoting the holding line when there is no verdict word, so an '
              'open question has no headline at all',
         file='render_report.py',
         find='  <p class="hline{" is-lead" if disp == "ANSWER" else ""}">{holding_html(h)}</p>',
         repl='  <p class="hline">{holding_html(h)}</p>',
         expect='leads with the holding line'),

    # ---- round 10: the last two invariant gaps ------------------------------
    dict(name='write the report in place again, so a failure mid-write destroys the previous ruling saved at that path',
         file='render_report.py',
         find='    tmp = out + ".tmp"\n    try:\n        with open(tmp, "w", encoding="utf-8") as fh:\n            fh.write(html_out)\n        os.replace(tmp, out)',
         repl='    tmp = out + ".tmp"\n    try:\n        with open(out, "w", encoding="utf-8") as fh:\n            raise OSError("disk full")',
         expect='failed write leaves the previous ruling intact'),
    dict(name='let the committed rulebook drift from its generator, so every report links into a document that no longer matches the code',
         file='render_rulebook.py',
         find=' --line:var(--ink-500);',
         repl=' --line:var(--ink-400);',
         expect='committed rulebook matches'),
    # Shrinks the corpus AFTER the parse completes. Mutating mid-parse (deleting
    # rules, truncating the input) leaves `cur` pointing at a rule that no longer
    # exists and crashes instead of shrinking — detected, but by a traceback
    # rather than by the check whose whole job is to notice drift.
    dict(name='silently drop rules from the corpus after parsing, so the shipped '
              'index is smaller than the document it claims to represent',
         file='parse_rules.py',
         find='        json.dump(rules_list, open(out, "w", encoding="utf-8"), indent=1)',
         repl='        json.dump(rules_list[:-40], open(out, "w", encoding="utf-8"), indent=1)',
         expect='matches the recorded corpus exactly', rebuild=True),

    dict(name='point deep rules at a parent that does not exist, orphaning them',
         file='parse_rules.py',
         find='                "parent": parent_of(rid),',
         repl='                "parent": (parent_of(rid) if rid.count(".") < 2 else rid + ".nonexistent"),',
         expect='orphaned parents', rebuild=True),
    # ---- the primer document kind -------------------------------------------
    # Two kinds means a new way to verify the wrong thing. These pin the two
    # properties that are new here and exist nowhere on the ruling path: a
    # transition is a claim, and the diagram is derived from those claims.
    dict(name='default an unrecognised `kind` to ruling, so a typo routes a primer '
              'down a path that never reads a single one of its keys',
         file='rules_cli.py',
         find='    kind = ans.get("kind", "ruling")\n    if kind not in KINDS:',
         repl='    kind = ans.get("kind", "ruling")\n    kind = kind if kind in KINDS else "ruling"\n    if False:',
         expect='unknown `kind` is refused'),
    # The backward-compatibility guarantee, and the most consequential thing in
    # the whole two-document design: every answer file written before primers
    # existed omits `kind`, and defaulting the other way routes all of them at a
    # verifier that reads none of their keys.
    dict(name='default a `kind`-less answer to primer, so every ruling ever written '
              'routes to a verifier that reads none of its keys',
         file='rules_cli.py',
         find='    kind = ans.get("kind", "ruling")',
         repl='    kind = ans.get("kind", "primer")',
         expect='an answer with no `kind` is a ruling'),
    # Masked until now: deleting this gate left the suite green, because the
    # renderer it shells out to refuses again. Two guards, each hiding the
    # other from a one-at-a-time battery.
    dict(name="delete `report`'s own verification gate, leaving the renderer's to "
              'catch what it lets through — the documented gate, pinned by nothing',
         file='rules_cli.py',
         find='''    ans = verify(raw, _idx())
    if ans["_problems"]:''',
         repl='''    ans = verify(raw, _idx())
    if False:''',
         expect='at its OWN gate'),
    dict(name="make `verify` exit 0 whatever it found, so its whole contract — the "
              'exit code — stops meaning anything',
         file='rules_cli.py',
         find='    sys.exit(1 if ans["_problems"] else 0)',
         repl='    sys.exit(0)',
         expect='through its exit code'),
    # A primer need not be a procedure. If the shape checks stop exempting one
    # with no transitions, the only primers this skill can write are loops —
    # "the parts of a card" becomes unrepresentable.
    dict(name='apply the procedure shape checks to a primer that declares no '
              'transitions, so a linear explainer is refused for having no way out',
         file='render_primer.py',
         find='    if not any(s.get("exits") for s in steps):\n        return problems',
         repl='    if False:\n        return problems',
         expect='a linear primer with no transitions is still valid'),
    # The sweep replaced an O(E x lanes) scan. Correctness is the property it
    # had to preserve, and "it is fast now" is not evidence of it.
    dict(name='hand every gutter transition the same lane, so overlapping arrows are '
              'drawn on top of each other',
         file='flowgraph.py',
         find='        if free:\n            lane = heapq.heappop(free)\n        else:\n            lane, next_lane = next_lane, next_lane + 1',
         repl='        lane = 0',
         expect='share a lane while their spans overlap'),
    # The concession has to stay available. If `structural` also demanded a
    # citation there would be no honest way to record a move the rules imply,
    # and an author would either invent a citation or omit the transition.
    dict(name='demand a citation from a transition that declares itself structural, so '
              'a move the rules only imply cannot be recorded at all',
         file='render_primer.py',
         find='            if ex["basis"] == "grounded" and not ex.get("cites"):',
         repl='            if not ex.get("cites"):',
         expect='may go uncited if it DECLARES itself structural'),
    dict(name='let a transition assert that the rules send you somewhere without '
              'citing the rule that says so',
         file='render_primer.py',
         find='            if ex["basis"] == "grounded" and not ex.get("cites"):',
         repl='            if False:',
         expect='uncited transition fails verification'),
    dict(name='grade a primer on its steps alone, so a document whose every '
              'transition is a guess still reports itself grounded',
         file='render_primer.py',
         find="""        for ex in s.get("exits") or []:
            n += 1
            graded.append((s["id"], ex["basis"], f"transition {n}"))""",
         repl="""        for ex in s.get("exits") or []:
            n += 1""",
         expect='reports structural as its weakest link'),
    dict(name="file a transition's basis under its source step, so the page names a "
              'weakest step whose own chip says something else',
         file='render_primer.py',
         find='            graded.append((s["id"], ex["basis"], f"transition {n}"))',
         repl='            graded.append((s["id"], ex["basis"], f"step {i}"))',
         expect='weakest link names what is actually weakest'),
    dict(name='let a transition claim the rules are silent without showing what it searched',
         file='render_primer.py',
         find='            if ex["basis"] == "gap" and not ex.get("rules_checked"):\n'
              '                problems.append(f"{where}: gap transition must list rules_checked")',
         repl='            if False:\n                pass',
         expect='gap TRANSITION must list rules_checked'),
    dict(name='accept a goto naming no step, so the derived diagram draws an arrow to nothing',
         file='render_primer.py',
         find='            if goto is not None and goto not in known:',
         repl='            if False:',
         expect='goto naming no step is refused'),
    dict(name='stop noticing a step nothing reaches, leaving an orphan box on the map',
         file='render_primer.py',
         find='    for s in steps[1:]:\n        if s.get("id") not in reachable:',
         repl='    for s in []:\n        if s.get("id") not in reachable:',
         expect='step nothing reaches is refused'),
    dict(name='accept a procedure with no way out, describing a loop play can never leave',
         file='render_primer.py',
         find='    if not any(ex.get("goto") is None\n               for s in steps for ex in (s.get("exits") or [])):',
         repl='    if False:',
         expect='procedure with no way out is refused'),
    dict(name='stop checking step ids for uniqueness, so every link to the duplicate '
              'resolves to the first',
         file='render_primer.py',
         find='    check_unique_ids(steps, "step", problems)\n    known = {s.get("id") for s in steps}',
         repl='    known = {s.get("id") for s in steps}',
         expect='duplicate step ids are refused'),
    dict(name="count only a primer's steps in its citation tally, so the headline "
              'under-reports every transition it verified',
         file='render_primer.py',
         find='    for step in ans.get("steps", []):\n        yield step\n'
              '        for ex in step.get("exits", []) or []:\n            yield ex',
         repl='    for step in ans.get("steps", []):\n        yield step',
         expect='counts steps, transitions AND misconceptions'),
    dict(name='drop a transition from the derived diagram, so the map shows fewer '
              'moves than the primer declares',
         file='flowgraph.py',
         find='            edges.append({\n                "n": n, "from": i, "to": target, "kind": kind,',
         repl='            if kind == "self":\n                continue\n'
              '            edges.append({\n                "n": n, "from": i, "to": target, "kind": kind,',
         expect='one edge per declared transition'),
    dict(name='number only the transitions that go somewhere, so the map and the '
              'prose disagree about which arrow is which',
         file='flowgraph.py',
         find='            n += 1\n            goto = ex.get("goto")',
         repl='            goto = ex.get("goto")\n            if goto:\n                n += 1',
         expect='numbered in the prose beside it'),
    dict(name='draw every arrow solid, so a transition that merely follows from the '
              'rules looks like one they state outright',
         file='flowgraph.py',
         find="""    dash = (' stroke-dasharray="9 4"' if failed
            else "" if e["basis"] == "grounded" else ' stroke-dasharray="4 3"')""",
         repl=(chr(32) * 4 + "dash = ' stroke-dasharray=" + chr(34) + "9 4"
               + chr(34) + "' if failed else " + chr(34) * 2),
         expect='structural transition draws a dashed one'),
    dict(name='render a primer that failed verification anyway, with no flag asked for',
         file='render_primer.py',
         find='    if ans["_problems"] and "--force" not in sys.argv:\n'
              '        print("VERIFICATION FAILED — refusing to render:", file=sys.stderr)',
         repl='    if False:\n        print("VERIFICATION FAILED — refusing to render:", file=sys.stderr)',
         expect='fabricated primer citation'),
    dict(name='emit a diagram from an unverified primer, handing a website a picture '
              'this project never stood behind',
         file='rules_cli.py',
         find='    if ans["_problems"]:\n        print("VERIFICATION FAILED — not emitting a graph:", file=sys.stderr)',
         repl='    if False:\n        print("VERIFICATION FAILED — not emitting a graph:", file=sys.stderr)',
         expect='refuses to emit a diagram for it too'),
    dict(name='drop the last step from the derived graph, so the map shows fewer '
              'steps than the primer walks through',
         file='flowgraph.py',
         find='             for i, s in enumerate(steps)]',
         repl='             for i, s in enumerate(steps[:-1])]',
         expect='one node per declared step'),
    dict(name='resolve every goto one step off, so each arrow lands on the step '
              'after the one the primer named',
         file='flowgraph.py',
         find='    order = {s["id"]: i for i, s in enumerate(steps)}',
         repl='    order = {s["id"]: i + 1 for i, s in enumerate(steps)}',
         expect='lands on a step the primer declares'),
    dict(name='dash every arrow, so a move the rules state outright looks like an inference',
         file='flowgraph.py',
         find="""    dash = (' stroke-dasharray="9 4"' if failed
            else "" if e["basis"] == "grounded" else ' stroke-dasharray="4 3"')""",
         repl="""    dash = ' stroke-dasharray="4 3"' """.rstrip(),
         expect='draws no dashed arrow'),
    dict(name='mangle the mermaid node ids, so the exported graph names steps that '
              'do not exist',
         file='flowgraph.py',
         find='    return "S_" + "".join(ch if ch.isalnum() else "_" for ch in str(step_id))',
         repl='    return "S_x" + "".join(ch if ch.isalnum() else "_" for ch in str(step_id))',
         expect='names only real steps'),
    dict(name='let a step claim the rules are silent without showing what it searched',
         file='render_primer.py',
         find='        if s["basis"] == "gap" and not s.get("rules_checked"):',
         repl='        if False:',
         expect='gap STEP must list rules_checked'),
    dict(name='write the primer in place again, so a failure mid-write destroys the '
              'previous page saved at that path',
         file='render_primer.py',
         find='    tmp = out + ".tmp"\n    try:\n        with open(tmp, "w", encoding="utf-8") as fh:\n            fh.write(html_out)\n        os.replace(tmp, out)',
         repl='    tmp = out + ".tmp"\n    try:\n        with open(out, "w", encoding="utf-8") as fh:\n            raise OSError("disk full")',
         expect='failed write leaves the previous primer intact'),
    dict(name='write the diagram colours as literals, so the print sheet cannot remap '
              'them and a printed map keeps its dark-ground palette on white',
         file='flowgraph.py',
         find='''EDGE_COLOUR = {
    "grounded": "var(--gold-500)",''',
         repl='''EDGE_COLOUR = {
    "grounded": "#c8aa6e",''',
         expect='no colour the print sheet cannot remap'),
    dict(name='drop the primer print sheet, so the map prints white-on-white',
         file='render_primer.py',
         find='@media print{\n .summary,.step:target{background:transparent}\n .topic{color:var(--fg)}',
         repl='@media screen{\n .summary,.step:target{background:transparent}\n .topic{color:var(--fg)}',
         expect="print sheet inverts the map"),
    dict(name='fix the transition badge at one digit wide again, clipping the second '
              'digit of every transition past nine',
         file='flowgraph.py',
         find="    w = 18 if len(str(n)) < 2 else 11 + 7 * len(str(n))",
         repl="    w = 18",
         expect='wide enough for its own number'),
    dict(name='draw a map for a primer that has no transitions, so a linear '
              'explainer gets a column of boxes with nothing between them',
         file='flowgraph.py',
         find='    if not nodes or not any(e["kind"] != "broken" for e in edges):',
         repl='    if not nodes:',
         expect='draws no map'),
    dict(name='assume every step is an object again, so a malformed one crashes '
              'verification and hides every problem found after it',
         file='render_primer.py',
         find='        if not isinstance(item, dict):',
         repl='        if False:',
         expect='not an object is reported, not crashed'),
    dict(name='assume `exits` is a list of objects, so a bare string is iterated '
              'one character at a time',
         file='render_primer.py',
         find='''        if exits is not None and (not isinstance(exits, list)
                                  or any(not isinstance(x, dict) for x in exits)):''',
         repl='        if False:',
         expect='is not a list of objects is reported'),
    dict(name='resolve relative output paths against the skill folder again, so a '
              'report lands somewhere the caller never named and is reported as written',
         file='rules_cli.py',
         find='''    if os.path.isabs(path):
        return path
    return os.path.join(default_dir or CWD, path)''',
         repl='''    return path''',
         expect='lands where the caller ran the command'),
    dict(name='bind the first argument after the source as the destination again, so '
              '--force becomes the output path',
         file='rules_cli.py',
         find='''    pos = [a for a in args if not a.startswith("-")]
    src = pos[0]
    out = _out_path(pos[1]) if len(pos) > 1 else _out_path("report.html")''',
         repl='''    src = args[0]
    out = _out_path(args[1]) if len(args) > 1 else _out_path("report.html")''',
         expect='not bound as the render destination'),
    dict(name='escape only the quote in a mermaid label again, so a step heading '
              'containing a tag is markup wherever the graph is finally drawn',
         file='flowgraph.py',
         find='''    return "".join(_MERMAID_ESCAPES.get(ch, ch)
                   for ch in " ".join(str(text).split()))''',
         repl='''    return " ".join(str(text).split()).replace('"', "'")''',
         expect='escapes every label'),
    dict(name='stop collapsing whitespace in a mermaid label, so a newline in a '
              'heading ends the statement early and truncates the graph',
         file='flowgraph.py',
         find='''    return "".join(_MERMAID_ESCAPES.get(ch, ch)
                   for ch in " ".join(str(text).split()))''',
         repl='''    return "".join(_MERMAID_ESCAPES.get(ch, ch) for ch in str(text))''',
         expect='collapses a newline rather than truncating'),
    dict(name='number a step from digits in its id again, so a primer whose steps '
              'are not called s1..sN links to numbers its own plates never show',
         file='render_primer.py',
         find='''        number, heading = steps_by_id.get(goto, ("?", goto))''',
         repl='''        from render_report import note_number
        number, heading = note_number(goto), steps_by_id.get(goto, (0, goto))[1]''',
         expect='numbers the step it points at by position'),
    dict(name='stop running the shared provenance checks on the primer path, so a '
              'primer can misdate the corpus and cite rules that do not exist',
         file='render_primer.py',
         find='''    check_corpus_stamp(ans, idx, problems)
    check_considered_rejected(ans, idx, problems)
    check_card_sections(ans, idx, problems)''',
         repl='''    pass''',
         expect='shared provenance checks run on the primer path'),
    dict(name='assume every step carries an id, so one without it raises KeyError '
              'inside verification and the author gets a traceback, not a problem list',
         file='render_primer.py',
         find='        if not str(item.get("id") or "").strip():',
         repl='        if False:',
         expect='a step with no id is reported, not crashed'),
    dict(name='scope the forced-render banner back to citations, so a primer that '
              'failed verification some other way prints as though it passed',
         file='render_primer.py',
         find='    ans["_unverified"] = bool(problems)',
         repl='    ans["_unverified"] = any(not c.get("verified", False) for c in all_cites(ans))',
         expect='marked whatever kind of verification it failed'),
    dict(name='estimate every glyph at one average width again, so an ordinary '
              'heading runs out of its box and over the transition arrows',
         file='flowgraph.py',
         find='''def _char_w(ch):
    if ch == " ":
        return 3.3''',
         repl='''def _char_w(ch):
    if True:
        return 6.15''',
         expect='clipped to fit inside its box'),
    dict(name='drop the geometric clip on a step label, leaving nothing but an '
              'estimate between a long heading and the arrows beside it',
         file='flowgraph.py',
         find='''            f'clip-path="url(#fg-box)">' ''' .rstrip(),
         repl='''            f'>' ''' .rstrip(),
         expect='cut at the box edge even if the estimate is wrong'),
    dict(name='stop normalising rules_checked to strings, so a list of plain '
              'integers verifies clean and then kills the renderer',
         file='render_report.py',
         find='''        refs = [str(x) for x in (item.get("rules_checked") or [])]
        if refs:
            item["rules_checked"] = refs
        elif "rules_checked" in item:
            item.pop("rules_checked")''',
         repl='''        refs = [str(x) for x in (item.get("rules_checked") or [])]''',
         expect='written as numbers verifies AND renders'),
    dict(name='subscript a step heading the verifier already complained about, so '
              '--force crashes on the one kind of document it exists for',
         file='render_primer.py',
         find='      <h3>{esc(s.get("heading", ""))}</h3>',
         repl='      <h3>{esc(s["heading"])}</h3>',
         expect='still renders under --force'),
    dict(name='subscript a misconception the verifier already rejected, so --force '
              'crashes on the document it exists to show you',
         file='render_primer.py',
         find='  <h3>“{esc(m.get("belief", ""))}”</h3>',
         repl='  <h3>“{esc(m["belief"])}”</h3>',
         expect='every malformed field is reported'),
    dict(name='accept a bare string where a list belongs, so "cards": "Astral Heron" '
              'renders twelve cards, each of them not found',
         file='render_primer.py',
         find='''        if value is not None and not isinstance(value, list):''',
         repl='''        if False:''',
         expect='iterated one character at a time'),

    # ---- what the review pass found ----------------------------------------
    dict(name='style a diagram edge from its declared basis alone, so a citation '
              'that failed the verbatim check still draws as a confident gold arrow',
         file='flowgraph.py',
         find='    failed = not e.get("verified", True)',
         repl='    failed = False',
         expect='drawn unmistakably, not as a confident arrow'),
    dict(name='draw every fall-through at the spine again, so two transitions '
              'between the same pair of steps collapse into one arrow',
         file='flowgraph.py',
         find='            elif target == i + 1 and not spine_used[i]:',
         repl='            elif target == i + 1:',
         expect='draw two arrows'),
    dict(name="count undrawable transitions in the map's accessible description, so "
              'a screen reader is told about an arrow nobody can see',
         file='flowgraph.py',
         find='    drawn = [e for e in edges if e["kind"] != "broken"]',
         repl='    drawn = list(edges)',
         expect='counts the arrows it actually drew'),
    dict(name='drop the readability cap, so a hundred-step primer verifies clean and '
              'renders a map three hundred thousand pixels wide',
         file='render_primer.py',
         find='    if len(steps) > MAX_STEPS:',
         repl='    if False:',
         expect='too many steps to read as a map is refused'),
    dict(name='drop the transition cap, so a primer needing more gutter lanes than a '
              'page can carry still renders its wall of a map',
         file='render_primer.py',
         find='    if transitions > MAX_TRANSITIONS:',
         repl='    if False:',
         expect='too many transitions to draw is refused'),
    dict(name='drop the whole map section when nothing in it can be drawn, so a '
              'primer that declares transitions silently shows no diagram at all',
         file='render_primer.py',
         find='    undrawable = declared_exits and not diagram',
         repl='    undrawable = False',
         expect='undrawable map says so rather than disappearing'),

    # ---- the exported diagram ------------------------------------------------
    # Invariant 12 does not stop at the report: a Fireworks SVG travels to a
    # website and a deck, away from the prose and the ✓ VERIFIED stamps.
    dict(name='export an arrow for a transition that cannot be drawn, so the picture '
              'shows a move the document could not place',
         file='fireworks_ir.py',
         find='    drawn = [e for e in edges if e["kind"] != "broken"]',
         repl='    drawn = list(edges)',
         expect='cannot be placed is not exported'),
    dict(name='mint the exit node id without checking the steps, so a primer that '
              'declares that id exports two nodes sharing one',
         file='fireworks_ir.py',
         find='    while end_id in taken:\n        end_id += "_"',
         repl='    while False:\n        end_id += "_"',
         expect='survives shapes the shipped primers do not have'),
    dict(name='rename the nodes on the way out, so the exported picture names steps '
              'the document does not declare',
         file='fireworks_ir.py',
         find='            "id": node["id"],\n            "kind": "rect",',
         repl='            "id": node["id"] + "_x",\n            "kind": "rect",',
         expect='every node in the export is a declared step'),
    dict(name='number the exported arrows by their source step instead of by the '
              'transition, so the picture and the prose stop agreeing',
         file='fireworks_ir.py',
         find='            "label": str(edge["n"]),',
         repl='            "label": str(edge["from"] + 1),',
         expect='exported arrows carry the same numbers as the prose'),
    dict(name='let a committed diagram drift from its generator, so a picture shipped '
              'with the skill goes on asserting a procedure the corpus no longer describes',
         file='fireworks_ir.py',
         find='BOX_H = 72',
         repl='''BOX_H = 73''',
         expect='committed diagram matches what this corpus now produces'),
    dict(name='export a diagram edge in its declared class even when its citation '
              'failed, so the picture that travels looks fully verified',
         file='fireworks_ir.py',
         find='''def _flow(edge):
    if not edge.get("verified", True):
        return FLOW_UNVERIFIED''',
         repl='''def _flow(edge):
    if False:
        return FLOW_UNVERIFIED''',
         expect='exported in the failed class'),
    dict(name='drop a basis from the export mapping, so a structural transition is '
              'drawn in the class the legend calls "the rules do not settle it"',
         file='fireworks_ir.py',
         find='    "structural": "read",\n    "inferred": "read",',
         repl='    "inferred": "read",',
         expect='every basis maps to an edge class'),
    dict(name='print the whole legend regardless of what was drawn, so a reader holds '
              'three rules for a diagram that uses one',
         file='fireworks_ir.py',
         find='    used = {_flow(e) for e in edges if e["kind"] != "broken"}\n'
              '    return [{"flow": flow, "label": label} for flow, label in rows if flow in used]',
         repl='    return [{"flow": flow, "label": label} for flow, label in rows]',
         expect='legend lists only the edge classes actually drawn'),
    dict(name='strip the provenance from the exported subtitle, so a diagram that '
              'leaves the report cannot say which corpus it came from',
         file='fireworks_ir.py',
         find='''    return ("derived from the transitions this primer declares"
            f"{stamp} · unofficial")''',
         repl='''    return "derived from the transitions this primer declares"''',
         expect='carries its corpus version and says it is unofficial'),
    dict(name='require a Fireworks install before writing the IR, so a machine '
              'without one gets nothing instead of a renderable document',
         file='rules_cli.py',
         find='    fireworks = find_fireworks()\n    if not fireworks:',
         repl='    fireworks = find_fireworks()\n    if not fireworks:\n        sys.exit(1)\n    if False:',
         expect='the IR is still written'),
    dict(name='render straight over the destination again, so an external renderer '
              'that fails part-way destroys the diagram already sitting there',
         file='rules_cli.py',
         find='    staged = svg_out + ".rendering"',
         repl='    staged = svg_out',
         expect='failed render leaves the previous diagram untouched'),
    dict(name='leave the staging file behind when a render fails, so a half-written '
              'diagram sits beside the good one looking like an artifact',
         file='rules_cli.py',
         find='''    if run.returncode != 0 or not os.path.exists(staged):
        _discard(staged)''',
         repl='''    if run.returncode != 0 or not os.path.exists(staged):
        pass''',
         expect='clears up after itself rather than leaving a staging file'),
    dict(name='trust the renderer exit code instead of the artifact, so `<svg><g>` and '
              'exit 0 is announced as a diagram no viewer will open',
         file='rules_cli.py',
         find='    if run.returncode != 0 or not _looks_like_svg(staged):',
         repl='    if run.returncode != 0:',
         expect='a truncated render is not announced as a diagram'),
    dict(name='prefer stdout however blank it is, so a renderer that prints whitespace '
              'there and its real error to stderr reports nothing at all',
         file='rules_cli.py',
         find='''    for stream in (run.stderr, run.stdout):
        text = (stream or "").strip()
        if text:
            return text[:300]''',
         repl='''    return ((run.stdout or run.stderr) or "")[:300]''',
         expect="the renderer's own complaint reaches the user"),
    dict(name='fall through a mis-set $RIFTBOUND_FIREWORKS to whatever else is '
              'installed, so a typo renders from a different install in silence',
         file='rules_cli.py',
         find='''        if not os.path.exists(script):
            raise SystemExit(''',
         repl='''        if False:
            raise SystemExit(''',
         expect='a mis-set override is refused'),
    dict(name='exit 0 when the caller named an SVG that was never produced, so a '
              'green exit code says they got the file they asked for',
         file='rules_cli.py',
         find='        sys.exit(1 if explicit else 0)',
         repl='        sys.exit(0)',
         expect='not reported as success'),
    # Breaks the GRAPH BUILDER, not the check. Mutating the guard out changes
    # nothing while flowgraph is healthy — the defect is the pair, and this is
    # the half a single-site mutant can express: with no edges to compare, the
    # `len(drawn) > 0` guard is what makes the check go red instead of passing
    # on three empty fallbacks.
    dict(name='derive a graph with no transitions at all, so every per-primer diagram '
              'assertion has nothing left to compare',
         file='flowgraph.py',
         find='    _assign_lanes(nodes, edges)\n    _assign_ports(nodes, edges)\n    return nodes, edges',
         repl='    _assign_lanes(nodes, edges)\n    _assign_ports(nodes, edges)\n    return nodes, []',
         expect='the report, the map and the export agree on every transition'),
    dict(name='stop noticing a truncated committed SVG, so a half-written picture '
              'ships beside a correct derivation',
         file='selftest.py',
         find='    if not body.rstrip().endswith("</svg>"):\n        return "the committed SVG is truncated"',
         repl='    if False:\n        return "the committed SVG is truncated"',
         expect='a truncated committed SVG is detected'),
    dict(name='stop comparing a committed SVG to the arrows its own IR declares, so a '
              'picture of a different procedure ships beside the right derivation',
         file='selftest.py',
         find='    if drawn and sorted(labels) and drawn != sorted(labels):',
         repl='    if False:',
         expect='drawing different arrows from its IR is detected'),
    dict(name='test only whether a step is named by something, so a disconnected '
              'island of steps that name each other passes',
         file='render_primer.py',
         find='''    reachable, frontier = {steps[0].get("id")}, [steps[0]]''',
         repl='''    reachable, frontier = {s.get("id") for s in steps}, []''',
         expect='disconnected island of steps is refused'),
    dict(name='report a transition-level problem under an id transitions do not '
              'have, leaving every one of them as "?"',
         file='render_primer.py',
         find='''        check_rules_checked(s.get("exits", []) or [], idx, problems,
                            label=lambda n, sid=sid: f"{sid} transition {n}")''',
         repl='''        check_rules_checked(s.get("exits", []) or [], idx, problems)''',
         expect='names the transition'),
    dict(name='drop an unreadable step instead of keeping its slot, renumbering '
              'every step after it and quietly losing a box from the map',
         file='render_primer.py',
         find='''            kept.append({
                "id": f"_unreadable{i}", "basis": "gap", "rules_checked": ["300"],''',
         repl='''            continue
            kept.append({
                "id": f"_unreadable{i}", "basis": "gap", "rules_checked": ["300"],''',
         expect='keeps its slot rather than renumbering'),
    dict(name='let two step ids collapse to one mermaid node, turning a cited '
              'transition between them into a self-loop',
         file='flowgraph.py',
         find='        ids[node["id"]] = base if seen[base] == 1 else f"{base}__{seen[base]}"',
         repl='        ids[node["id"]] = base',
         expect='its own node'),
    dict(name='strip -primer from the report slug again, so a primer and a ruling on '
              'one subject overwrite each other',
         file='rules_cli.py',
         find='    slug = os.path.splitext(os.path.basename(src))[0].replace("-answer", "")',
         repl='    slug = os.path.splitext(os.path.basename(src))[0].replace("-answer", "").replace("-primer", "")',
         expect='do not overwrite each other'),
    dict(name="stop guarding the shape of `cites`, so a bare string aborts "
              'verification and every problem found after it goes unreported',
         file='render_report.py',
         find='''    cites = item.get("cites")
    if cites is None:
        return []''',
         repl='''    cites = item.get("cites")
    if True:
        return cites or []''',
         expect='malformed field is reported'),
]

FAILED_RE = re.compile(r"^FAILED \d+ of \d+: (.*)$", re.M)


def run_one(m):
    """Apply one mutant to a throwaway copy and report which checks caught it."""
    with tempfile.TemporaryDirectory() as d:
        skill = os.path.join(d, "rules-report")
        # `rules.db` IS copied. Excluding it was a speed optimisation until the
        # research-path checks arrived: without the index every mutant made the
        # suite exit at "Rule index missing", which the battery then reported as
        # a crash rather than as a caught defect — 29 false crashes at once.
        shutil.copytree(SKILL, skill, ignore=shutil.ignore_patterns(
            "reports", "__pycache__", "*.tmp"))
        lib = os.path.join(skill, "lib")
        path = os.path.join(lib, m["file"])
        src = open(path, encoding="utf-8").read()
        if src.count(m["find"]) != 1:
            return None, (f"anchor matched {src.count(m['find'])}x — the mutant is "
                          "stale and is testing nothing")
        src = src.replace(m["find"], m["repl"])
        if m.get("also"):
            find2, repl2 = m["also"]
            if src.count(find2) != 1:
                return None, "second anchor did not match — the mutant is stale"
            src = src.replace(find2, repl2)
        open(path, "w", encoding="utf-8").write(src)

        if m.get("rebuild"):
            # parse_rules changes only reach the suite through rules.json, and a
            # rebuild parses SOURCE markdown that deliberately lives outside the
            # skill folder this sandbox copies. Point it at the real sources via
            # the documented override; it is read-only, and the only thing it
            # can affect is the throwaway rules.json inside the sandbox.
            env = dict(os.environ)
            src = os.path.join(REPO_ROOT, "output")
            if os.path.isdir(src):
                env["RIFTBOUND_CORPUS"] = src
            rc = subprocess.run([sys.executable, os.path.join(lib, "rules_cli.py"), "build"],
                                capture_output=True, text=True, cwd=lib, env=env)
            if rc.returncode != 0:
                return ["<suite crashed> corpus rebuild failed: "
                        + (rc.stderr.strip().splitlines() or ["?"])[-1]], None
        if m.get("regen"):
            subprocess.run([sys.executable, os.path.join(lib, "rules_cli.py"), "rulebook"],
                           capture_output=True, text=True, cwd=lib)

        r = subprocess.run([sys.executable, os.path.join(lib, "selftest.py")],
                           capture_output=True, text=True, cwd=lib)
        hit = FAILED_RE.search(r.stdout)
        if hit:
            # The RAW line, unsplit. Also keep the [FAIL] lines, which carry
            # each name intact and are immune to the join.
            failed = [hit.group(1).strip()]
            failed += re.findall(r"^\s*\[FAIL\]\s*(.+?)(?:\s+—.*)?$", r.stdout, re.M)
            return failed, None
        if r.returncode != 0:
            # No verdict line and a non-zero exit: the suite died rather than
            # reporting. Detection, not survival.
            last = [x for x in r.stderr.strip().splitlines() if x.strip()]
            return ["<suite crashed> " + (last[-1] if last else "no output")], None
        return [], None


def main():
    print("mutation battery — reintroducing defects the suite claims to catch\n")
    survived, stale, crashes = [], [], []
    for i, m in enumerate(MUTANTS, 1):
        failures, err = run_one(m)
        if err:
            stale.append((m["name"], err))
            print(f"  [STALE] {i:2}. {m['name']}\n           {err}")
            continue
        crashed = [f for f in failures if f.startswith("<suite crashed>")]
        # `caught` is computed over NAMED failures only. Matching it against the
        # crash text let a traceback containing the expect substring be credited
        # as a caught mutant, with not one check executed.
        caught = [f for f in failures
                  if not f.startswith("<suite crashed>") and m["expect"] in f]
        if crashed and not caught:
            print(f"  [crashed] {i:2}. {m['name']}")
            print(f"            {crashed[0][:110]}")
            print("            detected, but as a crash rather than a named failure")
            crashes.append(m)
        elif caught:
            print(f"  [caught] {i:2}. {m['name']}")
        else:
            survived.append(m)
            print(f"  [SURVIVED] {i:2}. {m['name']}")
            print(f"             expected a check matching {m['expect']!r}")
            print(f"             got: {failures or 'NOTHING — the suite stayed green'}")

    print()
    bad = []
    if stale:
        print(f"{len(stale)} mutant(s) no longer apply — an anchor drifted, so they "
              "test nothing. Update them.")
        bad += stale
    if crashes:
        print(f"{len(crashes)} mutant(s) killed the suite instead of failing a named "
              "check — the defect is detected, but not by the check it is filed under.")
        bad += crashes
    if survived:
        print(f"{len(survived)} of {len(MUTANTS)} mutants SURVIVED — the named check "
              "passes while its defect is live.")
        bad += survived
    if bad:
        # Exits non-zero for stale and crashed too. Only `survived` used to
        # fail, so a battery in which nothing meaningful ran still printed
        # "every check named here has been observed to fail" and exited 0.
        sys.exit(1)
    print(f"all {len(MUTANTS)} mutants caught — every check named here has been "
          "observed to fail.")
    sys.exit(0)


if __name__ == "__main__":
    main()

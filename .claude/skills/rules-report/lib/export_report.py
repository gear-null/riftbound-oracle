#!/usr/bin/env python3
"""Turn a rendered report into ONE file you can send to someone.

WHY THIS EXISTS

A rendered report looks self-contained and is not. It reaches outside itself
twice, and both escapes are invisible on the machine that made it — because
that machine has the things it is quietly reaching for:

  1. the rulebook overlay loads `../data/rules.html`, a sibling of the report's
     folder, which travels nowhere;
  2. card artwork is referenced by URL on Riot's CDN, so a reader who is
     offline, or whose viewer blocks remote images, gets a placeholder.

Send that file over Telegram and the recipient opens a document whose evidence
links do nothing. Worse, it does not LOOK broken: the argument, the citations
and the verification stamps all render, so the reader has no reason to suspect
the one part that is missing is the part that lets them check the claim.

So an export is not a copy. It is a rebuild with everything pulled inward, and
it holds one rule:

  WHOLE, OR NOT AT ALL.

If any piece cannot be inlined, this refuses and says which. It never writes a
partial file, because a partial export is exactly the failure above wearing a
success's clothes — and a reader cannot tell the difference by looking.
"""
import base64
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


class ExportRefused(Exception):
    """Something could not be inlined, so nothing is written."""


def _must_replace(text, find, repl, what):
    """Replace exactly once, or refuse.

    Every rewrite here is load-bearing, and a `str.replace` that matches
    nothing returns the original string and says nothing about it. That is how
    the first working version of this exporter shipped a file whose rulebook
    link still read "open full page" and pointed at `#`: the replacement had
    silently not applied, and the only check in place asked whether anything
    still pointed OUTSIDE the file — which was true either way.

    So the exporter asserts what ARRIVED, not just what left.
    """
    if isinstance(find, str):
        n = text.count(find)
        out = text.replace(find, repl, 1)
    else:
        n = len(find.findall(text))
        out = find.sub(repl, text, count=1)
    if n != 1:
        raise ExportRefused(
            f"expected exactly one {what} to rewrite, found {n} — the "
            "renderer's markup changed and this exporter was not updated"
        )
    return out


# `../data/rules.html#CR-142.4.a` — the overlay's href and the citation links.
RULEBOOK_HREF = re.compile(r'(?:\.\./)*data/rules\.html(#[^"\']*)?')
REMOTE_IMG = re.compile(r'<img\b[^>]*\bsrc="(https?://[^"]+)"[^>]*>', re.I)
ANY_REMOTE = re.compile(r'''\b(?:src|href)\s*=\s*["'](https?://[^"']+)["']''', re.I)


def _cited_anchors(html):
    """Every rulebook anchor the report actually links to."""
    return sorted({m.group(1)[1:] for m in RULEBOOK_HREF.finditer(html) if m.group(1)})


DOC_TITLES = {"CR": "Comprehensive Rules", "TR": "Tournament Rules"}


def _rule_sort_key(anchor):
    """Document, then rule number componentwise — 355.2 before 355.10."""
    doc, _, rid = anchor.partition("-")
    parts = []
    for piece in rid.split("."):
        parts.append((0, int(piece), "") if piece.isdigit() else (1, 0, piece))
    return (doc, parts)


# Runs INSIDE the embedded rulebook. Two jobs, both invisible until you click.
#
# 1. An `about:srcdoc` document inherits its base URL from the parent, so every
#    `href="#CR-206"` in here resolved against the REPORT's URL — clicking a
#    rule's own permalink, or a `see also`, navigated the overlay to a second
#    copy of the whole report nested inside itself. Intercepting the click and
#    scrolling makes those links mean what they look like.
# 2. A `see also` pointing at a rule this export does not carry cannot be
#    followed. Saying so is the honest outcome; a link that silently does
#    nothing teaches a reader that the evidence is unreliable.
_MINIBOOK_JS = """<script>
(function(){
  var here = {};
  Array.prototype.forEach.call(document.querySelectorAll('[id]'), function(n){
    here[n.id] = 1;
  });
  Array.prototype.forEach.call(document.querySelectorAll('a[href^="#"]'), function(a){
    var id = a.getAttribute('href').slice(1);
    if (here[id]) {
      a.addEventListener('click', function(e){
        e.preventDefault();
        var t = document.getElementById(id);
        if (t) t.scrollIntoView();
      });
    } else {
      a.setAttribute('title', 'not included in this export \u2014 ' +
        'the full rulebook has it');
      a.style.opacity = '.55';
      a.style.cursor = 'not-allowed';
      a.addEventListener('click', function(e){ e.preventDefault(); });
    }
  });
})();
</script>"""


def build_minibook(anchors, rules_html):
    """A rulebook holding exactly the rules this report links to.

    The full rulebook is ~1MB of 3,316 rules; a report reaches a few dozen. The
    guarantee is stated in terms of REACHABILITY, not citation: every anchor a
    reader can click arrives, and nothing else does.

    That distinction matters because the two counts differ and the difference
    looks like a leak. A report links each cited rule AND its ancestor spine —
    a rule is meaningless without the clause it sits under — so 6 cited rules
    can link 13 anchors, of which 5 are ancestors and 2 are children shown
    alongside. None of those is a passenger; each is a link that would
    otherwise dead-end.

    An earlier version of this docstring said "plus their spine", which implied
    this function adds ancestors. It does not — it takes the anchors it is
    given. The spine is present because the RENDERER links it. If that ever
    stopped being true the spine would quietly vanish from exports while this
    sentence went on promising it, which is the sort of claim that outlives the
    behaviour it describes.

    Reusing the REAL rulebook's markup rather than re-rendering: this document
    is what the citation links resolve against, and a re-render would be a
    second opinion about what a rule says. Same bytes, fewer rules.
    """
    missing = [a for a in anchors if f'id="{a}"' not in rules_html]
    if missing:
        raise ExportRefused(
            f"the rulebook has no anchor for {', '.join(missing[:5])} — "
            "the corpus and the report disagree; re-render the report"
        )
    head = rules_html.split("<body", 1)[0]
    blocks = []
    for a in anchors:
        # Each rule is ONE `<section>`, and they are siblings rather than
        # nested — depth is carried by a `d1`/`d2`/`d3` class, not by
        # containment — so a rule ends at its own closing tag.
        #
        # This used to look for `<div class="rule` and slice 4000 characters
        # when it did not find it. That sentinel occurs ZERO times in the
        # rulebook, so the fallback was not an edge case, it was the only path
        # ever taken: every block was a blind fixed-length cut. It carried ~100
        # uncited rules into a document whose whole purpose is to hold the ones
        # the report cites, left the HTML unbalanced, and ended the last block
        # mid-attribute. No cited rule was actually truncated, but only because
        # the longest rule in the corpus is 2,000 characters — a margin nobody
        # chose, upstream of us, and one longer rule from Riot would have
        # silently cut a cited rule's tail off.
        m = re.search(rf'<section[^>]*\bid="{re.escape(a)}"[^>]*>', rules_html)
        if not m:
            raise ExportRefused(f"could not locate the block for {a}")
        end = rules_html.find("</section>", m.end())
        if end < 0:
            raise ExportRefused(f"the block for {a} is never closed in the rulebook")
        block = rules_html[m.start():end + len("</section>")]
        # Completeness, not presence. The check that the anchor "arrived" is
        # satisfied by an opening tag alone; this is what makes it a rule.
        if block.count("<section") != 1 or not block.endswith("</section>"):
            raise ExportRefused(f"the block for {a} did not come out whole")
        blocks.append((a, block))

    # ORDER BY RULE NUMBER, not by string. `sorted()` over anchors puts 355.10
    # before 355.2, and 1000 before 200 — so a reader scrolling the embedded
    # rulebook meets the rules out of the order the document numbers them,
    # which is the one ordering a rules document guarantees.
    blocks.sort(key=lambda ab: _rule_sort_key(ab[0]))

    # KEEP THE DOCUMENT BOUNDARY. The real rulebook separates CR from TR with a
    # heading; dropping it left `CR-104` and `TR-104` — different rules with
    # the same number — as indistinguishable neighbours, and a reader has no
    # way to tell which document a block came from.
    body, current_doc = [], None
    for anchor, block in blocks:
        doc = anchor.split("-", 1)[0]
        if doc != current_doc:
            current_doc = doc
            body.append(
                f'<h1 class="rb-doc-sep">{DOC_TITLES.get(doc, doc)}</h1>')
        body.append(block)

    return (
        head
        + "<body class=\"rb minibook\">"
        + "<p class='minibook-note'>The rules this report cites, in document "
        + "order. The full rulebook is in the repository.</p>"
        + "".join(body)
        + _MINIBOOK_JS
        + "</body></html>"
    )


def inline_artwork(html, fetch):
    """Replace every remote <img> with a data: URI, or refuse.

    Refusing on ONE failure is the point. An export that inlines nine cards and
    quietly leaves the tenth pointing at a CDN opens correctly, looks correct,
    and is wrong precisely on the card the reader zoomed in to check. There is
    no visible difference between "this card has no art" and "this export is
    broken", so the reader cannot audit it and must instead trust it — which is
    the thing this project does not ask people to do.
    """
    failures = []

    def swap(m):
        url = m.group(1)
        data = fetch(url)
        if not data:
            failures.append(url)
            return m.group(0)
        return m.group(0).replace(url, data)

    out = REMOTE_IMG.sub(swap, html)
    if failures:
        raise ExportRefused(
            f"{len(failures)} image(s) could not be inlined, so nothing was "
            f"written: {', '.join(failures[:3])}"
        )
    return out


def remaining_escapes(html):
    """Every URL still pointing off this file. Empty means portable.

    The check that decides whether the export is honest, so it is deliberately
    dumb and total: it does not know which URLs are supposed to be here, it
    just reports anything that leaves. Links to GitHub in the footer are
    navigation and are allowed by the caller; anything that has to LOAD for the
    page to be complete is not.
    """
    return sorted({
        u for u in ANY_REMOTE.findall(html)
        if not u.startswith(("https://github.com/", "https://claude.ai/"))
    })


def export(html, rules_html, fetch=None):
    """A rendered report in, one portable document out. Raises, or succeeds."""
    if fetch is None:
        from render_report import embed_image
        fetch = embed_image

    anchors = _cited_anchors(html)
    if not anchors:
        raise ExportRefused(
            "this report links no rules — that is not a report this skill "
            "produces, so the input is probably not a rendered report"
        )
    minibook = build_minibook(anchors, rules_html)
    out = inline_artwork(html, fetch)

    # srcdoc, not src: a file has no sibling to point an iframe at. The overlay
    # keeps working — same open/close, same anchor — because the document it
    # shows now travels inside the report instead of beside it.
    payload = base64.b64encode(minibook.encode("utf-8")).decode("ascii")
    out = _must_replace(
        out,
        "<iframe class=\"rb-frame\" id=\"rb-frame\" title=\"Rulebook\"></iframe>",
        f'<iframe class="rb-frame" id="rb-frame" title="Rulebook"></iframe>'
        f'<script id="rb-doc" type="application/octet-stream">{payload}</script>',
        "the rulebook overlay's iframe",
    )
    out = _must_replace(
        out,
        "    fr.src=href;",
        "    var d=document.getElementById('rb-doc');\n"
        "    var doc=decodeURIComponent(escape(atob(d.textContent)));\n"
        "    var frag=href.indexOf('#')>=0?href.slice(href.indexOf('#')+1):'';\n"
        "    fr.removeAttribute('src'); fr.srcdoc=doc;\n"
        "    fr.onload=function(){ if(!frag) return;\n"
        "      var t=fr.contentDocument&&fr.contentDocument.getElementById(frag);\n"
        "      if(t) t.scrollIntoView(); };",
        "the overlay's iframe-loading line",
    )
    out = RULEBOOK_HREF.sub(lambda m: "#" + (m.group(1)[1:] if m.group(1) else ""), out)

    # "Open full page" promised the whole rulebook. There is no whole rulebook
    # in here, and after the href rewrite above the link points at "#" while
    # still carrying target="_blank" — so it opens an empty tab and reads as a
    # broken document rather than a deliberately smaller one. Say what this
    # actually holds, and stop being a link at all.
    out = _must_replace(
        out,
        re.compile(r'<a class="rb-pop" id="rb-pop"[^>]*>.*?</a>', re.S),
        '<span class="rb-pop" id="rb-pop">cited rules only</span>',
        "the overlay's full-page link",
    )

    escapes = remaining_escapes(out)
    if escapes:
        raise ExportRefused(
            f"{len(escapes)} reference(s) still point outside the file: "
            f"{', '.join(escapes[:3])}"
        )

    # Nothing left. Now: did everything ARRIVE?
    #
    # These two questions are not the same one, and conflating them shipped a
    # broken export once already. "No remote URLs" is satisfied perfectly by a
    # file with no rulebook, no artwork and no argument — deleting content
    # makes that check greener, which is the definition of a check pointing the
    # wrong way. Every assertion below fails when a piece is MISSING.
    for probe, what in (
        ('id="rb-doc"', "the embedded rulebook"),
        ("fr.srcdoc=doc", "the overlay's portable loader"),
    ):
        if probe not in out:
            raise ExportRefused(f"{what} is missing from the finished file")
    # PRESENCE IS NOT COMPLETENESS. `id="CR-829.1"` being in the document is
    # satisfied by an opening tag with the rule's text sliced off after it, and
    # a truncated rule is the worst possible payload here: the reader follows a
    # citation, sees a rule, and reads half of what it says. So assert the
    # closing tag too — the rule arrived whole, not merely started.
    for anchor in anchors:
        opened = f'id="{anchor}"' in minibook
        if not opened:
            raise ExportRefused(f"the embedded rulebook is missing {anchor}")
    if minibook.count("<section") != minibook.count("</section>"):
        raise ExportRefused(
            f"the embedded rulebook has {minibook.count('<section')} sections "
            f"open and {minibook.count('</section>')} closed — a rule was cut"
        )

    # Count only what THIS function inlined. Comparing the finished document's
    # data: URIs against the input's remote images silently credits any data:
    # URI the report already carried (`RIFTBOUND_EMBED_ART=1` produces them),
    # so the left side could cover a real drop on the right. It cannot today,
    # because `inline_artwork` refuses before reaching here — which is exactly
    # why it needed fixing: it reads as a second guard and was not one.
    remote_before = len(REMOTE_IMG.findall(html))
    still_remote = len(REMOTE_IMG.findall(out))
    if still_remote:
        raise ExportRefused(
            f"{remote_before} image(s) went in and {still_remote} still point "
            "at a remote host — artwork was dropped rather than inlined"
        )
    return out

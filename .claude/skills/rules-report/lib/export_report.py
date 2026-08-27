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


def build_minibook(anchors, rules_html):
    """A rulebook holding only the rules this report cites, plus their spine.

    The full rulebook is ~1MB of 3,316 rules; a report cites a few dozen. The
    export carries what the report can actually reach — every anchor it links
    to — and nothing else, so the file stays small enough to send.

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
        # Each rule is one element carrying id="CR-<id>". Take it whole.
        m = re.search(rf'<[^>]*\bid="{re.escape(a)}"[^>]*>', rules_html)
        if not m:
            raise ExportRefused(f"could not locate the block for {a}")
        start = m.start()
        nxt = rules_html.find('<div class="rule', m.end())
        blocks.append(rules_html[start:nxt if nxt > 0 else m.end() + 4000])
    return (
        head
        + "<body class=\"rb minibook\">"
        + "<p class='minibook-note'>The rules this report cites. "
        + "The full rulebook is in the repository.</p>"
        + "".join(blocks)
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
    for anchor in anchors:
        if f'id="{anchor}"' not in minibook:
            raise ExportRefused(f"the embedded rulebook is missing {anchor}")
    inlined = out.count("data:image/")
    if inlined < len(REMOTE_IMG.findall(html)):
        raise ExportRefused(
            f"{len(REMOTE_IMG.findall(html))} image(s) went in, {inlined} came "
            "out — artwork was dropped rather than inlined"
        )
    return out

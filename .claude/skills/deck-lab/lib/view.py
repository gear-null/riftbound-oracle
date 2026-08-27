"""Rendering the table.

Two rules shape everything here.

The board is public (109), so permanents, runes, battlefields, points and both
trashes are shown to everyone. Hands and deck order are not, so a seat view
shows the opponent's hand as a count and never shows either deck's order.

That redaction is the point. One mind playing both seats cannot un-know what it
saw, but it can at least be shown, at the moment it decides, only what that seat
would have in front of it. A view that leaked the opponent's hand would make
every game a perfect-information game, and every conclusion drawn from it
worthless.

What the record can and cannot do is worth stating exactly, because this file
used to claim more than it delivered. `do --seat N` writes a line into the log
saying which seat was acting, so the sequence of declared viewpoints is
auditable afterwards. Nothing verifies that the declaration was honest, and
nothing can: a mind holding both hands cannot be made to forget one. The
redaction removes the excuse, not the possibility.
"""
import cards
import table as tbl

BAR = "─" * 72


def _unit_line(t, perm):
    bits = [f"[{perm.id}]", perm.name]
    if perm.is_unit:
        might = f"{perm.might}M"
        if perm.buffs:
            might += f" (+{perm.buffs})"
        if perm.damage:
            might += f" dmg {perm.damage}"
        bits.append(might)
    if perm.exhausted:
        bits.append("EXHAUSTED")
    if perm.attached_to:
        bits.append(f"attached→{perm.attached_to}")
    if perm.note:
        bits.append(f"note: {perm.note}")
    return "  " + " ".join(bits)


def _cost(name):
    e = cards.energy_cost(name)
    p = cards.power_cost(name)
    out = "-" if e is None else str(e)
    if p:
        doms = "/".join(cards.domains(name)) or "any"
        out += f"+{p}{doms}"
    return out


def hand_lines(t, seat, show_text=True):
    """The hand, with a card's text printed the first time it is seen.

    Reprinting every card's full text on every render was about half of a turn's
    output, and none of it was new — the reader had just been shown it. Text
    appears once per game, when the card first reaches a hand or the board;
    `card <name>` fetches it again on demand.
    """
    p = t.player(seat)
    out = []
    for name in sorted(p.hand):
        payable, why = t.can_pay(seat, name)
        mark = "✓" if payable else "·"
        line = f"  {mark} {_cost(name):>10}  {name}"
        if cards.might(name) is not None:
            line += f"  [{cards.might(name)}M]"
        out.append(line)
        if cards.has_text(name) and (show_text is True and t.first_sight(name) or show_text == "always"):
            for chunk in _wrap(cards.text(name), 62):
                out.append(f"                  {chunk}")
        if not payable:
            out.append(f"                  ({why})")
    return out or ["  (empty)"]


def _wrap(text, width):
    words, line, out = text.split(), "", []
    for w in words:
        if len(line) + len(w) + 1 > width:
            out.append(line)
            line = w
        else:
            line = f"{line} {w}".strip()
    if line:
        out.append(line)
    return out


def render(t, seat=None, full=False, verbose=False):
    """The table as one seat sees it, or the whole thing when `full`.

    `verbose` re-prints card text that has already been shown this game.
    """
    lines = [BAR]
    header = f"turn {t.turn} · {t.phase or 'setup'} · seat {t.turn_player} to act"
    if t.winner is not None:
        header += f"  ·  GAME OVER — seat {t.winner} wins"
    lines.append(header)
    lines.append(BAR)

    for p in t.players:
        me = " (you)" if p.seat == seat else ""
        pool = f"{p.energy}E"
        if p.power:
            pool += " " + " ".join(f"{n}{d}" for d, n in sorted(p.power.items()))
        runes = [r for r in t.runes if r.controller == p.seat]
        ready = sum(1 for r in runes if not r.exhausted)
        lines.append(
            f"seat {p.seat}{me}  {p.points} pts  ·  hand {len(p.hand)}  ·  "
            f"deck {len(p.main_deck)}  ·  runes {ready}/{len(runes)} ready  ·  pool {pool}"
        )
        lines.append(f"          {p.legend}  ·  champion zone: {', '.join(p.champion_zone) or '—'}")
        if runes:
            counts = {}
            for r in runes:
                key = (r.domain or "—", r.exhausted)
                counts[key] = counts.get(key, 0) + 1
            shown = ", ".join(
                f"{n}× {d}{' exhausted' if ex else ''}" for (d, ex), n in sorted(counts.items())
            )
            lines.append(f"          runes: {shown}")

    lines.append(BAR)
    for bf in t.battlefields:
        status = []
        status.append(f"controlled by seat {bf.controller}" if bf.controller is not None else "uncontrolled")
        if bf.contested:
            status.append("CONTESTED")
        if bf.scored_by:
            status.append(f"scored this turn by {', '.join(f'seat {s}' for s in sorted(bf.scored_by))}")
        lines.append(f"{bf.name}  (bf:{bf.index})  —  {'; '.join(status)}")
        # Printed once, like a card's. It is in the setup log too, and it does
        # not change; `--verbose` brings it back.
        if cards.find(bf.name) and cards.has_text(bf.name) and (verbose or t.first_sight(bf.name)):
            for chunk in _wrap(cards.text(bf.name), 66):
                lines.append(f"    {chunk}")
        here = t.at(bf.location)
        if here:
            for perm in here:
                lines.append(f"  seat {perm.controller}" + _unit_line(t, perm)[1:])
        else:
            lines.append("  (empty)")

    for p in t.players:
        base = t.at(f"{tbl.BASE}:{p.seat}")
        lines.append(f"seat {p.seat} base —" + (f" {len(base)} permanent(s)" if base else " empty"))
        for perm in base:
            lines.append(_unit_line(t, perm))

    lines.append(BAR)
    if full:
        for p in t.players:
            lines.append(f"seat {p.seat} hand ({len(p.hand)}):")
            lines.extend(hand_lines(t, p.seat, show_text=verbose or True))
    elif seat is not None:
        lines.append(f"your hand ({len(t.player(seat).hand)}):")
        lines.extend(hand_lines(t, seat, show_text="always" if verbose else True))
        other = t.opponent(seat)
        lines.append(f"seat {other} holds {len(t.player(other).hand)} card(s) — contents hidden")
    else:
        lines.append("(no seat given — pass --seat to see a hand)")

    for p in t.players:
        if p.trash:
            lines.append(f"seat {p.seat} trash ({len(p.trash)}): {', '.join(p.trash[-8:])}")
    lines.append(BAR)
    return "\n".join(lines)


def log_lines(t, last=None, seat=None, full=False):
    """The log as one seat may see it.

    Entries marked private to another seat keep their headline and lose their
    detail, so the shape of the game stays readable — "seat 1 draws 1" — without
    naming a card that seat is not entitled to know. `full` is for reviewing a
    finished game, never for playing one.
    """
    entries = t.log[-last:] if last else t.log
    out = []
    for e in entries:
        text = e["text"]
        owner = e.get("private_to")
        if e.get("detail"):
            if full or owner == seat:
                text = f"{text}: {e['detail']}"
            else:
                text = f"{text} (hidden)"
        out.append(f"  t{e['turn']:>2} {(e['phase'] or 'setup')[:6]:6}  {text}")
    return out

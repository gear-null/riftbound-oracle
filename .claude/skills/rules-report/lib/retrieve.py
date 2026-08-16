"""Lexical retrieval + structural expansion over the rule tree.

Load-bearing: `rules_cli.py grep` and `rules_cli.py build` both depend on this.

Two bets being tested here:

1. LEXICAL BEATS SEMANTIC for this corpus. Riftbound names each action with an
   exact term and gives it its own section — "431. Burn Out" vs "440. Burn" vs
   "416. Recycle" vs "427. Banish". Embedding similarity blurs precisely the
   distinctions that decide rulings. BM25 over rule text should separate them
   cleanly. Measured below.

2. STRUCTURAL EXPANSION IS THE REAL WORK. A matched rule alone is often
   unusable — 471.1.b.1 needs 471.1.b for its condition. So a hit expands to an
   ancestor-closed packet plus children and `See rule` targets.

Usage:
    python3 retrieve.py build
    python3 retrieve.py query "does a countered flow spell still get banished"
    python3 retrieve.py selftest
"""
import json, os, re, sqlite3, sys, textwrap

from corpus import rules_json

# Anchored to this file, not the cwd. `rules_cli.py` always passes an explicit
# absolute path, so the shipped answering path was never affected — but the
# standalone usage in the docstring above is real, and with a bare relative
# name it built or opened a `rules.db` wherever it happened to be invoked
# from. That silently scattered empty databases (one turned up in `output/`)
# and meant a standalone `query` could read an index that was not the one
# `build` had just written.
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rules.db")


def sort_key(rule_id):
    out = []
    for seg in rule_id.split("."):
        out.append((0, int(seg), "") if seg.isdigit() else (1, 0, seg))
    return out


def build():
    rules = json.load(open(rules_json(), encoding="utf-8"))
    con = sqlite3.connect(DB)
    con.executescript("""
        DROP TABLE IF EXISTS rule;
        DROP TABLE IF EXISTS rule_fts;
        CREATE TABLE rule(
            uid TEXT PRIMARY KEY, doc TEXT, rid TEXT, version TEXT, depth INT,
            parent TEXT, section TEXT, section_title TEXT, text TEXT,
            examples TEXT, see_also TEXT
        );
        CREATE INDEX rule_parent ON rule(parent, doc);
        CREATE INDEX rule_doc_rid ON rule(doc, rid);
    """)
    con.executemany(
        "INSERT INTO rule VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [(f'{r["doc"]}:{r["id"]}', r["doc"], r["id"], r["version"], r["depth"],
          r["parent"], r["section"], r["section_title"], r["text"],
          json.dumps(r["examples"]), json.dumps(r["see_also"])) for r in rules],
    )
    # rid weighted heavily so "rule 471.1.b" is a direct hit; section_title
    # matters because Riot titles sections with the exact term.
    con.executescript("""
        CREATE VIRTUAL TABLE rule_fts USING fts5(
            uid UNINDEXED, rid, text, examples, section_title,
            tokenize='unicode61', prefix='2 3'
        );
        INSERT INTO rule_fts SELECT uid, rid, text, examples, section_title FROM rule;
    """)
    con.commit()
    n = con.execute("SELECT count(*) FROM rule").fetchone()[0]
    print(f"built {DB}: {n} rules indexed")
    con.close()


class Retriever:
    def __init__(self, db=DB):
        self.con = sqlite3.connect(db)
        self.con.row_factory = sqlite3.Row

    def get(self, uid):
        return self.con.execute("SELECT * FROM rule WHERE uid=?", (uid,)).fetchone()

    def ancestors(self, uid):
        """Ancestor spine, root first. Without this a deep rule is unreadable."""
        row = self.get(uid)
        chain = []
        while row:
            chain.append(row)
            p = row["parent"]
            row = self.get(f'{row["doc"]}:{p}') if p else None
        return list(reversed(chain))

    def children(self, uid):
        row = self.get(uid)
        if not row:
            return []
        return self.con.execute(
            "SELECT * FROM rule WHERE doc=? AND parent=? ORDER BY rid", (row["doc"], row["rid"])
        ).fetchall()

    def search(self, fts_query, limit=12):
        try:
            return self.con.execute(
                """SELECT r.*, bm25(rule_fts, 0, 8.0, 5.0, 2.0, 1.5) AS score
                   FROM rule_fts JOIN rule r ON r.uid = rule_fts.uid
                   WHERE rule_fts MATCH ? ORDER BY score LIMIT ?""",
                (fts_query, limit),
            ).fetchall()
        except sqlite3.OperationalError as e:
            # A missing index is not a bad query. sqlite3.connect happily
            # creates an empty file, so without this the agent sees zero hits
            # and a message blaming its own search terms.
            if "no such table" in str(e):
                raise SystemExit(
                    "Rule index missing or empty. Build it first:\n"
                    "    python3 rules_cli.py build"
                ) from e
            print(f"  (bad FTS query: {e})", file=sys.stderr)
            return []

    def packet(self, uid):
        """Ancestor-closed packet: the unit that is safe to cite from."""
        anc = self.ancestors(uid)
        kids = self.children(uid)
        row = self.get(uid)
        if not row:
            return None
        seen, rules = set(), []
        for r in anc + kids:
            if r["uid"] not in seen:
                seen.add(r["uid"])
                rules.append({"uid": r["uid"], "rid": r["rid"], "depth": r["depth"],
                              "text": r["text"], "role": "target" if r["uid"] == uid else
                              ("ancestor" if r in anc else "child")})
        return {
            "uid": uid,
            "section": f'{row["section"]}. {row["section_title"]}',
            "doc": row["doc"],
            "version": row["version"],
            "see_also": json.loads(row["see_also"]),
            "rules": rules,
        }

    def retrieve(self, fts_query, limit=8):
        hits = self.search(fts_query, limit)
        return [self.packet(h["uid"]) for h in hits]


# ------------------------------------------------------------------ self-test

CONFUSABLES = [
    ("burn out", '"burn out"', "431"),
    ("burn (not burn out)", 'burn NOT "burn out"', "440"),
    ("recycle", "recycle", "416"),
    ("banish", "banish*", "427"),
]

QUESTIONS = [
    ('countered Flow spell still banished', '"flow" AND (banish OR "leave the chain")', "829.1.b.1"),
    ('sideboard size limit', 'sideboard AND (size OR "10 or fewer")', "601.1.c.1"),
    ('victory score default', '"victory score"', "194.3"),
    ('can an Empowered unit be Empowered again', 'empowered AND binary', "441.1.a"),
]


def selftest():
    r = Retriever()
    print("=== BET 1: lexical separates the confusable actions ===")
    for label, q, expect_section in CONFUSABLES:
        hits = r.search(q, 8)
        secs = [h["section"] for h in hits]
        on = sum(1 for s in secs if s == expect_section)
        print(f"  {label:22} -> {on}/{len(secs)} hits in section {expect_section}"
              f"   top: {', '.join(h['rid'] for h in hits[:4])}")

    print("\n=== BET 2: does the target rule surface for real questions? ===")
    for label, q, want in QUESTIONS:
        hits = r.search(q, 12)
        rids = [h["rid"] for h in hits]
        rank = rids.index(want) + 1 if want in rids else None
        status = f"rank {rank}" if rank else "*** MISS ***"
        print(f"  {label:42} want {want:12} {status}")
        if not rank:
            print(f"      got: {', '.join(rids[:6])}")

    print("\n=== packet shape (what the agent actually sees) ===")
    p = r.packet("CR:829.1.b.1")
    print(f"  {p['uid']}  [{p['section']}]  {p['doc']} @ {p['version']}")
    for rr in p["rules"]:
        print(f"    {rr['role']:8} {rr['rid']:14} {textwrap.shorten(rr['text'], 92)}")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "selftest"
    if cmd == "build":
        build()
    elif cmd == "selftest":
        selftest()
    elif cmd == "query":
        r = Retriever()
        packets = r.retrieve(sys.argv[2], 6)
        print(json.dumps([p for p in packets if p], indent=1)[:4000])
    else:
        print(__doc__)


if __name__ == "__main__":
    main()

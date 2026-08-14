import { describe, it, expect } from "vitest";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { checkUpstream, diffSets, loadState, saveState, toSnapshots } from "../watch.js";

const S = (id: string, n: number) => ({ set_id: id, card_count: n, published_on: null });

describe("toSnapshots", () => {
  it("accepts both the paginated and bare shapes", () => {
    const bare = toSnapshots([{ set_id: "OGN", card_count: 352 }]);
    const paged = toSnapshots({ items: [{ set_id: "OGN", card_count: 352 }] });
    expect(bare).toEqual(paged);
  });

  it("rejects a set id that could not be a set id", () => {
    // set_id reaches a PR title and a commit message. It is constrained at the
    // source rather than trusted downstream.
    const out = toSnapshots([
      { set_id: "OGN", card_count: 1 },
      { set_id: "$(rm -rf /)", card_count: 1 },
      { set_id: "a".repeat(64), card_count: 1 },
      { set_id: 42, card_count: 1 },
    ]);
    expect(out.map((s) => s.set_id)).toEqual(["OGN"]);
  });

  it("does not turn a missing count into NaN", () => {
    expect(toSnapshots([{ set_id: "X1", card_count: "nope" }])[0].card_count).toBe(0);
  });
});

describe("diffSets", () => {
  const before = [S("OGN", 352), S("VEN", 358)];

  it("stays quiet when nothing moved", () => {
    const d = diffSets(before, [...before]);
    expect(d.changed).toBe(false);
    expect(d.summary).toContain("no card-side changes");
  });

  it("notices a new set", () => {
    const d = diffSets(before, [...before, S("NEW", 200)]);
    expect(d.changed).toBe(true);
    expect(d.newSets).toEqual(["NEW"]);
  });

  it("notices a card count moving", () => {
    const d = diffSets(before, [S("OGN", 354), S("VEN", 358)]);
    expect(d.countChanges).toEqual([{ set_id: "OGN", from: 352, to: 354 }]);
    expect(d.summary).toContain("352 → 354");
  });

  it("notices a set disappearing", () => {
    // Worth surfacing: it means either an upstream error or a withdrawal, and
    // a regeneration would drop those cards from the corpus.
    expect(diffSets(before, [S("OGN", 352)]).removedSets).toEqual(["VEN"]);
  });

  it("treats an empty baseline as a change, so the first run records state", () => {
    expect(diffSets([], before).changed).toBe(true);
  });
});

describe("checkUpstream", () => {
  it("refuses to act on an empty set list", async () => {
    // An empty response is an API hiccup far more often than every set being
    // withdrawn, and acting on it would blank the corpus.
    await expect(
      checkUpstream({ fetchSets: async () => ({ items: [] }) })
    ).rejects.toThrow(/refusing/);
  });

  it("compares live data against the committed state", async () => {
    const dir = mkdtempSync(join(tmpdir(), "watch-"));
    try {
      const path = join(dir, "upstream.json");
      saveState([S("OGN", 352)], "2026-08-14", path);
      const { drift } = await checkUpstream({
        statePath: path,
        fetchSets: async () => ({ items: [{ set_id: "OGN", card_count: 352 }] }),
      });
      expect(drift.changed).toBe(false);
    } finally { rmSync(dir, { recursive: true }); }
  });
});

describe("state file", () => {
  it("round-trips, sorted so a rewrite is a reviewable diff", () => {
    const dir = mkdtempSync(join(tmpdir(), "watch-"));
    try {
      const path = join(dir, "upstream.json");
      saveState([S("VEN", 358), S("OGN", 352)], "2026-08-14", path);
      expect(loadState(path).sets.map((s) => s.set_id)).toEqual(["OGN", "VEN"]);
      // stable across rewrites
      const a = readFileSync(path, "utf-8");
      saveState(loadState(path).sets, "2026-08-14", path);
      expect(readFileSync(path, "utf-8")).toBe(a);
    } finally { rmSync(dir, { recursive: true }); }
  });

  it("treats a missing or corrupt state file as an empty baseline", () => {
    const dir = mkdtempSync(join(tmpdir(), "watch-"));
    try {
      expect(loadState(join(dir, "nope.json")).sets).toEqual([]);
      const bad = join(dir, "bad.json");
      writeFileSync(bad, "{not json");
      expect(loadState(bad).sets).toEqual([]);
    } finally { rmSync(dir, { recursive: true }); }
  });
});

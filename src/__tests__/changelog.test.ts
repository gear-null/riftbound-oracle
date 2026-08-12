import { describe, it, expect } from "vitest";
import { parseCommit, corpusDiff, renderEntry } from "../changelog.js";

describe("parseCommit", () => {
  it("splits a conventional subject", () => {
    const c = parseCommit("abc123 feat(cards): add stats")!;
    expect(c).toMatchObject({ type: "feat", scope: "cards", subject: "add stats", breaking: false, hash: "abc123" });
  });

  it("marks a breaking change", () => {
    expect(parseCommit("abc feat!: drop the old schema")!.breaking).toBe(true);
  });

  it("keeps a non-conventional subject rather than dropping it", () => {
    // Early history predates the convention; losing those silently would make
    // the changelog quietly incomplete.
    const c = parseCommit("abc Rebuild rules source")!;
    expect(c.type).toBe("other");
    expect(c.subject).toBe("Rebuild rules source");
  });
});

describe("corpusDiff", () => {
  const now = { rules_version: "2026-08-20", rules: 3400, cards: 1000, errata_applied: 30, cards_awaiting_transcription: 25 };

  it("reports absolutes when there is no previous release", () => {
    const lines = corpusDiff(now);
    expect(lines[0]).toContain("2026-08-20");
    expect(lines[0]).toContain("3400 rules");
  });

  it("reports a rules update with the delta", () => {
    const before = { ...now, rules_version: "2026-07-16", rules: 3316 };
    const lines = corpusDiff(now, before).join("\n");
    expect(lines).toContain("2026-07-16 → 2026-08-20");
    expect(lines).toContain("(+84)");
  });

  it("says nothing about rules when the version is unchanged", () => {
    const lines = corpusDiff(now, now).join("\n");
    expect(lines).not.toContain("Rules updated");
  });

  it("always surfaces cards still awaiting transcription", () => {
    // A known gap must not vanish from release notes just because it did not change.
    expect(corpusDiff(now, now).join("\n")).toContain("awaiting transcription");
  });
});

describe("renderEntry", () => {
  const commits = [
    parseCommit("a1 feat: new thing")!,
    parseCommit("b2 fix: old thing")!,
    parseCommit("c3 feat!: breaking thing")!,
  ];

  it("puts the corpus first and breaking changes above features", () => {
    const md = renderEntry("1.2.3", "2026-08-20", commits, ["Rules updated."]);
    expect(md.indexOf("### Corpus")).toBeLessThan(md.indexOf("### Breaking"));
    expect(md.indexOf("### Breaking")).toBeLessThan(md.indexOf("### Added"));
    expect(md).toContain("## [1.2.3] — 2026-08-20");
  });

  it("lists a breaking change once, not also under its type", () => {
    const md = renderEntry("1.2.3", "d", commits, []);
    expect(md.match(/breaking thing/g)).toHaveLength(1);
  });

  it("omits empty sections", () => {
    const md = renderEntry("1.0.0", "d", [parseCommit("a1 docs: tweak")!], []);
    expect(md).toContain("### Documentation");
    expect(md).not.toContain("### Added");
    expect(md).not.toContain("### Corpus");
  });
});

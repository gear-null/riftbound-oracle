import { describe, it, expect } from "vitest";
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync, existsSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { describeSkill, packageSkill } from "../package.js";

function fakeSkill(dir: string, over: Record<string, unknown> = {}) {
  mkdirSync(join(dir, "data"), { recursive: true });
  mkdirSync(join(dir, "lib"), { recursive: true });
  mkdirSync(join(dir, "reports"), { recursive: true });
  mkdirSync(join(dir, "lib", "__pycache__"), { recursive: true });
  writeFileSync(join(dir, "SKILL.md"), "---\nname: x\n---\n");
  writeFileSync(join(dir, "lib", "rules_cli.py"), "print('hi')\n");
  writeFileSync(join(dir, "lib", "rules.db"), "binary");
  writeFileSync(join(dir, "reports", "old.html"), "<html></html>");
  writeFileSync(join(dir, "lib", "__pycache__", "x.pyc"), "cached");
  writeFileSync(join(dir, "data", "rules.json"),
    JSON.stringify([{ id: "1", version: "2026-07-16" }, { id: "2", version: "2026-07-16" }]));
  writeFileSync(join(dir, "data", "cards.json"), JSON.stringify({
    "a": { name: "Alpha" },
    "alpha": { name: "Alpha" },                         // alias of the same card
    "b": { name: "Beta", incomplete: "granted ability missing" },
    ...over,
  }));
}

describe("describeSkill", () => {
  it("reports the corpus it actually carries, counting cards not aliases", () => {
    const dir = mkdtempSync(join(tmpdir(), "sk-"));
    try {
      fakeSkill(dir);
      const m = describeSkill(dir, "9.9.9");
      expect(m.rules).toBe(2);
      expect(m.cards).toBe(2);                          // Alpha counted once
      expect(m.cards_awaiting_transcription).toBe(1);
      expect(m.rules_version).toBe("2026-07-16");
      expect(m.version).toBe("9.9.9");
    } finally { rmSync(dir, { recursive: true }); }
  });
});

describe("packageSkill", () => {
  it("records nothing self-referential, so a release reproduces from its tag", () => {
    // A commit hash here cannot be stable: the manifest is committed, so
    // building at A writes A, committing yields B, rebuilding writes B. The
    // archive could then never be rebuilt from its own tag.
    const dir = mkdtempSync(join(tmpdir(), "sk-"));
    try {
      fakeSkill(dir);
      const m = describeSkill(dir, "1.2.3") as unknown as Record<string, unknown>;
      expect(m).not.toHaveProperty("commit");
      expect(JSON.stringify(m)).not.toMatch(/\b[0-9a-f]{7,40}\b/);
      // and it is a pure function of the corpus + version
      expect(describeSkill(dir, "1.2.3")).toEqual(m);
    } finally { rmSync(dir, { recursive: true }); }
  });

  it("is byte-reproducible across builds", () => {
    // A release checksum is meaningless if archiving identical bytes twice
    // yields two different files.
    const src = mkdtempSync(join(tmpdir(), "sk-"));
    const out = mkdtempSync(join(tmpdir(), "dist-"));
    try {
      fakeSkill(src);
      const a = packageSkill({ skillDir: src, distDir: out, version: "1.2.3" });
      const b = packageSkill({ skillDir: src, distDir: out, version: "1.2.3" });
      expect(b.sha256).toBe(a.sha256);
      expect(readFileSync(`${a.archive}.sha256`, "utf-8")).toContain(a.sha256);
    } finally { rmSync(src, { recursive: true }); rmSync(out, { recursive: true }); }
  });

  it("leaves build artifacts and stale reports out of the archive", () => {
    const src = mkdtempSync(join(tmpdir(), "sk-"));
    const out = mkdtempSync(join(tmpdir(), "dist-"));
    try {
      fakeSkill(src);
      const { archive } = packageSkill({ skillDir: src, distDir: out, version: "1.2.3" });
      const listing = readFileSync(archive).toString("latin1");
      expect(listing).toContain("rules-report/SKILL.md");
      expect(listing).toContain("SKILL-VERSION.json");
      expect(listing).not.toContain("rules.db");
      expect(listing).not.toContain("__pycache__");
      expect(listing).not.toContain("old.html");
    } finally { rmSync(src, { recursive: true }); rmSync(out, { recursive: true }); }
  });

  it("refuses to package a skill with no corpus", () => {
    // Shipping an empty skill is worse than failing the build.
    const src = mkdtempSync(join(tmpdir(), "sk-"));
    const out = mkdtempSync(join(tmpdir(), "dist-"));
    try {
      mkdirSync(join(src, "data"), { recursive: true });
      expect(() => packageSkill({ skillDir: src, distDir: out })).toThrow(/skill-data/);
      expect(existsSync(join(out, "riftbound-rules-report-v1.0.0.zip"))).toBe(false);
    } finally { rmSync(src, { recursive: true }); rmSync(out, { recursive: true }); }
  });
});

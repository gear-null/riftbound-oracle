import { describe, it, expect } from "vitest";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { SKILL_SRC } from "../package.js";

/**
 * `npx skills add` installs straight from git, so the committed layout IS the
 * published package. Nothing else in the suite would catch a break here.
 */
describe("registry-installable layout", () => {
  const md = readFileSync(join(SKILL_SRC, "SKILL.md"), "utf-8");

  it("has the frontmatter the skills CLI requires", () => {
    const fm = md.match(/^---\n([\s\S]*?)\n---/);
    expect(fm).not.toBeNull();
    expect(fm![1]).toMatch(/^name:\s*\S+/m);
    expect(fm![1]).toMatch(/^description:\s*\S+/m);
  });

  it("declares a name matching its directory, lowercase and hyphenated", () => {
    // The CLI requires name === parent directory.
    const name = md.match(/^name:\s*(\S+)/m)![1];
    expect(name).toBe(SKILL_SRC.split("/").pop());
    expect(name).toMatch(/^[a-z0-9-]+$/);
  });

  it("carries its corpus in git, not only in the archive", () => {
    // A registry install never sees the zip; if the data were gitignored the
    // skill would install and then fail at first use.
    for (const f of ["data/rules.json", "data/cards.json", "data/rules.html"]) {
      expect(existsSync(join(SKILL_SRC, f))).toBe(true);
    }
  });

  it("carries provenance in git so a registry install can be dated", () => {
    const v = JSON.parse(readFileSync(join(SKILL_SRC, "SKILL-VERSION.json"), "utf-8"));
    expect(v.rules_version).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(v.cards).toBeGreaterThan(500);
  });
});

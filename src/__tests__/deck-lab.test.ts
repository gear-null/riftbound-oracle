import { describe, it, expect } from "vitest";
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join, resolve } from "node:path";
import { GAUNTLET_DIR } from "../decks.js";

const SKILL = resolve(".claude/skills/deck-lab");
const LIB = join(SKILL, "lib");

/**
 * The engine's own regression harness lives in Python, next to the code it
 * covers, so a copied skill can verify itself with no Node and no install.
 * This runs it, so `npm test` fails when the table breaks.
 */
describe("deck-lab engine", () => {
  it("passes its own selftest", () => {
    const out = execFileSync("python3", ["deck_cli.py", "selftest"], {
      cwd: LIB,
      encoding: "utf-8",
    });
    expect(out).toMatch(/\n(\d+)\/\1 passed/);
    expect(out).not.toContain("[FAIL]");
  });
});

describe("deck-lab skill layout", () => {
  const md = readFileSync(join(SKILL, "SKILL.md"), "utf-8");

  it("has the frontmatter the skills CLI requires", () => {
    const fm = md.match(/^---\n([\s\S]*?)\n---/);
    expect(fm).not.toBeNull();
    expect(fm![1]).toMatch(/^name:\s*deck-lab/m);
    expect(fm![1]).toMatch(/^description:\s*\S+/m);
  });

  it("vendors its own card data rather than reaching into the other skill", () => {
    // ADR 0004: copying the folder is the whole install. A skill that read
    // rules-report's copy would install fine and then fail at first use.
    expect(existsSync(join(SKILL, "data/cards.json"))).toBe(true);
  });

  it("nothing in the answering path imports from outside the skill folder", () => {
    // The invariant docs/maintaining.md names. A relative import climbing out
    // of lib/ is the exact way it was broken before.
    for (const file of readdirSync(LIB).filter((f) => f.endsWith(".py"))) {
      const body = readFileSync(join(LIB, file), "utf-8");
      expect(body, `${file} climbs out of the skill folder`).not.toMatch(
        /\.\.[/\\]\.\.[/\\]/
      );
    }
  });

  it("ships a gauntlet so a deck has real opponents on first use", () => {
    const decks = readdirSync(GAUNTLET_DIR).filter((f) => f.endsWith(".json"));
    expect(decks.length).toBeGreaterThan(10);
  });
});

describe("the pulled gauntlet", () => {
  const decks = readdirSync(GAUNTLET_DIR)
    .filter((f) => f.endsWith(".json"))
    .map((f) => JSON.parse(readFileSync(join(GAUNTLET_DIR, f), "utf-8")));

  it("holds decks of a legal size, not fragments of pages that half-rendered", () => {
    // A short main deck is the signature of a scrape that captured a partially
    // rendered page, and it is invisible until a game draws from it.
    for (const d of decks) {
      const main = d.main.reduce((n: number, c: { qty: number }) => n + c.qty, 0);
      expect(main, `${d.name} main deck`).toBeGreaterThanOrEqual(40);
      expect(d.runes.reduce((n: number, c: { qty: number }) => n + c.qty, 0)).toBe(12);
      expect(d.battlefields.length).toBe(3);
    }
  });

  it("records where every deck came from", () => {
    for (const d of decks) {
      expect(d.source?.url, `${d.name}`).toMatch(/^https:\/\//);
      expect(d.source?.fetched).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    }
  });
});

import { describe, it, expect } from "vitest";
import { findGaps, stubYaml, collectGaps } from "../gear-gaps.js";
import { mkdtempSync, readFileSync, readdirSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";

const card = (name: string, over = {}) =>
  ({ name, text: "", stats: { energy: null, might: null, power: null, type: "Gear", rarity: null, domain: [] }, ...over }) as never;

describe("findGaps", () => {
  const index = {
    a: card("B.F. Sword", { incomplete: "granted ability missing", image: "https://cdn/a.png" }),
    "b.f. sword": card("B.F. Sword", { incomplete: "granted ability missing", image: "https://cdn/a.png" }),
    c: card("Astral Heron"),
    d: card("Boneshiver", { incomplete: "granted ability missing" }),
  };

  it("lists each incomplete card once, by name", () => {
    // The index is keyed by every alias, so a card appears several times.
    expect(findGaps(index as never).map((g) => g.name)).toEqual(["B.F. Sword", "Boneshiver"]);
  });

  it("excludes cards already transcribed", () => {
    const done = new Map([["b.f. sword", {}]]);
    expect(findGaps(index as never, done).map((g) => g.name)).toEqual(["Boneshiver"]);
  });

  it("returns nothing when the pool is complete", () => {
    expect(findGaps({ c: card("Astral Heron") } as never)).toEqual([]);
  });
});

describe("stubYaml", () => {
  it("pre-fills everything mechanical and leaves only the transcription", () => {
    const y = stubYaml([{ name: "B.F. Sword", image: "https://cdn/a.png", reason: "why" }]);
    expect(y).toContain('- name: "B.F. Sword"');
    expect(y).toContain("source: https://cdn/a.png");
    expect(y).toContain("granted_might:");
    // parses as YAML with the value left empty for a human
    expect(y).toMatch(/granted_might:\s*#/);
  });

  it("says so plainly when there is nothing to do", () => {
    expect(stubYaml([])).toContain("Nothing to transcribe");
  });

  it("survives a card with no artwork URL", () => {
    expect(stubYaml([{ name: "X", reason: "why" }])).toContain("no artwork URL");
  });
});

describe("collectGaps", () => {
  it("keeps going when one image is unreachable", async () => {
    // One dead CDN entry must not abandon the other transcriptions.
    const dir = mkdtempSync(join(tmpdir(), "gaps-"));
    try {
      const r = await collectGaps(
        [
          { name: "Good", image: "https://cdn/good.png", reason: "r" },
          { name: "Bad", image: "https://cdn/bad.png", reason: "r" },
        ],
        {
          outputDir: dir,
          fetchImage: async (u) => {
            if (u.includes("bad")) throw new Error("404");
            return new TextEncoder().encode("png").buffer;
          },
        }
      );
      expect(r.saved).toBe(1);
      expect(r.failed).toHaveLength(1);
      expect(r.failed[0]).toContain("Bad");
      expect(readdirSync(dir)).toContain("good.png");
      expect(readFileSync(join(dir, "overlay-stub.yaml"), "utf-8")).toContain("Good");
    } finally {
      rmSync(dir, { recursive: true });
    }
  });
});

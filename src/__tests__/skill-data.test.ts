import { describe, it, expect } from "vitest";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { buildCardIndex, buildSkillData, cardText, keysFor } from "../skill-data.js";
import type { RiftcodexCard } from "../riftcodex.js";

function card(over: Partial<RiftcodexCard> & { name: string }): RiftcodexCard {
  return {
    id: "x",
    riftbound_id: "x",
    tcgplayer_id: "x",
    collector_number: 1,
    attributes: { energy: null, might: null, power: null },
    classification: { type: "Unit", supertype: null, rarity: "Common", domain: [] },
    text: { rich: "", plain: "", flavour: null },
    set: { set_id: "VEN", label: "Vendetta" },
    media: { image_url: "", artist: "", accessibility_text: "" },
    tags: [],
    orientation: "portrait",
    metadata: {
      clean_name: over.name,
      updated_on: "",
      alternate_art: false,
      overnumbered: false,
      signature: false,
    },
    ...over,
  } as RiftcodexCard;
}

describe("keysFor", () => {
  it("indexes both the full name and the part before the subtitle", () => {
    expect(keysFor("Viktor - Machine Herald")).toEqual([
      "viktor - machine herald",
      "viktor",
    ]);
  });

  it("strips a parenthetical suffix", () => {
    expect(keysFor("Windsinger (Alternate Art)")).toEqual(["windsinger"]);
  });

  it("drops keys of three characters or fewer", () => {
    // A short key matches inside a large share of questions, so a card named
    // "Ash" must not claim every question containing that substring.
    expect(keysFor("Ash")).toEqual([]);
    expect(keysFor("Ash - Emberborn")).toEqual(["ash - emberborn"]);
  });

  it("does not emit a duplicate when there is no subtitle", () => {
    expect(keysFor("Astral Heron")).toEqual(["astral heron"]);
  });
});

describe("cardText", () => {
  it("keeps bracketed keywords and shortcodes verbatim", () => {
    // card_bridge.py maps [Equip] onto a glossary rule section and expands
    // :rb_energy_1:. Rewriting either would sever the card->rules bridge.
    const text = cardText(
      card({ name: "Blighted Battleaxe", text: { rich: "", plain: "[Equip] :rb_energy_1:", flavour: null } })
    );
    expect(text).toContain("[Equip]");
    expect(text).toContain(":rb_energy_1:");
  });

  it("emits the stats line the bridge expects", () => {
    const text = cardText(
      card({
        name: "Astral Heron",
        attributes: { energy: 7, might: 7, power: null },
        classification: { type: "Unit", supertype: null, rarity: "Epic", domain: ["Calm"] },
      })
    );
    expect(text).toContain("**Energy:** 7");
    expect(text).toContain("**Might:** 7");
    expect(text).toContain("**Type:** Unit");
    expect(text).toContain("**Domain:** Calm");
    expect(text).not.toContain("**Power:**");
  });

  it("decodes HTML entities the API serves escaped", () => {
    // Riftcodex escapes text.plain, so the keyword marker [>] arrives as
    // "[&gt;]". Going API -> cards.json skipped normalize(), which used to
    // decode it — the literal entity then printed in reports and hid the ">"
    // row from the symbol legend.
    const text = cardText(
      card({
        name: "Legion Unit",
        text: { rich: "", plain: "[Legion][&gt;] Deal 1 damage &amp; draw &quot;a card&quot;", flavour: null },
      })
    );
    expect(text).toContain("[Legion][>]");
    expect(text).toContain('& draw "a card"');
    expect(text).not.toContain("&gt;");
    expect(text).not.toContain("&amp;");
  });

  it("survives a card with no printed text", () => {
    expect(cardText(card({ name: "Vanilla" }))).toContain("**Type:** Unit");
  });
});

describe("buildCardIndex", () => {
  it("keeps the first printing's text when a card is reprinted", () => {
    const index = buildCardIndex([
      card({ name: "Reprint", text: { rich: "", plain: "original", flavour: null } }),
      card({ name: "Reprint", text: { rich: "", plain: "changed", flavour: null } }),
    ]);
    expect(index["reprint"].text).toContain("original");
  });

  it("takes artwork from a later printing when the first had none", () => {
    // Ordering decided whether a card had art at all; that is a coin flip, not
    // a decision, so a reprint's image fills the gap.
    const index = buildCardIndex([
      card({ name: "Latecomer", media: { image_url: "", artist: "", accessibility_text: "" } }),
      card({ name: "Latecomer", media: { image_url: "https://cdn/art.png", artist: "", accessibility_text: "" } }),
    ]);
    expect(index["latecomer"].image).toBe("https://cdn/art.png");
  });

  it("resolves a card under both its full name and its base name", () => {
    const index = buildCardIndex([card({ name: "Viktor - Machine Herald" })]);
    expect(index["viktor"].name).toBe("Viktor - Machine Herald");
    expect(index["viktor - machine herald"]).toBeDefined();
  });

  it("omits the image key entirely when there is no artwork", () => {
    const index = buildCardIndex([card({ name: "Artless Card" })]);
    expect("image" in index["artless card"]).toBe(false);
  });
});

describe("buildSkillData", () => {
  it("writes a sorted index so an unchanged corpus regenerates identically", async () => {
    const dir = mkdtempSync(join(tmpdir(), "skill-data-"));
    try {
      const out = join(dir, "cards.json");
      const opts = {
        outputPath: out,
        listSets: async () => [{ set_id: "VEN", name: "Vendetta", card_count: 2 }] as never,
        listCards: async () => [
          card({ name: "Zed - Shadow" }),
          card({ name: "Astral Heron", media: { image_url: "https://cdn/h.png", artist: "", accessibility_text: "" } }),
        ],
      };

      const first = await buildSkillData(opts);
      const a = readFileSync(out, "utf-8");
      expect(Object.keys(JSON.parse(a))).toEqual([...Object.keys(JSON.parse(a))].sort());
      expect(first.withArt).toBe(1);
      expect(first.cards).toBe(2);

      await buildSkillData(opts);
      expect(readFileSync(out, "utf-8")).toBe(a);
    } finally {
      rmSync(dir, { recursive: true });
    }
  });

  it("creates the data directory when it does not exist yet", async () => {
    const dir = mkdtempSync(join(tmpdir(), "skill-data-"));
    try {
      const out = join(dir, "nested", "deeper", "cards.json");
      await buildSkillData({
        outputPath: out,
        listSets: async () => [{ set_id: "VEN", name: "Vendetta", card_count: 1 }] as never,
        listCards: async () => [card({ name: "Astral Heron" })],
      });
      expect(JSON.parse(readFileSync(out, "utf-8"))["astral heron"].name).toBe("Astral Heron");
    } finally {
      rmSync(dir, { recursive: true });
    }
  });
});

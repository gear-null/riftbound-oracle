import { describe, it, expect } from "vitest";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { buildCardIndex, buildSkillData, cardStats, cardText, keysFor } from "../skill-data.js";
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

  it("carries no markdown — stats are structured, not glued on as prose", () => {
    // They used to ship as "**Energy:** 7 | **Might:** 7 | ...", which then
    // rendered literally in reports because nothing downstream parses markdown.
    const c = card({
      name: "Astral Heron",
      attributes: { energy: 7, might: 7, power: null },
      classification: { type: "Unit", supertype: null, rarity: "Epic", domain: ["Calm"] },
      text: { rich: "", plain: "When you play your first card each turn...", flavour: null },
    });
    expect(cardText(c)).not.toContain("**");
    expect(cardText(c)).toBe("When you play your first card each turn...");
    expect(cardStats(c)).toEqual({
      energy: 7, might: 7, power: null, type: "Unit", rarity: "Epic", domain: ["Calm"],
    });
  });

  it("keeps a zero cost as 0, not null", () => {
    // 7 cards genuinely cost 0 Energy; a falsy-check would erase their cost.
    const s = cardStats(card({ name: "Called Shot", attributes: { energy: 0, might: null, power: null } }));
    expect(s.energy).toBe(0);
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

  it("returns empty text for a vanilla card, with its stats intact", () => {
    // A card with no rules text has no text — the stats are not a substitute
    // for it, which is exactly why they no longer live in the same string.
    const c = card({ name: "Vanilla", attributes: { energy: 2, might: 3, power: null } });
    expect(cardText(c)).toBe("");
    expect(cardStats(c).might).toBe(3);
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

  it("is deterministic regardless of the order cards arrive in", () => {
    // The API paginates without a guaranteed sort, so "first printing wins"
    // was decided by fetch order: two consecutive real runs differed in 27
    // entries, 5 binding a base name to a genuinely different card.
    const pool = [
      card({ name: "Ahri - Alluring", set: { set_id: "OGN", label: "O" }, collector_number: 12 }),
      card({ name: "Ahri - Inquisitive", set: { set_id: "VEN", label: "V" }, collector_number: 3 }),
      card({ name: "Ahri - Nine-Tailed Fox", set: { set_id: "OGN", label: "O" }, collector_number: 4 }),
    ] as never[];
    const forward = JSON.stringify(buildCardIndex(pool));
    const reversed = JSON.stringify(buildCardIndex([...pool].reverse()));
    expect(reversed).toBe(forward);
    // and the winner is the stable one: OGN #4 sorts before OGN #12
    expect(buildCardIndex(pool)["ahri"].name).toBe("Ahri - Nine-Tailed Fox");
  });

  it("flags a base name shared by genuinely different cards", () => {
    // Silently answering about one arbitrary printing is the failure the whole
    // card path exists to prevent.
    const index = buildCardIndex([
      card({ name: "Ahri - Alluring" }),
      card({ name: "Ahri - Inquisitive" }),
    ] as never[]);
    expect(index["ahri"].ambiguous).toEqual(["Ahri - Alluring", "Ahri - Inquisitive"]);
    // an unambiguous name carries no flag at all
    expect(buildCardIndex([card({ name: "Astral Heron" })])["astral heron"].ambiguous)
      .toBeUndefined();
  });

  it("prefers a real rarity over a print treatment", () => {
    // 126 of 954 cards showed "Promo"/"Showcase" where their rarity belongs.
    const index = buildCardIndex([
      card({ name: "Doran's Blade", classification: { type: "Gear", supertype: null, rarity: "Promo", domain: [] }, set: { set_id: "AAA", label: "a" }, collector_number: 1 }),
      card({ name: "Doran's Blade", classification: { type: "Gear", supertype: null, rarity: "Common", domain: [] }, set: { set_id: "BBB", label: "b" }, collector_number: 2 }),
    ] as never[]);
    expect(index["doran's blade"].stats.rarity).toBe("Common");
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

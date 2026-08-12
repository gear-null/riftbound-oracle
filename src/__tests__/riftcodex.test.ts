import { describe, it, expect, vi, afterEach } from "vitest";
import {
  cardToMarkdown,
  cardsToMarkdown,
  resolveSetLabel,
  fetchSetLabel,
  resetSetIndexCache,
  type RiftcodexCard,
} from "../riftcodex.js";

function makeCard(overrides: Partial<RiftcodexCard> = {}): RiftcodexCard {
  return {
    id: "abc123",
    name: "Test Card",
    riftbound_id: "ogn-001-298",
    tcgplayer_id: "100001",
    collector_number: 1,
    attributes: { energy: 3, might: 2, power: 1 },
    classification: { type: "Unit", supertype: null, rarity: "Common", domain: ["Order"] },
    text: { rich: "<p>Do something.</p>", plain: "Do something.", flavour: "A wise quote." },
    set: { set_id: "OGN", label: "Origins" },
    media: { image_url: "https://example.com/card.png", artist: "Test Artist", accessibility_text: "Test" },
    tags: ["Elite", "Demacia"],
    orientation: "portrait",
    metadata: { clean_name: "Test Card", updated_on: "2026-03-01", alternate_art: false, overnumbered: false, signature: false },
    ...overrides,
  };
}

describe("cardToMarkdown", () => {
  it("includes card name as heading", () => {
    const md = cardToMarkdown(makeCard({ name: "Vanguard Captain" }));
    expect(md).toContain("### Vanguard Captain");
  });

  it("includes stats when present", () => {
    const md = cardToMarkdown(makeCard({ attributes: { energy: 5, might: 3, power: null } }));
    expect(md).toContain("**Energy:** 5");
    expect(md).toContain("**Might:** 3");
    expect(md).not.toContain("**Power:**");
  });

  it("includes card text and flavour", () => {
    const md = cardToMarkdown(makeCard());
    expect(md).toContain("Do something.");
    expect(md).toContain("A wise quote.");
  });

  it("omits flavour when null", () => {
    const md = cardToMarkdown(makeCard({ text: { rich: "", plain: "Effect.", flavour: null } }));
    expect(md).not.toContain(">");
  });

  it("includes tags", () => {
    const md = cardToMarkdown(makeCard({ tags: ["Elite", "Demacia"] }));
    expect(md).toContain("**Tags:** Elite, Demacia");
  });

  it("includes artist and set info", () => {
    const md = cardToMarkdown(makeCard());
    expect(md).toContain("*Artist: Test Artist | Origins #1*");
  });
});

describe("resolveSetLabel", () => {
  it("uses the label carried on the set's cards", () => {
    const cards = [makeCard({ set: { set_id: "VEN", label: "Vendetta" } })];
    expect(resolveSetLabel(cards, "VEN")).toBe("Vendetta");
  });

  it("falls back to the set id for an empty set", () => {
    expect(resolveSetLabel([], "VEN")).toBe("VEN");
  });

  it("falls back to the set id when the label is blank", () => {
    const cards = [makeCard({ set: { set_id: "VEN", label: "   " } })];
    expect(resolveSetLabel(cards, "VEN")).toBe("VEN");
  });

  it("produces a titled heading rather than a bare set id", () => {
    const cards = [makeCard({ set: { set_id: "SFD", label: "Spiritforged" } })];
    const md = cardsToMarkdown(cards, resolveSetLabel(cards, "SFD"));
    expect(md).toContain("# Spiritforged — Complete Card List");
    expect(md).not.toContain("# SFD Set");
  });
});

describe("fetchSetLabel", () => {
  afterEach(() => {
    resetSetIndexCache();
    vi.unstubAllGlobals();
  });

  function stubSets(items: Array<{ set_id: string; name: string }>) {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      status: 200,
      statusText: "OK",
      json: async () => ({ items }),
    }));
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }

  it("prefers the canonical /sets name over the shorter card label", async () => {
    stubSets([{ set_id: "OGS", name: "Origins: Proving Grounds" }]);
    const cards = [makeCard({ set: { set_id: "OGS", label: "Proving Grounds" } })];
    await expect(fetchSetLabel("OGS", cards)).resolves.toBe("Origins: Proving Grounds");
  });

  it("fetches /sets only once across multiple lookups", async () => {
    const fetchMock = stubSets([
      { set_id: "VEN", name: "Vendetta" },
      { set_id: "UNL", name: "Unleashed" },
    ]);
    await fetchSetLabel("VEN");
    await fetchSetLabel("UNL");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("degrades to the card label when /sets fails", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("ECONNRESET"); }));
    const cards = [makeCard({ set: { set_id: "VEN", label: "Vendetta" } })];
    await expect(fetchSetLabel("VEN", cards)).resolves.toBe("Vendetta");
  });

  it("degrades to the set id when /sets fails and no cards are available", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("ECONNRESET"); }));
    await expect(fetchSetLabel("VEN")).resolves.toBe("VEN");
  });

  it("retries /sets on a later lookup after a failure", async () => {
    const failing = vi.fn(async () => { throw new Error("ECONNRESET"); });
    vi.stubGlobal("fetch", failing);
    await fetchSetLabel("VEN");

    stubSets([{ set_id: "VEN", name: "Vendetta" }]);
    await expect(fetchSetLabel("VEN")).resolves.toBe("Vendetta");
  });

  it("falls back when /sets succeeds but omits the set", async () => {
    stubSets([{ set_id: "OGN", name: "Origins" }]);
    const cards = [makeCard({ set: { set_id: "VEN", label: "Vendetta" } })];
    await expect(fetchSetLabel("VEN", cards)).resolves.toBe("Vendetta");
  });
});

describe("cardsToMarkdown", () => {
  it("groups cards by type", () => {
    const cards = [
      makeCard({ name: "A Spell", classification: { type: "Spell", supertype: null, rarity: "Common", domain: [] }, collector_number: 2 }),
      makeCard({ name: "A Unit", classification: { type: "Unit", supertype: null, rarity: "Rare", domain: [] }, collector_number: 1 }),
    ];
    const md = cardsToMarkdown(cards, "Origins");
    expect(md).toContain("## Spells (1)");
    expect(md).toContain("## Units (1)");
  });

  it("includes set label in title and total count", () => {
    const cards = [makeCard()];
    const md = cardsToMarkdown(cards, "Origins");
    expect(md).toContain("# Origins — Complete Card List");
    expect(md).toContain("**Total cards:** 1");
  });

  it("sorts cards by collector number within each type", () => {
    const cards = [
      makeCard({ name: "Second", collector_number: 10 }),
      makeCard({ name: "First", collector_number: 5 }),
    ];
    const md = cardsToMarkdown(cards, "Origins");
    const firstIdx = md.indexOf("### First");
    const secondIdx = md.indexOf("### Second");
    expect(firstIdx).toBeLessThan(secondIdx);
  });
});

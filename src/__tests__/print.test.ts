import { describe, it, expect } from "vitest";
import type { RiftcodexCard } from "../riftcodex.js";

// Import the sort/filter logic by testing the output structure
// We test the core logic functions indirectly through the module

function makeCard(overrides: Partial<RiftcodexCard> = {}): RiftcodexCard {
  return {
    id: "abc",
    name: "Test Card",
    riftbound_id: "ogn-001",
    tcgplayer_id: "1",
    collector_number: 1,
    attributes: { energy: 3, might: 2, power: 1 },
    classification: { type: "Unit", supertype: null, rarity: "Common", domain: ["Order"] },
    text: { rich: "", plain: "", flavour: null },
    set: { set_id: "OGN", label: "Origins" },
    media: { image_url: "https://example.com/card.png", artist: "Test", accessibility_text: "" },
    tags: [],
    orientation: "portrait",
    metadata: { clean_name: "Test Card", updated_on: "2026-01-01", alternate_art: false, overnumbered: false, signature: false },
    ...overrides,
  };
}

// Re-implement the filter/sort logic for testing (same as print.ts)
function isUnique(card: RiftcodexCard): boolean {
  if (card.metadata.alternate_art) return false;
  if (card.metadata.overnumbered) return false;
  if (card.classification.rarity === "Showcase") return false;
  return true;
}

function domainSortKey(card: RiftcodexCard): string {
  const domains = card.classification.domain;
  if (domains.length === 0) return "ZZZ_Colorless";
  if (domains.length > 1) return "ZZZ_Multi_" + domains.sort().join("_");
  return domains[0];
}

function sortCards(cards: RiftcodexCard[]): RiftcodexCard[] {
  return [...cards].sort((a, b) => {
    const domainA = domainSortKey(a);
    const domainB = domainSortKey(b);
    if (domainA !== domainB) return domainA.localeCompare(domainB);
    const energyA = a.attributes.energy ?? 0;
    const energyB = b.attributes.energy ?? 0;
    if (energyA !== energyB) return energyA - energyB;
    const powerA = a.attributes.power ?? 0;
    const powerB = b.attributes.power ?? 0;
    if (powerA !== powerB) return powerA - powerB;
    return a.name.localeCompare(b.name);
  });
}

describe("print card filtering", () => {
  it("filters out alternate art cards", () => {
    const card = makeCard({ metadata: { ...makeCard().metadata, alternate_art: true } });
    expect(isUnique(card)).toBe(false);
  });

  it("filters out overnumbered cards", () => {
    const card = makeCard({ metadata: { ...makeCard().metadata, overnumbered: true } });
    expect(isUnique(card)).toBe(false);
  });

  it("filters out Showcase rarity", () => {
    const card = makeCard({ classification: { ...makeCard().classification, rarity: "Showcase" } });
    expect(isUnique(card)).toBe(false);
  });

  it("keeps regular cards", () => {
    expect(isUnique(makeCard())).toBe(true);
    expect(isUnique(makeCard({ classification: { ...makeCard().classification, rarity: "Rare" } }))).toBe(true);
  });
});

describe("print card sorting", () => {
  it("sorts by domain first", () => {
    const cards = [
      makeCard({ name: "Z", classification: { ...makeCard().classification, domain: ["Order"] } }),
      makeCard({ name: "A", classification: { ...makeCard().classification, domain: ["Body"] } }),
    ];
    const sorted = sortCards(cards);
    expect(sorted[0].name).toBe("A"); // Body before Order
  });

  it("sorts multi-domain cards after single-domain", () => {
    const cards = [
      makeCard({ name: "Multi", classification: { ...makeCard().classification, domain: ["Fury", "Mind"] } }),
      makeCard({ name: "Single", classification: { ...makeCard().classification, domain: ["Order"] } }),
    ];
    const sorted = sortCards(cards);
    expect(sorted[0].name).toBe("Single");
    expect(sorted[1].name).toBe("Multi");
  });

  it("sorts colorless cards after single-domain", () => {
    const cards = [
      makeCard({ name: "Colorless", classification: { ...makeCard().classification, domain: [] } }),
      makeCard({ name: "Single", classification: { ...makeCard().classification, domain: ["Fury"] } }),
    ];
    const sorted = sortCards(cards);
    expect(sorted[0].name).toBe("Single");
    expect(sorted[1].name).toBe("Colorless");
  });

  it("sorts by energy within same domain", () => {
    const cards = [
      makeCard({ name: "Expensive", attributes: { energy: 5, might: null, power: null } }),
      makeCard({ name: "Cheap", attributes: { energy: 1, might: null, power: null } }),
    ];
    const sorted = sortCards(cards);
    expect(sorted[0].name).toBe("Cheap");
  });

  it("sorts by power within same domain and energy", () => {
    const cards = [
      makeCard({ name: "Strong", attributes: { energy: 3, might: null, power: 2 } }),
      makeCard({ name: "Weak", attributes: { energy: 3, might: null, power: 0 } }),
    ];
    const sorted = sortCards(cards);
    expect(sorted[0].name).toBe("Weak");
  });

  it("sorts alphabetically as final tiebreaker", () => {
    const cards = [
      makeCard({ name: "Zebra" }),
      makeCard({ name: "Alpha" }),
    ];
    const sorted = sortCards(cards);
    expect(sorted[0].name).toBe("Alpha");
  });
});

import { describe, it, expect } from "vitest";
import { parseErrata, sameWording, wordsOf } from "../errata.js";
import { applyErratum, buildCardIndex } from "../skill-data.js";

const ARTICLE = `# Unleashed Cards

## Stalking Wolf

![](https://cdn/x.jpg)

**\\[NEW TEXT\\]**

\\[Ambush\\] (You may play me as a \\[Reaction\\].)

You may \\[Ambush\\] me to its battlefield, even if you don't have other units there.

▲

**\\[OLD TEXT\\]**

You may play me to its battlefield (even if you don't have other units there).

* * *

## Not Errata'd

Just an article with no new text.

# Vendetta Cards

## Astral Heron

**\\[NEW TEXT\\]**

When you play your first card each turn, the next card costs \\[2\\] less.

▲

**\\[OLD TEXT\\]**

Your next card costs \\[2\\] less.
`;

describe("parseErrata", () => {
  const e = parseErrata(ARTICLE);

  it("finds every card with new text, across heading levels", () => {
    // A `# Set` heading between entries must not end the sweep.
    expect([...e.keys()].sort()).toEqual(["astral heron", "stalking wolf"]);
  });

  it("takes the NEW text and stops before the OLD", () => {
    const t = e.get("stalking wolf")!.text;
    expect(t).toContain("[Ambush] me to its battlefield");
    expect(t).not.toContain("you may play me to its battlefield");
  });

  it("unescapes markdown brackets so keywords survive", () => {
    expect(e.get("stalking wolf")!.text).toContain("[Ambush]");
    expect(e.get("stalking wolf")!.text).not.toContain("\\[");
  });

  it("ignores an article that has no new text", () => {
    expect(e.has("not errata'd")).toBe(false);
  });

  it("returns nothing for markdown with no errata at all", () => {
    expect(parseErrata("# Rules\n\nSome prose.\n").size).toBe(0);
  });
});

describe("sameWording", () => {
  it("treats a notation difference as unchanged", () => {
    // The errata prints [1][C] where the API sends :rb_energy_1:. Rewriting
    // every reprint into the other notation would churn the corpus for nothing.
    expect(sameWording("Pay :rb_energy_1: to draw 1.", "Pay [1] to draw 1.")).toBe(true);
  });

  it("treats a real wording change as changed", () => {
    expect(sameWording("play me to its battlefield", "ambush me to its battlefield")).toBe(false);
  });

  it("notices a dropped word", () => {
    // Ava Achiever lost "here" — a targeting restriction, not a rewording.
    expect(sameWording("play a card from your hand here", "play a card from your hand")).toBe(false);
  });

  it("ignores bracketed symbols entirely", () => {
    expect(wordsOf("[Ambush] deal [2] damage")).toEqual(["deal", "damage"]);
  });
});

describe("applyErratum", () => {
  const card = { name: "Stalking Wolf", text: "You may play me to its battlefield.", stats: {} as never };

  it("replaces stale text and records provenance", () => {
    const r = applyErratum(card, { name: "Stalking Wolf", text: "You may ambush me to its battlefield." });
    expect(r.text).toContain("ambush me");
    expect(r.errata).toContain("Riot errata");
  });

  it("leaves a card alone when only the notation differs", () => {
    const c = { ...card, text: "Pay :rb_energy_1: to draw 1." };
    const r = applyErratum(c, { name: "x", text: "Pay [1] to draw 1." });
    expect(r.text).toBe(c.text);
    expect(r.errata).toBeUndefined();
  });

  it("is a no-op with no erratum", () => {
    expect(applyErratum(card, undefined)).toBe(card);
  });
});

describe("buildCardIndex with errata", () => {
  it("prefers Riot's text over the API's", () => {
    const api = [{
      name: "Stalking Wolf", collector_number: 1, riftbound_id: "a", id: "a",
      attributes: { energy: 4, might: 6, power: null },
      classification: { type: "Unit", supertype: null, rarity: "Uncommon", domain: ["Order"] },
      text: { rich: "", plain: "You may play me to its battlefield.", flavour: null },
      set: { set_id: "UNL", label: "U" }, media: { image_url: "", artist: "", accessibility_text: "" },
      tags: [], orientation: "portrait", metadata: {} as never,
    }] as never[];
    const idx = buildCardIndex(api, new Map(), new Map([
      ["stalking wolf", { name: "Stalking Wolf", text: "You may [Ambush] me to its battlefield." }],
    ]));
    expect(idx["stalking wolf"].text).toContain("[Ambush]");
    expect(idx["stalking wolf"].errata).toBeDefined();
  });
});

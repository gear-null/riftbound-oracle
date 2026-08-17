import { describe, it, expect } from "vitest";
import { countErrataMarkers, parseErrata, sameWording, wordsOf } from "../errata.js";
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

// Round 8: the parser was anchored to exactly two hashes, so an entire Riot
// article was skipped and six cards served text Riot had RETRACTED, with no
// banner. These pin the shapes the real corpus actually contains.
const SPIRITFORGED = `# **_Spiritforged Cards_**

# **Tianna Crownguard**

##### **\\[NEW TEXT\\]**

While I'm at a battlefield, opponents can't gain points.

#### **▲**

##### **\\[OLD TEXT\\]**

While I'm at a battlefield, opponents can't score points.

* * *

## Ava Achiever

##### **\\[NEW TEXT\\]**

Deal 2 to a unit.

#### ▲

##### **\\[OLD TEXT\\]**

Deal 3 to a unit.
`;

describe("parseErrata heading shapes", () => {
  const parsed = parseErrata(SPIRITFORGED);

  it("reads `# **Card Name**`, not only `## Card Name`", () => {
    expect(parsed.get("tianna crownguard")?.text)
      .toBe("While I'm at a battlefield, opponents can't gain points.");
  });

  it("still reads the two-hash shape", () => {
    expect(parsed.get("ava achiever")?.text).toBe("Deal 2 to a unit.");
  });

  it("does not mistake a bold-italic group heading for a card", () => {
    expect([...parsed.keys()]).not.toContain("_spiritforged cards_");
    expect(parsed.size).toBe(2);
  });

  it("stops at a decorated ▲, so no markdown reaches the card text", () => {
    for (const e of parsed.values()) {
      expect(e.text).not.toMatch(/▲|#{2,}/);
    }
  });

  it("counts the markers so a future heading shape cannot vanish quietly", () => {
    expect(countErrataMarkers(SPIRITFORGED)).toBe(parsed.size);
  });
});

describe("sameWording counts digits", () => {
  it("a numeric nerf in prose is a real change, not a reprint", () => {
    expect(sameWording("Deal 4 to a unit.", "Deal 5 to a unit.")).toBe(false);
    expect(sameWording("Draw 1 card.", "Draw 2 cards.")).toBe(false);
  });

  it("but notation still does not count", () => {
    expect(sameWording("[Ambush] I am fast.", "I am fast.")).toBe(true);
    expect(sameWording("[1][C]: Draw 1.", ":rb_energy_1::rb_calm:: Draw 1.")).toBe(true);
  });

  // KNOWN LIMIT, pinned so it is a decision rather than a surprise. Bracket
  // CONTENTS are dropped because the two sources spell the same cost
  // differently (`[1][C]` vs `:rb_energy_1:`), so a change expressed purely
  // inside brackets — a cost nerf from [1] to [3] — reads as a reprint and the
  // erratum is not applied. Closing it means canonicalising both notations
  // rather than deleting them. No live instance today.
  it("does NOT yet see a change made only inside notation", () => {
    expect(sameWording("[1][C]: Draw 1.", "[3][C]: Draw 1.")).toBe(true);
  });
});

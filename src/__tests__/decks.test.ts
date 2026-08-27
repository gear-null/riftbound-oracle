import { describe, expect, it } from "vitest";
import {
  deckSlug,
  lookupCard,
  parseDeckIndex,
  parseDeckPage,
  pullMetaDecks,
  resolveChosenChampion,
  type Deck,
} from "../decks.js";
import type { CardIndex } from "../skill-data.js";
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

/** A page whose two champions both carry the legend's tag, so it stays unresolved. */
function ambiguousPage(): string {
  return page({
    sections:
      section("Champions", 6, tile("SFD-057", "Irelia, Fervent", 3) + tile("SFD-058", "Irelia, Graceful", 3)) +
      section("Runes", 12, tile("calmrune", "Calm Rune", 12)) +
      section("Battlefields", 3, tile("OGN-276", "Aspirant's Climb") + tile("SFD-215", "Ravenbloom Conservatory") + tile("OGN-292", "The Dreaming Tree")),
  });
}

/** A tile as the site renders it — the count badge is omitted for singletons. */
function tile(code: string, name: string, qty = 1): string {
  const badge = qty > 1 ? `<span class="deck-card-count">${qty}</span>` : "";
  return `<a class="deck-card-tile" href="/atlas/${code}" title="${name}"><img src="/images/cards/${code}.webp" alt="${name}"/><span class="deck-card-fallback">${name}</span>${badge}</a>`;
}

function section(heading: string, declared: number, tiles: string): string {
  return `<section class="deck-section"><h2>${heading}<!-- --> <span class="deck-section-count">${declared}</span></h2><div class="deck-card-grid">${tiles}</div></section>`;
}

function page(overrides: { sections?: string; meta?: boolean } = {}): string {
  const sections =
    overrides.sections ??
    section("Legend", 1, tile("SFD-195a", "Irelia, Blade Dancer")) +
      section("Champions", 4, tile("SFD-057", "Irelia, Fervent", 3) + tile("SFD-148A", "Draven, Audacious")) +
      section("Units", 3, tile("SFD-048", "Stellacorn Herder", 3)) +
      section("Spells", 2, tile("OGN-046", "Called Shot", 2)) +
      section("Runes", 12, tile("calmrune", "Calm Rune", 6) + tile("chaosrunes", "Chaos Rune", 6)) +
      section("Battlefields", 3, tile("OGN-276", "Aspirant's Climb") + tile("SFD-215", "Ravenbloom Conservatory") + tile("OGN-292", "The Dreaming Tree"));
  return `<html><body><div class="deck-hero"><div class="deck-hero-info">${
    overrides.meta === false ? "" : '<span class="meta-badge">META</span>'
  }<h1 class="deck-title">Irelia Tempo</h1><div class="deck-author">by <!-- -->Dezmu</div><div class="deck-meta-row">Legend: <strong>Irelia, Blade Dancer</strong></div><div class="deck-colors"><span class="deck-color-chip">Calm</span><span class="deck-color-chip">Chaos</span></div></div></div><div>${sections}</div></body></html>`;
}

const CARDS: CardIndex = {
  "irelia, blade dancer": stub("Irelia, Blade Dancer", "Legend", null, ["Irelia"]),
  "irelia, fervent": stub("Irelia, Fervent", "Unit", "Champion", ["Irelia", "Ionia"]),
  "irelia, graceful": stub("Irelia, Graceful", "Unit", "Champion", ["Irelia", "Ionia"]),
  "draven, audacious": stub("Draven, Audacious", "Unit", "Champion", ["Draven", "Noxus"]),
  "stellacorn herder": stub("Stellacorn Herder", "Unit", null, []),
};

function stub(name: string, type: string, supertype: string | null, tags: string[]) {
  return {
    name,
    text: "",
    stats: { energy: 3, might: 3, power: null, type, rarity: "Rare", domain: ["Calm"], supertype, tags },
  };
}

describe("parseDeckPage", () => {
  it("folds every main-deck category into one list, as the rules do", () => {
    // The site splits Champions/Units/Spells/Gear for display, but rule 103.2
    // makes all of them the Main Deck — they shuffle together, so keeping the
    // display split would make every opening-hand draw wrong.
    const { deck } = parseDeckPage(page(), "https://rift-atlas.com/meta/x", "2026-08-24");
    expect(deck.main.map((c) => c.name)).toEqual([
      "Irelia, Fervent",
      "Draven, Audacious",
      "Stellacorn Herder",
      "Called Shot",
    ]);
    expect(deck.main.reduce((n, c) => n + c.qty, 0)).toBe(9);
  });

  it("reads a missing count badge as one copy, not zero", () => {
    // The badge only renders above 1. Treating its absence as zero silently
    // drops every singleton — which is most of a battlefield set.
    const { deck } = parseDeckPage(page(), "https://rift-atlas.com/meta/x", "2026-08-24");
    expect(deck.battlefields).toHaveLength(3);
    expect(deck.battlefields.every((b) => b.qty === 1)).toBe(true);
    expect(deck.runes.map((r) => r.qty)).toEqual([6, 6]);
  });

  it("records provenance including whether the source called it a meta list", () => {
    const { deck } = parseDeckPage(page(), "https://rift-atlas.com/meta/x", "2026-08-24");
    expect(deck.source).toMatchObject({
      site: "rift-atlas.com",
      url: "https://rift-atlas.com/meta/x",
      author: "Dezmu",
      meta: true,
      fetched: "2026-08-24",
    });
    const brew = parseDeckPage(page({ meta: false }), "u", "2026-08-24");
    expect(brew.deck.source?.meta).toBe(false);
  });

  it("warns when the page's own count disagrees with the tiles it rendered", () => {
    // A short section means the page did not finish rendering. Silently
    // accepting it produces a 34-card deck that draws nothing it should.
    const html = page({
      sections: section("Spells", 24, tile("OGN-046", "Called Shot", 2)),
    });
    const { warnings } = parseDeckPage(html, "u", "2026-08-24");
    expect(warnings).toContain("Spells: page declares 24, tiles total 2");
  });

  it("refuses a page with no legend rather than emitting a deck that cannot be played", () => {
    expect(() => parseDeckPage("<html><body></body></html>", "u", "2026-08-24")).toThrow(/no legend/);
  });

  it("never emits a NaN quantity from an unreadable count badge", () => {
    // parseInt("x6") is NaN, JSON.stringify turns NaN into null, and the Python
    // loader's int(c["qty"]) then raises on a file that looks fine — a failure
    // three layers away from its cause.
    const html = page({
      sections: section("Units", 6, tile("SFD-048", "Stellacorn Herder", 3).replace(">3<", ">many<")),
    });
    const { deck, structural } = parseDeckPage(html, "u", "2026-08-24");
    expect(deck.main.every((c) => Number.isFinite(c.qty))).toBe(true);
    expect(structural.join(" ")).toMatch(/unreadable count badge/);
  });

  it("still reads a badge that carries a prefix around its digits", () => {
    // "x3" is a rendering variant, not a failure — the digits are right there.
    const html = page({
      sections: section("Units", 3, tile("SFD-048", "Stellacorn Herder", 3).replace(">3<", ">x3<")),
    });
    expect(parseDeckPage(html, "u", "2026-08-24").deck.main[0].qty).toBe(3);
  });

  it("reads a two-digit count, not just its first digit", () => {
    const html = page({ sections: section("Runes", 12, tile("calmrune", "Calm Rune", 12)) });
    expect(parseDeckPage(html, "u", "2026-08-24").deck.runes[0].qty).toBe(12);
  });

  it("reads every section sharing a heading, not just the first", () => {
    // A prefix match took the first "Units" section and silently dropped the
    // rest of the deck's units.
    const html = page({
      sections:
        section("Units", 1, tile("SFD-048", "Stellacorn Herder")) +
        section("Units", 1, tile("OGN-046", "Called Shot")),
    });
    const { deck } = parseDeckPage(html, "u", "2026-08-24");
    expect(deck.main.map((c) => c.name).sort()).toEqual(["Called Shot", "Stellacorn Herder"]);
  });

  it("does not absorb a different section whose heading starts with the same word", () => {
    // The heading must genuinely share the prefix for this to test anything —
    // "Unit Tokens" does not start with "Units", so an earlier version of this
    // check passed against the prefix-matching bug it was named for.
    const html = page({
      sections:
        section("Units", 1, tile("SFD-048", "Stellacorn Herder")) +
        section("Units (sideboard)", 1, tile("OGN-046", "Called Shot")),
    });
    const { deck } = parseDeckPage(html, "u", "2026-08-24");
    expect(deck.main.map((c) => c.name)).toEqual(["Stellacorn Herder"]);
  });

  it("flags a missing mandatory section instead of reporting an empty one", () => {
    // Every legal list has runes and battlefields (103.3.a, 103.4.a), so their
    // absence is a rendering failure, never a property of the deck.
    const html = page({ sections: section("Units", 1, tile("SFD-048", "Stellacorn Herder")) });
    const { structural } = parseDeckPage(html, "u", "2026-08-24");
    expect(structural).toContain("Runes: section not found on the page");
    expect(structural).toContain("Battlefields: section not found on the page");
  });

  it("does not treat an unreadable declared count as agreement", () => {
    // The guard against a half-rendered page used to switch itself off in
    // exactly the case it exists to catch.
    const html = page({
      sections: section("Units", 3, tile("SFD-048", "Stellacorn Herder")).replace(
        '<span class="deck-section-count">3</span>',
        '<span class="deck-section-count">—</span>'
      ),
    });
    const { structural } = parseDeckPage(html, "u", "2026-08-24");
    expect(structural.join(" ")).toMatch(/no declared count/);
  });
});

describe("parseDeckIndex", () => {
  it("collects deck ids once each", () => {
    const html = `<a href="/meta/aaa"></a><a href="/meta/bbb"></a><a href="/meta/aaa"></a><a href="/decks"></a>`;
    expect(parseDeckIndex(html)).toEqual(["aaa", "bbb"]);
  });

  it("treats a fragment or query on the same deck as the same deck", () => {
    // Raw hrefs made /meta/aaa and /meta/aaa#comments two ids that both
    // survived the Set and were both fetched — a wasted request against a site
    // this pulls from politely, and a duplicate deck written twice.
    const html = `<a href="/meta/aaa"></a><a href="/meta/aaa#comments"></a><a href="/meta/aaa?ref=x"></a>`;
    expect(parseDeckIndex(html)).toEqual(["aaa"]);
  });

  it("ignores non-deck pages that also live under /meta/", () => {
    // The index links tier lists and archetype hubs there too; fetching one as
    // a deck throws "no legend found" and eats a request.
    const html = `<a href="/meta/aaa"></a><a href="/meta/tier-list/aggro"></a>`;
    expect(parseDeckIndex(html)).toEqual(["aaa"]);
  });
});

describe("resolveChosenChampion", () => {
  const deck = (main: string[]): Deck => ({
    name: "d",
    legend: "Irelia, Blade Dancer",
    chosenChampion: null,
    domains: [],
    main: main.map((name) => ({ name, code: "", qty: 3 })),
    runes: [],
    battlefields: [],
  });

  it("binds by champion tag, not by name", () => {
    const r = resolveChosenChampion(deck(["Irelia, Fervent", "Draven, Audacious"]), CARDS);
    expect(r.chosenChampion).toBe("Irelia, Fervent");
  });

  it("resolves when the legend is spelled with the other separator", () => {
    // The deck says "Irelia, Blade Dancer"; the card data says
    // "Irelia - Blade Dancer". Failing this lookup drops the legend's tags,
    // which makes every champion in the deck look like a candidate.
    const dashIndex: CardIndex = { ...CARDS, "irelia - blade dancer": CARDS["irelia, blade dancer"] };
    delete dashIndex["irelia, blade dancer"];
    const r = resolveChosenChampion(deck(["Irelia, Fervent", "Draven, Audacious"]), dashIndex);
    expect(r.chosenChampion).toBe("Irelia, Fervent");
  });

  it("leaves it unresolved when the tag matches two champions", () => {
    // Both are legal Chosen Champions for this legend. Picking one silently
    // would change every opening hand the deck ever draws.
    const r = resolveChosenChampion(deck(["Irelia, Fervent", "Irelia, Graceful"]), CARDS);
    expect(r.chosenChampion).toBeNull();
    expect(r.championCandidates).toEqual(["Irelia, Fervent", "Irelia, Graceful"]);
  });

  it("ignores non-champion units even when they share a domain", () => {
    const r = resolveChosenChampion(deck(["Stellacorn Herder", "Irelia, Fervent"]), CARDS);
    expect(r.chosenChampion).toBe("Irelia, Fervent");
  });
});

describe("lookupCard", () => {
  // Riftcodex writes "Master Yi - Wuju Bladesman"; rift-atlas writes
  // "Master Yi, Wuju Bladesman". Every legend and every champion is subtitled,
  // so a literal match resolved none of them.
  const index: CardIndex = { "master yi - wuju bladesman": stub("Master Yi - Wuju Bladesman", "Legend", null, ["Master Yi"]) };

  it("matches across the separator the two sources disagree on", () => {
    expect(lookupCard(index, "Master Yi, Wuju Bladesman")?.name).toBe("Master Yi - Wuju Bladesman");
  });

  it("matches in the other direction too", () => {
    const commaIndex: CardIndex = { "irelia, fervent": stub("Irelia, Fervent", "Unit", "Champion", []) };
    expect(lookupCard(commaIndex, "Irelia - Fervent")?.name).toBe("Irelia, Fervent");
  });

  it("returns nothing rather than a near miss", () => {
    // A wrong card is worse than no card: it would be shuffled into the deck
    // and played as if it were the one the list named.
    expect(lookupCard(index, "Master Yi")).toBeUndefined();
    expect(lookupCard(index, "Master Yi - Wuju Master")).toBeUndefined();
  });
});

describe("deckSlug", () => {
  const withUrl = (legend: string, name: string, url: string) =>
    ({ legend, name, source: { url } } as unknown as Deck);

  it("is stable across runs, so a re-pull overwrites rather than accumulates", () => {
    const d = withUrl("Irelia, Blade Dancer", "Irelia 2025 12 17", "https://x/meta/a");
    expect(deckSlug(d)).toBe(deckSlug(d));
    expect(deckSlug(d)).toMatch(/^irelia-blade-dancer-irelia-2025-12-17-[0-9a-f]{6}$/);
  });

  it("keeps two long, similarly-named decks apart", () => {
    // Three of the 24 decks currently pulled already hit the truncation limit,
    // so two lists whose names differ only past it would slugify identically
    // and the second would overwrite the first while both were counted written.
    const long = "1st Place Regional Qualifier Houston Enormous Event Name That Runs Very Long Indeed";
    const a = withUrl("Master Yi, Wuju Bladesman", `${long} Alpha`, "https://x/meta/a");
    const b = withUrl("Master Yi, Wuju Bladesman", `${long} Beta`, "https://x/meta/b");
    expect(deckSlug(a)).not.toBe(deckSlug(b));
  });
});

describe("pullMetaDecks", () => {
  it("fetches each listed deck and writes it to both the corpus and the gauntlet", async () => {
    const tmp = `/tmp/decks-test-${process.pid}`;
    const fetched: string[] = [];
    const result = await pullMetaDecks({
      delayMs: 0,
      cards: CARDS,
      outputDir: `${tmp}/output`,
      gauntletDir: `${tmp}/gauntlet`,
      now: () => "2026-08-24",
      fetchText: async (url) => {
        fetched.push(url);
        return url.endsWith("/decks") ? `<a href="/meta/aaa"></a>` : page();
      },
    });
    expect(fetched).toEqual(["https://rift-atlas.com/decks", "https://rift-atlas.com/meta/aaa"]);
    expect(result.decks).toHaveLength(1);
    expect(result.decks[0].chosenChampion).toBe("Irelia, Fervent");
    expect(result.written).toHaveLength(2);
    expect(result.quarantined).toEqual([]);
  });

  it("refuses to write a deck whose page did not parse cleanly", async () => {
    // Overwriting a good committed gauntlet deck with a half-rendered one loses
    // data that was correct, and the CLI would still have counted it written.
    const tmp = `/tmp/decks-test-${process.pid}-q`;
    const result = await pullMetaDecks({
      delayMs: 0,
      cards: CARDS,
      outputDir: `${tmp}/output`,
      gauntletDir: `${tmp}/gauntlet`,
      fetchText: async (url) =>
        url.endsWith("/decks")
          ? `<a href="/meta/short"></a>`
          : page({ sections: section("Units", 1, tile("SFD-048", "Stellacorn Herder")) }),
    });
    expect(result.decks).toHaveLength(0);
    expect(result.written).toHaveLength(0);
    expect(result.quarantined[0].reasons.join(" ")).toMatch(/Runes: section not found/);
  });

  it("does not undo a hand-set Chosen Champion on a re-pull", async () => {
    // Five of the 24 pulled decks legally run two champions of the legend's tag,
    // so the champion is filled in by hand. Overwriting it returns those decks
    // to unplayable, and the next CI run is the first anyone hears of it.
    const tmp = `/tmp/decks-test-${process.pid}-keep`;
    const opts = {
      delayMs: 0,
      cards: CARDS,
      outputDir: `${tmp}/output`,
      gauntletDir: `${tmp}/gauntlet`,
      now: () => "2026-08-24",
      fetchText: async (url: string) =>
        url.endsWith("/decks") ? `<a href="/meta/aaa"></a>` : ambiguousPage(),
    };
    const first = await pullMetaDecks(opts);
    expect(first.decks[0].chosenChampion).toBeNull();

    // A maintainer fills it in.
    const file = join(`${tmp}/gauntlet`, `${deckSlug(first.decks[0])}.json`);
    const saved = JSON.parse(readFileSync(file, "utf-8"));
    saved.chosen_champion = "Irelia, Fervent";
    saved.chosen_champion_note = "picked by hand";
    writeFileSync(file, JSON.stringify(saved, null, 1));

    const second = await pullMetaDecks(opts);
    const after = JSON.parse(readFileSync(file, "utf-8"));
    expect(after.chosen_champion).toBe("Irelia, Fervent");
    expect(after.chosen_champion_note).toBe("picked by hand");
    expect(second.warnings.join(" ")).toMatch(/kept the hand-set Chosen Champion/);
  });

  it("keeps going when one deck page fails, and says which", async () => {
    // A pull that aborts on the first bad list leaves the gauntlet half
    // written, which is worse than a gauntlet with a known hole in it.
    const result = await pullMetaDecks({
      delayMs: 0,
      cards: CARDS,
      outputDir: `/tmp/decks-test-${process.pid}-b/output`,
      gauntletDir: `/tmp/decks-test-${process.pid}-b/gauntlet`,
      fetchText: async (url) => {
        if (url.endsWith("/decks")) return `<a href="/meta/ok"></a><a href="/meta/bad"></a>`;
        if (url.endsWith("/bad")) return "<html><body></body></html>";
        return page();
      },
    });
    expect(result.decks).toHaveLength(1);
    expect(result.warnings.some((w) => w.includes("/meta/bad") && w.includes("no legend"))).toBe(true);
  });
});

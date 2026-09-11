import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import {
  RIFTOOLS_CARD_ALIASES,
  isDecklistSitemap,
  parseDecklistSitemap,
  parseRiftoolsDeckPage,
  parseSitemapIndex,
  selectRecentTopLists,
  type RiftoolsEntry,
} from "../riftools.js";

/**
 * Real pages, not hand-written approximations of them.
 *
 * The rift-atlas tests build their HTML in code, and that is fine for a site
 * whose markup this repo has watched for a year. Riftools is new here, and a
 * fixture written from a reading of the page tests the reading rather than the
 * page — which is how a parser passes its suite and fails on the real thing.
 * These are the deck sections as served, byte for byte.
 */
const FIXTURES = join(import.meta.dirname, "fixtures");
const fixture = (name: string) => readFileSync(join(FIXTURES, name), "utf-8");

const ORNN = "https://www.riftools.app/decklists/riftbound-regional-qualifier-barcelona/1-mice-themanland-ornn";
const total = (rows: { qty: number }[]) => rows.reduce((n, c) => n + c.qty, 0);

describe("parseRiftoolsDeckPage", () => {
  it("reads a whole tournament list off a real page", () => {
    const { deck, structural } = parseRiftoolsDeckPage(fixture("riftools-deck.html"), ORNN, "2026-09-11");
    expect(structural).toEqual([]);
    expect(deck.legend).toBe("Ornn, Fire Below the Mountain");
    expect(deck.chosenChampion).toBe("Ornn, Blacksmith");
    expect(total(deck.runes)).toBe(12);
    expect(deck.battlefields.map((b) => b.name)).toEqual([
      "Ornn's Forge",
      "Seat of Power",
      "Veiled Temple",
    ]);
  });

  it("folds the Chosen Champion into the Main Deck, where rule 103.2 puts it", () => {
    // Riftools renders it in a section of its own. Left there, the deck is a
    // 39-card Main Deck — illegal under 103.2 — and the champion is missing
    // from the list `check` looks in for it (103.2.a).
    const { deck } = parseRiftoolsDeckPage(fixture("riftools-deck.html"), ORNN, "2026-09-11");
    expect(total(deck.main)).toBe(40);
    expect(deck.main.map((c) => c.name)).toContain("Ornn, Blacksmith");
  });

  it("leaves the sideboard out — the table plays a game, not a match", () => {
    // The page's Sideboard section is read (its rows count toward the declared
    // total) and then dropped: rule 103 as implemented here has no sideboard,
    // and shuffling those cards in would change every draw.
    const { deck } = parseRiftoolsDeckPage(fixture("riftools-deck.html"), ORNN, "2026-09-11");
    expect(deck.main.map((c) => c.name)).not.toContain("Decree of Focus");
    // This list runs Guardian Angel in BOTH, which is the case that would go
    // unnoticed: folding the sideboard in would leave the name present and only
    // the count wrong, and a 2-of played as a 3-of is a deck nobody registered.
    expect(deck.main.find((c) => c.name === "Guardian Angel")?.qty).toBe(1);
  });

  it("records the event, the placement and the date the list was played", () => {
    // `fetched` is when this repo read the page; a list's age is the age of the
    // EVENT, and a gauntlet that cannot tell those apart cannot say how stale
    // it is.
    const { deck } = parseRiftoolsDeckPage(fixture("riftools-deck.html"), ORNN, "2026-09-11");
    expect(deck.source).toMatchObject({
      site: "riftools.app",
      url: ORNN,
      author: "MICE TheManLand",
      meta: true,
      fetched: "2026-09-11",
      event: "Riftbound Regional Qualifier - Barcelona",
      placement: 1,
      event_date: "2026-08-22",
      event_size: "Premier event",
    });
    expect(deck.name).toBe("MICE TheManLand — #1 — Riftbound Regional Qualifier - Barcelona");
  });

  it("bridges the one name Riftools spells differently from the card pool", () => {
    // Riftcodex carries the Kennen legend as `Yordle, Kennen - Heart of the
    // Tempest`; Riftools writes `Kennen, Heart of the Tempest`, which neither
    // separator variant can reach. 22 of 78 measured lists were that legend, so
    // an unbridged name is a quarter of the meta missing from the gauntlet.
    const { deck } = parseRiftoolsDeckPage(fixture("riftools-deck-kennen.html"), "u", "2026-09-11");
    expect(deck.legend).toBe("Yordle, Kennen - Heart of the Tempest");
    expect(Object.keys(RIFTOOLS_CARD_ALIASES)).toEqual(["kennen, heart of the tempest"]);
  });

  it("says an incomplete SOURCE list is incomplete, not that the layout changed", () => {
    // Riftools publishes genuinely partial records — the Showdown Series pages
    // carry runes, main deck and sideboard and no legend, battlefields or
    // champion at all. Reporting that as a parser problem sends whoever reads
    // the warning to fix code that is working.
    expect(() =>
      parseRiftoolsDeckPage(fixture("riftools-deck-no-legend.html"), "u", "2026-09-11")
    ).toThrow(/records no legend/);
  });

  it("refuses a page with no deck markup at all as a layout change", () => {
    expect(() => parseRiftoolsDeckPage("<html><body></body></html>", "u", "2026-09-11")).toThrow(
      /page layout may have changed/
    );
  });

  it("keeps the specific reason when the legend row itself did not parse", () => {
    // A Legend section that IS there, whose one row was dropped for an
    // unreadable badge, leaves zero legend rows — which looks exactly like the
    // partial-record case above. Reporting it as "the source's list is
    // incomplete" throws away the only sentence saying what to look at.
    const html = fixture("riftools-deck.html").replace(
      '<span class="deck-card-count">1</span><strong>Ornn, Fire Below the Mountain</strong>',
      '<span class="deck-card-count">?</span><strong>Ornn, Fire Below the Mountain</strong>'
    );
    expect(() => parseRiftoolsDeckPage(html, "u", "2026-09-11")).toThrow(
      /legend row did not parse.*unreadable count/
    );
  });

  it("catches a dropped card against the page's own declared total", () => {
    // The page states "66 cards / 30 unique" across every section. That is the
    // one guard that notices a section which rendered short, which is the
    // failure that produces a deck quietly missing three spells.
    const html = fixture("riftools-deck.html").replace(
      /<div class="deck-card-row deck-ssr-card-row"><span><\/span><span class="deck-card-count">3<\/span><strong>Scuttle Crab<\/strong><\/div>/,
      ""
    );
    const { structural } = parseRiftoolsDeckPage(html, "u", "2026-09-11");
    expect(structural.join(" ")).toMatch(/page declares 66 cards, sections total 63/);
  });

  it("catches a section that rendered fewer rows than it claims", () => {
    const html = fixture("riftools-deck.html").replace("<small>17</small>", "<small>19</small>");
    const { structural } = parseRiftoolsDeckPage(html, "u", "2026-09-11");
    expect(structural.join(" ")).toMatch(/Main deck: page declares 19 row\(s\), 17 parsed/);
  });

  it("never invents a quantity from an unreadable count", () => {
    // rift-atlas omits the badge for singletons, so there an absent badge means
    // one copy. Riftools always renders it, so an unreadable one is a rendering
    // failure — defaulting to 1 would silently shrink a 3-of.
    const html = fixture("riftools-deck.html").replace(
      '<span class="deck-card-count">3</span><strong>Scuttle Crab</strong>',
      '<span class="deck-card-count">many</span><strong>Scuttle Crab</strong>'
    );
    const { deck, structural } = parseRiftoolsDeckPage(html, "u", "2026-09-11");
    expect(deck.main.every((c) => Number.isFinite(c.qty))).toBe(true);
    expect(structural.join(" ")).toMatch(/Scuttle Crab has an unreadable count/);
  });

  it("treats a missing mandatory section as a rendering failure (103.3.a, 103.4.a)", () => {
    const html = fixture("riftools-deck.html").replace(/<h3>Runes\s*<small>2<\/small><\/h3>/, "<h3>Sideboard <small>2</small></h3>");
    const { structural } = parseRiftoolsDeckPage(html, "u", "2026-09-11");
    expect(structural.join(" ")).toMatch(/Runes: section not found/);
  });

  it("adds the champion's copies rather than filing the card twice", () => {
    // A list running two copies of its champion splits them across the two
    // sections. Two entries naming one card is how `deckfile.canonical` ends up
    // counting six legal copies of a three-copy card.
    const html = fixture("riftools-deck.html").replace(
      '<span class="deck-card-count">3</span><strong>Scuttle Crab</strong>',
      '<span class="deck-card-count">3</span><strong>Ornn, Blacksmith</strong>'
    );
    const { deck } = parseRiftoolsDeckPage(html, "u", "2026-09-11");
    const ornn = deck.main.filter((c) => c.name === "Ornn, Blacksmith");
    expect(ornn).toHaveLength(1);
    expect(ornn[0].qty).toBe(4);
  });
});

describe("the sitemap, which is how the crawl stays small", () => {
  it("finds the decklist sub-sitemaps in the real index", () => {
    const locs = parseSitemapIndex(fixture("riftools-sitemap.xml"));
    expect(locs.filter(isDecklistSitemap)).toEqual([
      "https://www.riftools.app/sitemaps/decklists-set3.xml",
      "https://www.riftools.app/sitemaps/decklists-set4.xml",
    ]);
    // `core.xml` is marketing pages; fetching it would be pure noise.
    expect(locs.filter(isDecklistSitemap)).not.toContain("https://www.riftools.app/sitemaps/core.xml");
  });

  it("refuses an index it cannot read rather than reporting an empty site", () => {
    expect(() => parseSitemapIndex("<html>not a sitemap</html>")).toThrow(/no <sitemap> entries/);
    expect(() => parseDecklistSitemap("<urlset></urlset>")).toThrow(/format may have changed/);
  });

  it("reads the event and the placement out of each decklist URL", () => {
    const entries = parseDecklistSitemap(fixture("riftools-decklists.xml"));
    expect(entries).toHaveLength(16);
    expect(entries[0]).toEqual({
      url: "https://www.riftools.app/decklists/dangguan-animation-expo-tournament/1-gambit-diana",
      event: "dangguan-animation-expo-tournament",
      slug: "1-gambit-diana",
      placement: 1,
      lastmod: "2026-08-08",
    });
    expect(entries.map((e) => e.placement)).not.toContain(null);
  });
});

describe("selectRecentTopLists", () => {
  const entries = parseDecklistSitemap(fixture("riftools-decklists.xml"));

  it("draws from the most recent events, top placings first", () => {
    const picked = selectRecentTopLists(entries, { events: 2, perEvent: 2 });
    expect(picked.map((e) => `${e.event}/${e.placement}`)).toEqual([
      "i-micelion-cup/1",
      "i-micelion-cup/10",
      "dangguan-animation-expo-tournament/1",
      "dangguan-animation-expo-tournament/10",
    ]);
  });

  it("breaks a tie on date by event size, so a 1,280-list open outranks a locals", () => {
    // Both of these are 2026-08-02 in the fixture and both have four lists, so
    // the fixture settles it on the slug — but the size term is what keeps a
    // regional open ahead of an eight-player weekly on the same weekend.
    const small: RiftoolsEntry[] = [
      { url: "u1", event: "tiny-weekly", slug: "1-a", placement: 1, lastmod: "2026-08-02" },
    ];
    const [first] = selectRecentTopLists([...entries, ...small], { events: 3, perEvent: 1 });
    expect(first.event).toBe("i-micelion-cup");
    // Five events exist once `tiny-weekly` is added; asking for four drops the
    // smallest of the two that share the oldest date rather than an arbitrary one.
    const ranked = selectRecentTopLists([...entries, ...small], { events: 4, perEvent: 1 });
    expect(ranked.map((e) => e.event)).not.toContain("tiny-weekly");
  });

  it("is deterministic, so two runs pull the same decks", () => {
    const a = selectRecentTopLists(entries, { events: 3, perEvent: 3 });
    const b = selectRecentTopLists([...entries].reverse(), { events: 3, perEvent: 3 });
    expect(a.map((e) => e.url)).toEqual(b.map((e) => e.url));
  });

  it("honours the hard cap, because 14,700 lists is a census and not a gauntlet", () => {
    expect(selectRecentTopLists(entries, { events: 4, perEvent: 4, limit: 5 })).toHaveLength(5);
  });
});

/**
 * Riftools (riftools.app) — the second decklist source.
 *
 * rift-atlas covers roughly two dozen curated meta decks. Riftools covers
 * *events*: 83 tournaments and 14,755 individual lists at the time of writing,
 * placement by placement, which is what the gauntlet actually wants — the
 * opponent set is supposed to be the current tournament meta, not a tier list.
 *
 * **How this reads the site, and why not the obvious way.** `/tournaments` is
 * the human entry point and it is client-rendered: the HTML ships an empty
 * `#tournament-rows` and fills it from Supabase, so there is nothing structural
 * to parse. The individual decklist pages ARE server-rendered, completely, and
 * `sitemap.xml` is the site's own machine-readable index of them. So the crawl
 * goes sitemap → decklist page, and never touches the site's data API.
 *
 * **Etiquette.** `robots.txt` is `Allow: /` for every agent with no crawl-delay,
 * and there is no `Disallow` to work around. Requests are paced by the caller
 * (see `pullMetaDecks`) and identified by the same User-Agent as the rest of
 * this repo. See docs/content-and-licensing.md.
 *
 * **Blocked sources are not worked around.** Piltover Archive resets scripted
 * connections and riftdecks.com refuses them; both are recorded in `decks.ts`
 * and neither is fetched from here.
 *
 * The parse is structural in the same sense as `decks.ts`: sections are found
 * by heading text, rows by their class, and the page's own declared totals are
 * checked against what was parsed — so a layout change or a half-rendered page
 * fails loudly instead of producing a deck that is quietly missing its spells.
 */
import { JSDOM } from "jsdom";
import type { DeckCard, ParsedDeck } from "./decks.js";

export const RIFTOOLS_SITE = "riftools.app";
export const RIFTOOLS_SITEMAP = "https://www.riftools.app/sitemap.xml";

/** The sections a decklist page renders, in the order it renders them. */
const LEGEND_SECTION = "Legend";
const CHAMPION_SECTION = "Chosen Champion";
const MAIN_SECTION = "Main deck";
const RUNES_SECTION = "Runes";
const BATTLEFIELDS_SECTION = "Battlefields";
/**
 * Parsed and then dropped. The table plays a single game, never a match, so
 * rule 103 as implemented here has no sideboard to check and the deck file has
 * no field to put one in. It is still read, because its rows count toward the
 * page's declared card total and ignoring them would make that check fail on
 * every deck that brought one.
 */
const SIDEBOARD_SECTION = "Sideboard";

/**
 * Cards Riftools spells differently from this repo's card pool.
 *
 * Measured, not guessed: over 78 pulled lists exactly one name failed to
 * resolve, and it failed on 22 of them. Riftcodex carries the Kennen legend as
 * `Yordle, Kennen - Heart of the Tempest` — the champion's own name is
 * "Yordle, Kennen" — and Riftools writes it `Kennen, Heart of the Tempest`, so
 * neither of the two separator variants `lookupCard` tries can bridge it.
 *
 * This is a table rather than a looser match on purpose. A rule like "fall back
 * to the subtitle" would resolve this one and, on the next set, silently bind
 * some other list to a card it never named — which is the failure the whole
 * lookup path is built to refuse. A name absent from here quarantines its deck
 * and prints itself, so the next one arrives as a decision, not a defect.
 *
 * The value is the pool's own spelling of the card, which is also the spelling
 * the committed rift-atlas decks use, so one legend has one name across the
 * whole gauntlet.
 */
export const RIFTOOLS_CARD_ALIASES: Record<string, string> = {
  "kennen, heart of the tempest": "Yordle, Kennen - Heart of the Tempest",
};

function aliased(name: string): string {
  return RIFTOOLS_CARD_ALIASES[name.trim().toLowerCase()] ?? name;
}

function textOf(el: Element | null): string {
  return (el?.textContent ?? "").replace(/\s+/g, " ").trim();
}

/**
 * A section's heading without its row-count badge.
 *
 * `<h3>Main deck <small>17</small></h3>` reads as "Main deck 17" through
 * `textContent`, so the badge is removed rather than matched around — a prefix
 * match would fold a hypothetical "Main deck (sideboarded)" into the Main Deck
 * and an exact match on the raw text would find nothing at all.
 */
function headingOf(section: Element): string {
  const h3 = section.querySelector("h3");
  if (!h3) return "";
  const badge = textOf(h3.querySelector("small"));
  const full = textOf(h3);
  return (badge && full.endsWith(badge) ? full.slice(0, -badge.length) : full).trim();
}

/** The first integer in a badge, or null when there is not one. */
function readCount(text: string): number | null {
  const digits = /\d+/.exec(text);
  if (!digits) return null;
  const n = Number.parseInt(digits[0], 10);
  return Number.isFinite(n) && n > 0 ? n : null;
}

interface Section {
  heading: string;
  rows: DeckCard[];
  /** Rows the page says it rendered, from the `<small>` badge. */
  declaredRows: number | null;
  warnings: string[];
}

/**
 * Every `deck-group` section on the page, parsed once.
 *
 * Riftools always renders the count span, even for a singleton — unlike
 * rift-atlas, where an absent badge means one copy. So an unreadable count here
 * is a rendering failure and is reported, never defaulted to 1: a deck that
 * quietly gains or loses copies plays differently in every game.
 */
function readSections(doc: Document): Section[] {
  const out: Section[] = [];
  for (const section of doc.querySelectorAll("section.deck-group")) {
    const heading = headingOf(section);
    const rows: DeckCard[] = [];
    const warnings: string[] = [];
    for (const row of section.querySelectorAll(".deck-card-row")) {
      const name = textOf(row.querySelector("strong"));
      const badge = textOf(row.querySelector(".deck-card-count"));
      const qty = readCount(badge);
      if (!name) {
        warnings.push(`${heading}: a row rendered with no card name`);
        continue;
      }
      if (qty === null) {
        warnings.push(`${heading}: ${name} has an unreadable count ${JSON.stringify(badge)}`);
        continue;
      }
      rows.push({ name: aliased(name), qty });
    }
    const declaredRows = readCount(textOf(section.querySelector("h3 small")));
    if (declaredRows !== null && declaredRows !== rows.length) {
      warnings.push(`${heading}: page declares ${declaredRows} row(s), ${rows.length} parsed`);
    }
    out.push({ heading, rows, declaredRows, warnings });
  }
  return out;
}

/** The `<dt>/<dd>` facts strip: Set, Event size, Runes, Cards, Date. */
function readFacts(doc: Document): Record<string, string> {
  const facts: Record<string, string> = {};
  for (const pair of doc.querySelectorAll(".deck-summary-facts div")) {
    const key = textOf(pair.querySelector("dt"));
    const value = textOf(pair.querySelector("dd"));
    if (key) facts[key] = value;
  }
  return facts;
}

/** `66 cards / 30 unique` → 66. The page's own total, for cross-checking. */
export function declaredCardTotal(facts: Record<string, string>): number | null {
  const m = /(\d+)\s*cards?/i.exec(facts["Cards"] ?? "");
  return m ? Number.parseInt(m[1], 10) : null;
}

/**
 * Merge rows that name the same card, keeping first-seen order.
 *
 * The Chosen Champion is rendered in its own section and is a Main Deck card
 * for construction purposes (103.2), so it has to be folded back in. A list
 * running more than one copy of its champion splits them across the two
 * sections, and adding the sections without merging would file the same card
 * twice — which `deckfile.canonical` then counts as six legal copies of a
 * three-copy card.
 */
function mergeRows(rows: DeckCard[]): DeckCard[] {
  const out: DeckCard[] = [];
  const at = new Map<string, number>();
  for (const row of rows) {
    const seen = at.get(row.name);
    if (seen === undefined) {
      at.set(row.name, out.length);
      out.push({ ...row });
    } else {
      out[seen].qty += row.qty;
    }
  }
  return out;
}

const total = (rows: DeckCard[]) => rows.reduce((n, c) => n + c.qty, 0);

/**
 * One Riftools decklist page.
 *
 * Throws when the page carries no legend at all, exactly as the rift-atlas
 * parser does: a deck with no legend has no Domain Identity (103.1.b) and
 * nothing downstream can do anything with it.
 */
export function parseRiftoolsDeckPage(html: string, url: string, fetched: string): ParsedDeck {
  const doc = new JSDOM(html).window.document;
  const sections = readSections(doc);
  const facts = readFacts(doc);
  const structural: string[] = [];
  for (const s of sections) structural.push(...s.warnings);

  const find = (heading: string) => sections.filter((s) => s.heading === heading);
  const one = (heading: string): Section | undefined => {
    const found = find(heading);
    if (found.length > 1) structural.push(`${heading}: ${found.length} sections share this heading`);
    return found[0];
  };

  const legendSection = one(LEGEND_SECTION);
  const legend = legendSection?.rows[0]?.name ?? "";
  if (!legend) {
    // Three different failures, and conflating them sends the reader to the
    // wrong place. Riftools publishes genuinely partial records — the Showdown
    // Series lists carry runes, main deck and sideboard and no legend,
    // battlefields or champion at all — and that is the source's data, not this
    // parser's bug. But a Legend section that IS there and whose one row was
    // dropped for an unreadable count badge is a third thing again, and the
    // specific reason has already been worked out: reporting it as "the source's
    // list is incomplete" throws away the only sentence that says what to look
    // at.
    const why = legendSection?.warnings ?? [];
    throw new Error(
      why.length
        ? `the legend row did not parse — ${why.join("; ")}: ${url}`
        : sections.length
          ? `the page records no legend (103.1) — the source's list is incomplete: ${url}`
          : `no legend found — page layout may have changed: ${url}`
    );
  }
  if ((legendSection?.rows.length ?? 0) > 1) {
    structural.push(`${LEGEND_SECTION}: ${legendSection?.rows.length} legends listed, only one is legal (103.1)`);
  }

  const mainSection = one(MAIN_SECTION);
  const championSection = one(CHAMPION_SECTION);
  const runeSection = one(RUNES_SECTION);
  const bfSection = one(BATTLEFIELDS_SECTION);
  const sideboard = one(SIDEBOARD_SECTION);

  // Runes and Battlefields are mandatory in every legal list (103.3.a, 103.4.a)
  // and the Main Deck obviously is, so an absent section is a rendering failure
  // rather than a property of the deck. A sideboard is genuinely optional.
  for (const [heading, section] of [
    [MAIN_SECTION, mainSection],
    [RUNES_SECTION, runeSection],
    [BATTLEFIELDS_SECTION, bfSection],
  ] as const) {
    if (!section) structural.push(`${heading}: section not found on the page`);
  }

  const championRows = championSection?.rows ?? [];
  if (championRows.length > 1) {
    structural.push(`${CHAMPION_SECTION}: ${championRows.length} champions listed, only one is legal (103.2.a.1)`);
  }
  const main = mergeRows([...(mainSection?.rows ?? []), ...championRows]);

  // The page states how many cards the list holds across every section it
  // rendered. Checking the parse against it is the one guard that catches a
  // section that rendered empty, or a row shape this parser has not met.
  const declared = declaredCardTotal(facts);
  const parsedTotal =
    total(legendSection?.rows ?? []) +
    total(mainSection?.rows ?? []) +
    total(championRows) +
    total(runeSection?.rows ?? []) +
    total(bfSection?.rows ?? []) +
    total(sideboard?.rows ?? []);
  if (declared === null) {
    structural.push("no declared card total to check the parse against");
  } else if (declared !== parsedTotal) {
    structural.push(`page declares ${declared} cards, sections total ${parsedTotal}`);
  }

  const placementText = textOf(doc.querySelector(".deck-summary-result span"));
  const placement = readCount(placementText);
  const event = textOf(doc.querySelectorAll(".deck-summary-subtitle span")[1]) || undefined;
  const author = textOf(doc.querySelector(".deck-summary-result strong")) || undefined;

  const deck = {
    name: [author, placement ? `#${placement}` : null, event].filter(Boolean).join(" — ") || "untitled",
    legend,
    chosenChampion: championRows.length === 1 ? championRows[0].name : null,
    // Filled from the legend's own card entry by the puller (103.1.b); the page
    // states the deck's RUNE domains, which is a different thing.
    domains: [] as string[],
    main,
    runes: runeSection?.rows ?? [],
    battlefields: bfSection?.rows ?? [],
    source: {
      site: RIFTOOLS_SITE,
      url,
      author,
      // Every page under /decklists/ is a recorded tournament result.
      meta: true,
      fetched,
      event,
      placement: placement ?? undefined,
      event_date: facts["Date"] || undefined,
      event_size: facts["Event size"] || undefined,
    },
  };

  return { deck, warnings: [...structural], structural };
}

/** One decklist URL as the sitemap lists it, with what its path encodes. */
export interface RiftoolsEntry {
  url: string;
  /** Event slug — the first path segment under `/decklists/`. */
  event: string;
  /** `1-gorica-akali` — placement, player and legend, as the site slugs them. */
  slug: string;
  /** Leading integer of the slug: the player's finish. Null when unslugged. */
  placement: number | null;
  lastmod: string;
}

/** Sub-sitemaps listed by the sitemap index, in the order they appear. */
export function parseSitemapIndex(xml: string): string[] {
  const locs = [...xml.matchAll(/<sitemap>\s*<loc>([^<]+)<\/loc>/g)].map((m) => m[1].trim());
  if (!locs.length) throw new Error("sitemap index listed no <sitemap> entries");
  return locs;
}

/** True for the sub-sitemaps that hold decklists rather than marketing pages. */
export function isDecklistSitemap(url: string): boolean {
  return /\/sitemaps\/decklists/.test(url);
}

/**
 * Decklist entries from one sub-sitemap.
 *
 * Read with a regex rather than a DOM: these files are 2MB of a fixed, flat
 * shape, and the only thing a parser could add is a way to be slower. Zero
 * matches throws, so a format change is not mistaken for an empty sitemap.
 */
export function parseDecklistSitemap(xml: string): RiftoolsEntry[] {
  const out: RiftoolsEntry[] = [];
  for (const m of xml.matchAll(/<loc>([^<]+)<\/loc>\s*<lastmod>([^<]+)<\/lastmod>/g)) {
    const url = m[1].trim();
    const path = url.split("/decklists/")[1];
    if (!path) continue;
    const [event, slug] = path.replace(/\/+$/, "").split("/");
    if (!event || !slug) continue;
    const place = /^(\d+)-/.exec(slug);
    out.push({
      url,
      event,
      slug,
      placement: place ? Number.parseInt(place[1], 10) : null,
      lastmod: m[2].trim(),
    });
  }
  if (!out.length) throw new Error("no decklist <url> entries — the sitemap format may have changed");
  return out;
}

export interface SelectOptions {
  /** How many events to draw from, most recent first. */
  events?: number;
  /** Top placings taken from each event. */
  perEvent?: number;
  /** Hard cap on URLs returned. */
  limit?: number;
}

/**
 * The lists worth pulling: top finishes at the newest, largest events.
 *
 * Fourteen thousand lists is not a gauntlet, it is a census, and fetching them
 * would be both useless and rude. What the engine plan asks for is the *current
 * tournament meta*, so events are ranked by recency first and by how many lists
 * they recorded second — a 1,280-list regional open says more about the meta
 * than a 8-player locals on the same weekend — and within an event the top
 * placings are taken, because those are the lists that beat the field.
 *
 * Ordering is total and deterministic (date, size, slug; then placement, slug)
 * so two runs over the same sitemap pull the same decks.
 */
export function selectRecentTopLists(entries: RiftoolsEntry[], opts: SelectOptions = {}): RiftoolsEntry[] {
  const byEvent = new Map<string, RiftoolsEntry[]>();
  for (const entry of entries) {
    const bucket = byEvent.get(entry.event);
    if (bucket) bucket.push(entry);
    else byEvent.set(entry.event, [entry]);
  }

  const ranked = [...byEvent.entries()]
    .map(([event, lists]) => ({
      event,
      lists,
      date: lists.reduce((latest, e) => (e.lastmod > latest ? e.lastmod : latest), ""),
    }))
    .sort((a, b) =>
      b.date.localeCompare(a.date) || b.lists.length - a.lists.length || a.event.localeCompare(b.event)
    )
    .slice(0, opts.events ?? 12);

  const picked: RiftoolsEntry[] = [];
  for (const { lists } of ranked) {
    const top = [...lists]
      .sort(
        (a, b) =>
          (a.placement ?? Number.MAX_SAFE_INTEGER) - (b.placement ?? Number.MAX_SAFE_INTEGER) ||
          a.slug.localeCompare(b.slug)
      )
      .slice(0, opts.perEvent ?? 4);
    picked.push(...top);
  }
  return picked.slice(0, opts.limit ?? Infinity);
}

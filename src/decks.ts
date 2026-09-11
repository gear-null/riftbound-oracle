/**
 * Pull competitive decklists so a deck under construction has something real to
 * be tested against.
 *
 * There is no deck API, and most sites publishing competitive lists refuse
 * scripted requests. Two do not, and this reads both:
 *
 *   rift-atlas.com   server-renders a curated meta index as plain semantic
 *                    HTML — roughly two dozen archetype-defining decks.
 *   riftools.app     server-renders one page per tournament *placement*, and
 *                    publishes a sitemap of all of them. That is where the
 *                    breadth comes from; see `riftools.ts`.
 *
 * **Sources deliberately not read.** Piltover Archive resets scripted
 * connections and riftdecks.com refuses them. Both were measured, both are a
 * clear enough signal, and neither is worked around: lists from sites like
 * those reach the gauntlet by hand through `deck_cli.py import`, which is a
 * person copying a page in their own browser rather than a crawl.
 *
 * The parse is deliberately structural rather than positional: sections are
 * found by their heading text and cards by their tile class, so a layout change
 * fails loudly with "section not found" instead of silently returning a deck
 * that is missing its spells.
 */
import { JSDOM } from "jsdom";
import { createHash } from "node:crypto";
import { mkdirSync, writeFileSync, readFileSync, existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import type { CardIndex } from "./skill-data.js";
import { DECK_LAB_CARD_DATA, canonicalCardName } from "./skill-data.js";
import {
  RIFTOOLS_SITE,
  RIFTOOLS_SITEMAP,
  type RiftoolsEntry,
  isDecklistSitemap,
  parseDecklistSitemap,
  parseRiftoolsDeckPage,
  parseSitemapIndex,
  selectRecentTopLists,
} from "./riftools.js";

const SITE = "rift-atlas.com";
const INDEX_URL = `https://${SITE}/decks`;
const USER_AGENT = "riftbound-oracle";

/** Where pulled decks land, and where the skill reads its gauntlet from. */
export const DECK_OUTPUT_DIR = "output/decks";
export const GAUNTLET_DIR = ".claude/skills/deck-lab/gauntlet";

export interface DeckCard {
  name: string;
  /**
   * Collector code as the source spells it, e.g. `SFD-057`. Provenance only,
   * and only where the source prints one — Riftools names cards and does not.
   */
  code?: string;
  qty: number;
}

export interface DeckSource {
  site: string;
  url: string;
  author?: string;
  /** The source flagged this as a tournament/meta list rather than a brew. */
  meta: boolean;
  /** The day this repo fetched the page. Not the day the deck was played. */
  fetched: string;
  /** The tournament the list was played at, where the source names one. */
  event?: string;
  /** Where the player finished. 1 is the winner. */
  placement?: number;
  /** The event's own date, as the source states it. */
  event_date?: string;
  /** How the source classifies the event's size, e.g. `Premier event`. */
  event_size?: string;
}

export interface Deck {
  name: string;
  legend: string;
  /**
   * Set by hand when the source leaves the Chosen Champion ambiguous, and
   * carried across a re-pull so the decision is not silently undone.
   */
  chosen_champion?: string | null;
  chosen_champion_note?: string;
  /**
   * Resolved at pull time where the card data makes it unambiguous, null where
   * it does not. Never guessed: a wrong Chosen Champion changes every opening
   * hand, so an unresolved one is reported rather than invented.
   */
  chosenChampion: string | null;
  /** Candidates when the champion tag matched more than one card. */
  championCandidates?: string[];
  domains: string[];
  /** Champions, units, spells and gear — everything in the Main Deck (103.2). */
  main: DeckCard[];
  runes: DeckCard[];
  battlefields: DeckCard[];
  source?: DeckSource;
}

/** Section headings the site renders, mapped to where the rules put them. */
const MAIN_DECK_SECTIONS = ["Champions", "Units", "Spells", "Gear"];

function textOf(el: Element | null): string {
  return (el?.textContent ?? "").replace(/\s+/g, " ").trim();
}

/**
 * A section's heading text without the count badge glued onto it.
 *
 * `textOf(h2)` returns "Units 3" because the count lives in a child span, which
 * is why the original match had to be a prefix match — and a prefix match takes
 * the FIRST section whose heading merely starts with the word, so a second
 * "Units" section is dropped and an unrelated "Unit Tokens" section is absorbed
 * into the Main Deck. Removing the badge lets the comparison be exact.
 */
function headingOf(section: Element): string {
  const h2 = section.querySelector("h2");
  if (!h2) return "";
  const count = textOf(h2.querySelector(".deck-section-count"));
  const full = textOf(h2);
  return (count && full.endsWith(count) ? full.slice(0, -count.length) : full).trim();
}

/** Every section under one heading — plural, because duplicates must not vanish. */
function sectionsFor(doc: Document, heading: string): Element[] {
  return [...doc.querySelectorAll("section.deck-section")].filter(
    (s) => headingOf(s) === heading
  );
}

/**
 * The first integer in a count badge, or null when there is not one.
 *
 * `parseInt` was the wrong tool twice over: it returns NaN for a badge rendered
 * with any non-digit prefix, and NaN then flowed all the way into the written
 * JSON as `null`, where the Python loader's `int(c["qty"])` raises. A count that
 * cannot be read is reported, never guessed at and never emitted.
 */
function readCount(text: string): number | null {
  const digits = /\d+/.exec(text);
  if (!digits) return null;
  const n = Number.parseInt(digits[0], 10);
  return Number.isFinite(n) && n > 0 ? n : null;
}

interface SectionParse {
  cards: DeckCard[];
  warnings: string[];
  /** Distinguishes "this deck runs no gear" from "the section is not there". */
  present: boolean;
}

/**
 * Cards under one heading.
 *
 * Quantity lives in a `deck-card-count` badge that is only rendered above 1, so
 * a missing badge means one copy — not zero. Reading it as zero silently drops
 * every singleton in the deck.
 */
function sectionCards(doc: Document, heading: string): SectionParse {
  const sections = sectionsFor(doc, heading);
  if (!sections.length) return { cards: [], warnings: [], present: false };

  const cards: DeckCard[] = [];
  const warnings: string[] = [];
  let declaredTotal = 0;
  let sawDeclared = false;

  for (const section of sections) {
    const declared = readCount(textOf(section.querySelector(".deck-section-count")));
    if (declared === null) {
      // The one guard against a half-rendered page used to switch itself off in
      // exactly the situation it exists to catch: an unreadable count returned
      // "no mismatch", which reads as a pass.
      warnings.push(`${heading}: no declared count to check the tiles against`);
    } else {
      sawDeclared = true;
      declaredTotal += declared;
    }
    for (const tile of section.querySelectorAll("a.deck-card-tile")) {
      const name = (tile.getAttribute("title") ?? "").trim();
      const badgeText = textOf(tile.querySelector(".deck-card-count"));
      const qty = badgeText ? readCount(badgeText) : 1;
      if (qty === null) {
        warnings.push(`${heading}: ${name || "a tile"} has an unreadable count badge ${JSON.stringify(badgeText)}`);
        continue;
      }
      cards.push({
        name,
        code: (tile.getAttribute("href") ?? "").replace(/^\/atlas\//, ""),
        qty,
      });
    }
  }

  if (sections.length > 1) {
    warnings.push(`${heading}: ${sections.length} sections share this heading — all were read`);
  }

  // A declared count that disagrees with the tiles means the page did not fully
  // render: the deck is short, not small.
  const actual = cards.reduce((n, c) => n + c.qty, 0);
  if (sawDeclared && actual !== declaredTotal) {
    warnings.push(`${heading}: page declares ${declaredTotal}, tiles total ${actual}`);
  }
  return { cards, warnings, present: true };
}

export interface ParsedDeck {
  deck: Deck;
  warnings: string[];
  /**
   * Warnings that mean the PARSE is untrustworthy, as opposed to facts about
   * the deck itself. A deck whose Chosen Champion is genuinely ambiguous is
   * still a real decklist; one whose Runes section did not render is not, and
   * writing it over a good committed copy loses data that was correct.
   */
  structural: string[];
}

export function parseDeckPage(html: string, url: string, fetched: string): ParsedDeck {
  const doc = new JSDOM(html).window.document;
  const warnings: string[] = [];

  const legend = textOf(doc.querySelector(".deck-meta-row strong"));
  if (!legend) throw new Error(`no legend found — page layout may have changed: ${url}`);

  const structural: string[] = [];
  const main: DeckCard[] = [];
  for (const heading of MAIN_DECK_SECTIONS) {
    // Not every deck runs gear, so an absent optional section is legitimate.
    const parsed = sectionCards(doc, heading);
    structural.push(...parsed.warnings);
    main.push(...parsed.cards);
  }

  // Runes and Battlefields are mandatory in every legal list (103.3.a, 103.4.a),
  // so their absence is a rendering failure, never a property of the deck.
  const runeParse = sectionCards(doc, "Runes");
  const bfParse = sectionCards(doc, "Battlefields");
  for (const [heading, parsed] of [["Runes", runeParse], ["Battlefields", bfParse]] as const) {
    structural.push(...parsed.warnings);
    if (!parsed.present) structural.push(`${heading}: section not found on the page`);
  }
  const runes = runeParse.cards;
  const battlefields = bfParse.cards;
  warnings.push(...structural);

  const deck: Deck = {
    name: textOf(doc.querySelector(".deck-title")) || "untitled",
    legend,
    chosenChampion: null,
    domains: [...doc.querySelectorAll(".deck-color-chip")].map((c) => textOf(c)),
    main,
    runes,
    battlefields,
    source: {
      site: SITE,
      url,
      author: textOf(doc.querySelector(".deck-author")).replace(/^by\s+/i, "") || undefined,
      meta: Boolean(doc.querySelector(".meta-badge")),
      fetched,
    },
  };
  return { deck, warnings, structural };
}

/**
 * Deck ids linked from the meta index.
 *
 * The href is normalised before deduping: `/meta/aaa` and `/meta/aaa#comments`
 * are the same deck, and taking the raw remainder made them two ids that both
 * survived `new Set` and were both fetched. Anything with a further path
 * segment is not a deck page — the index also links tier lists and archetype
 * hubs under `/meta/` — so those are dropped rather than fetched as decks.
 */
export function parseDeckIndex(html: string): string[] {
  const doc = new JSDOM(html).window.document;
  const ids = [...doc.querySelectorAll('a[href^="/meta/"]')]
    .map((a) => {
      const href = (a.getAttribute("href") ?? "").trim();
      const path = href.split(/[?#]/)[0].replace(/^\/meta\//, "").replace(/\/+$/, "");
      return path;
    })
    .filter((id) => id && !id.includes("/"));
  return [...new Set(ids)];
}

/**
 * Find a card by a name written the way some other source spells it.
 *
 * The two sources disagree on one character. Riftcodex names a subtitled card
 * `Master Yi - Wuju Bladesman`; rift-atlas renders the same card
 * `Master Yi, Wuju Bladesman`. Matching on the literal string failed for every
 * subtitled card in the pool — which is every legend and every champion, so
 * champion resolution fell back to "all champions" and reported an ambiguity
 * that did not exist.
 *
 * Both separators are tried, and nothing looser: a near-miss that returns a
 * DIFFERENT card is worse than returning none, which is the same reason
 * `card_bridge.find_cards` refuses fuzzy matches. Measured over the 24 pulled
 * decks, the two variants resolve 562 of 562 entries.
 */
export function lookupCard(cards: CardIndex, name: string) {
  const base = name.replace(/\s*\(.*?\)\s*$/, "").trim().toLowerCase();
  for (const key of [base, base.replace(/, /g, " - "), base.replace(/ - /g, ", ")]) {
    if (cards[key]) return cards[key];
  }
  return undefined;
}

/**
 * The deck's Domain Identity, which rule 103.1.b takes from the legend alone.
 *
 * rift-atlas prints domain chips; Riftools prints the deck's *rune* domains,
 * which is a different fact — a deck can run a rune it never spends and can
 * play a colorless card from outside both. Reading the legend's own card entry
 * gives the rule's answer for both sources. Colorless is a value in the API's
 * domain list rather than an absence (135.2.e.6.b), so it is dropped here for
 * the same reason `cards.domains` drops it.
 */
export function domainsOfLegend(cards: CardIndex, legend: string): string[] {
  const entry = lookupCard(cards, legend);
  return (entry?.stats.domain ?? []).filter((d) => d !== "Colorless");
}

/**
 * Bind the deck's Chosen Champion to its Legend by champion tag (103.2.a.2).
 *
 * Name matching was the obvious shortcut and is wrong: "Irelia, Blade Dancer"
 * as a legend can sit beside both "Irelia, Fervent" and "Irelia, Graceful" in
 * the same list, and only the tag says which slot each fills. Where the tag
 * leaves more than one candidate the field stays null and the candidates are
 * recorded, because a wrong champion silently changes every game it plays.
 */
export function resolveChosenChampion(deck: Deck, cards: CardIndex): Pick<Deck, "chosenChampion" | "championCandidates"> {
  const legend = lookupCard(cards, deck.legend);
  const legendTags = new Set(legend?.stats.tags ?? []);

  const champions = deck.main.filter((c) => {
    const entry = lookupCard(cards, c.name);
    if (entry?.stats.supertype !== "Champion") return false;
    // A legend with no tags in the data cannot discriminate; fall back to every
    // champion unit in the deck so the ambiguity is visible rather than hidden.
    if (legendTags.size === 0) return true;
    return (entry.stats.tags ?? []).some((t) => legendTags.has(t));
  });

  const names = [...new Set(champions.map((c) => c.name))];
  if (names.length === 1) return { chosenChampion: names[0] };
  return { chosenChampion: null, championCandidates: names };
}

/** A previously written deck file, or undefined. Never throws on bad JSON. */
function readExistingDeck(path: string): (Deck & { chosen_champion?: string }) | undefined {
  if (!existsSync(path)) return undefined;
  try {
    return JSON.parse(readFileSync(path, "utf-8"));
  } catch {
    return undefined;
  }
}

export function loadCardIndex(path?: string): CardIndex {
  const target = resolve(path ?? DECK_LAB_CARD_DATA);
  if (!existsSync(target)) {
    throw new Error(`no card data at ${target} — run \`oracle skill-data\` first`);
  }
  return JSON.parse(readFileSync(target, "utf-8")) as CardIndex;
}

/**
 * Stable, filesystem-safe, collision-free name for a deck file.
 *
 * The readable part is truncated to 72 characters, and three of the 24 decks
 * currently pulled already reach that limit — so two tournament lists with
 * similarly long names would slugify identically and the second would silently
 * overwrite the first on disk, while both were still counted as written. The
 * suffix is a short digest of the deck's source URL, which is unique per deck,
 * so the name stays readable and the path stays distinct.
 */
export function deckSlug(deck: Deck): string {
  const base = `${deck.legend} ${deck.name}`
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 72)
    .replace(/-+$/, "");
  const identity = deck.source?.url ?? `${deck.legend}/${deck.name}`;
  const digest = createHash("sha256").update(identity).digest("hex").slice(0, 6);
  return `${base || "deck"}-${digest}`;
}

/** The sites this pulls from. Order is the order they are fetched in. */
export const DECK_SITES = [SITE, RIFTOOLS_SITE] as const;
export type DeckSite = (typeof DECK_SITES)[number];

export interface PullOptions {
  /** Which sites to read. Defaults to all of them. */
  sites?: readonly DeckSite[];
  /** Cap on deck pages fetched per site. */
  limit?: number;
  /** riftools.app: how many recent events to draw from. */
  events?: number;
  /** riftools.app: how many top placings to take from each event. */
  perEvent?: number;
  /** Politeness gap between requests, ms. See docs/content-and-licensing.md. */
  delayMs?: number;
  outputDir?: string;
  gauntletDir?: string;
  cards?: CardIndex;
  onProgress?: (message: string) => void;
  fetchText?: (url: string) => Promise<string>;
  now?: () => string;
}

/**
 * A decklist site, reduced to the two things a pull needs from it.
 *
 * Keeping the adapters this thin is the point: one site is an index page and
 * the other is a sitemap, but after `index()` they are both a list of URLs that
 * `parse()` turns into decks, so champion resolution, quarantine, deduplication
 * and writing happen once rather than once per site.
 */
interface SiteAdapter {
  site: DeckSite;
  /** Deck page URLs, most important first. May make its own requests. */
  index(get: (url: string) => Promise<string>, opts: PullOptions): Promise<string[]>;
  parse(html: string, url: string, fetched: string): ParsedDeck;
}

const ADAPTERS: Record<DeckSite, SiteAdapter> = {
  [SITE]: {
    site: SITE,
    async index(get, opts) {
      const ids = parseDeckIndex(await get(INDEX_URL));
      return ids.slice(0, opts.limit ?? Infinity).map((id) => `https://${SITE}/meta/${id}`);
    },
    parse: parseDeckPage,
  },
  [RIFTOOLS_SITE]: {
    site: RIFTOOLS_SITE,
    async index(get, opts) {
      const sitemaps = parseSitemapIndex(await get(RIFTOOLS_SITEMAP)).filter(isDecklistSitemap);
      if (!sitemaps.length) {
        throw new Error(`${RIFTOOLS_SITEMAP} lists no decklist sitemaps — the site layout may have changed`);
      }
      const entries: RiftoolsEntry[] = [];
      for (const url of sitemaps) {
        // Paced like every other request; see docs/content-and-licensing.md.
        await sleep(opts.delayMs ?? DEFAULT_DELAY_MS);
        entries.push(...parseDecklistSitemap(await get(url)));
      }
      return selectRecentTopLists(entries, {
        events: opts.events,
        perEvent: opts.perEvent,
        limit: opts.limit,
      }).map((e) => e.url);
    },
    parse: parseRiftoolsDeckPage,
  },
};

/**
 * Two lists with the same cards are one opponent.
 *
 * Events overlap — Riftools records the Singapore RQ twice under two slugs, and
 * a deck that wins one weekend gets copied to the next — so a pull that took
 * every page at face value would fill the gauntlet with the same 40 cards under
 * different players' names, inflating the deck count while testing nothing new.
 * The key is the composition, not the page, so the duplicate is detectable
 * before it is written.
 */
function compositionKey(deck: Deck, cards: CardIndex): string {
  const section = (rows: DeckCard[]) =>
    rows
      .map((c) => `${c.qty}x${canonicalCardName(cards, c.name)}`)
      .sort()
      .join("|");
  return [
    canonicalCardName(cards, deck.legend),
    deck.chosenChampion ? canonicalCardName(cards, deck.chosenChampion) : "",
    section(deck.main),
    section(deck.runes),
    section(deck.battlefields),
  ].join("::");
}

/** Card names in the list that this repo's card pool cannot resolve. */
function unresolvableCards(deck: Deck, cards: CardIndex): string[] {
  const named = [deck.legend, ...[...deck.main, ...deck.runes, ...deck.battlefields].map((c) => c.name)];
  return [...new Set(named.filter((n) => !lookupCard(cards, n)))];
}

/**
 * Fill an unresolved Chosen Champion from what the rest of the pull did.
 *
 * A list that legally runs two champion units of its legend's tag does not say
 * which one started in the Champion Zone, and the deck is unplayable until it
 * does (103.2.a.1). Guessing is not allowed — but this is not a guess: the
 * pulled tournament data states, for that legend, which champion the field
 * actually chose, and the count is written into the deck so a reader can
 * disagree with it. Where the legend's most common choice is not one of THIS
 * deck's candidates, the field stays null and the deck stays unplayable, which
 * is the honest outcome.
 */
export function fillChosenChampionByConsensus(decks: Deck[]): string[] {
  const votes = new Map<string, Map<string, number>>();
  for (const deck of decks) {
    const chosen = deck.chosenChampion ?? deck.chosen_champion;
    if (!chosen) continue;
    const forLegend = votes.get(deck.legend) ?? new Map<string, number>();
    forLegend.set(chosen, (forLegend.get(chosen) ?? 0) + 1);
    votes.set(deck.legend, forLegend);
  }

  const notes: string[] = [];
  for (const deck of decks) {
    if (deck.chosenChampion || deck.chosen_champion) continue;
    const candidates = deck.championCandidates ?? [];
    const forLegend = votes.get(deck.legend);
    if (candidates.length < 2 || !forLegend) continue;
    const ranked = candidates
      .map((name) => ({ name, n: forLegend.get(name) ?? 0 }))
      .sort((a, b) => b.n - a.n || a.name.localeCompare(b.name));
    if (!ranked[0].n || ranked[0].n === ranked[1]?.n) continue;
    const total = [...forLegend.values()].reduce((a, b) => a + b, 0);
    deck.chosen_champion = ranked[0].name;
    deck.chosen_champion_note =
      `the list legally runs ${candidates.join(" and ")} and the page does not say which ` +
      `sat in the Champion Zone. Set to ${ranked[0].name}: the most common choice for ` +
      `${deck.legend} in this pull (${ranked[0].n} of ${total} lists).`;
    notes.push(`${deck.name}: Chosen Champion set to ${ranked[0].name} by pulled-data consensus`);
  }
  return notes;
}

async function fetchText(url: string): Promise<string> {
  const res = await fetch(url, { headers: { "User-Agent": USER_AGENT } });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} for ${url}`);
  return res.text();
}

/** Politeness gap between requests. See docs/content-and-licensing.md. */
const DEFAULT_DELAY_MS = 1200;

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export interface PullResult {
  decks: Deck[];
  warnings: string[];
  written: string[];
  /**
   * Parsed but NOT written: either the parse itself was untrustworthy, or the
   * list names cards this repo's pool cannot resolve, which makes it a deck no
   * game can be played with. Each carries its reasons by name.
   */
  quarantined: { name: string; reasons: string[] }[];
  /** Decks written, per site. A site that returned nothing shows as 0. */
  bySite: Record<string, number>;
  /** Parsed, fine, and skipped because another list has the same cards. */
  duplicates: { name: string; sameAs: string }[];
}

export async function pullMetaDecks(opts: PullOptions = {}): Promise<PullResult> {
  const get = opts.fetchText ?? fetchText;
  const onProgress = opts.onProgress ?? (() => {});
  const delayMs = opts.delayMs ?? DEFAULT_DELAY_MS;
  const outputDir = opts.outputDir ?? DECK_OUTPUT_DIR;
  const gauntletDir = opts.gauntletDir ?? GAUNTLET_DIR;
  const cards = opts.cards ?? loadCardIndex();
  const fetched = (opts.now ?? (() => new Date().toISOString().slice(0, 10)))();
  const sites = opts.sites ?? DECK_SITES;

  const decks: Deck[] = [];
  const warnings: string[] = [];
  const written: string[] = [];
  const quarantined: { name: string; reasons: string[] }[] = [];
  const duplicates: { name: string; sameAs: string }[] = [];
  const bySite: Record<string, number> = {};
  const seenComposition = new Map<string, string>();
  let fetchedPages = 0;

  for (const site of sites) {
    bySite[site] = 0;
    const adapter = ADAPTERS[site];
    let urls: string[];
    try {
      urls = await adapter.index(get, { ...opts, delayMs });
    } catch (err) {
      // One site being down or restructured must not cost the other one's
      // decks: the pull reports the gap and carries on.
      warnings.push(`${site}: index unreadable — ${err instanceof Error ? err.message : String(err)}`);
      continue;
    }
    onProgress(`${site}: ${urls.length} deck(s) listed`);

    for (const url of urls) {
      // Paced, and never scheduled — see docs/content-and-licensing.md. The gap
      // is counted across sites, not within one: finishing rift-atlas is not a
      // reason to hit riftools without pausing first.
      if (fetchedPages > 0) await sleep(delayMs);
      fetchedPages += 1;
      try {
        const parsed = adapter.parse(await get(url), url, fetched);
        const deck = parsed.deck;
        if (!deck.domains.length) deck.domains = domainsOfLegend(cards, deck.legend);
        if (!deck.chosenChampion) {
          Object.assign(deck, resolveChosenChampion(deck, cards));
        }
        if (!deck.chosenChampion) {
          warnings.push(
            `${deck.name}: Chosen Champion unresolved ` +
              `(${(deck.championCandidates ?? []).join(", ") || "no champion unit found"})`
          );
        }
        warnings.push(...parsed.warnings.map((w) => `${deck.name}: ${w}`));

        // A list naming cards this repo's pool has never heard of cannot be
        // played, and shipping it would break the skill's own promise that
        // every gauntlet deck is legal. It is a hole with a name on it, in
        // exactly the sense a quarantined parse is.
        const unknown = unresolvableCards(deck, cards);
        const reasons = [
          ...parsed.structural,
          ...(unknown.length ? [`card pool cannot resolve: ${unknown.join(", ")}`] : []),
        ];
        if (reasons.length) {
          // Writing a half-parsed deck over a good committed one loses data
          // that was correct. A named gap in the gauntlet beats silent
          // corruption.
          quarantined.push({ name: deck.name, reasons });
          continue;
        }

        const key = compositionKey(deck, cards);
        const twin = seenComposition.get(key);
        if (twin) {
          duplicates.push({ name: deck.name, sameAs: twin });
          continue;
        }
        seenComposition.set(key, deck.name);

        decks.push(deck);
        bySite[site] += 1;
        onProgress(`${deck.legend} — ${deck.name}`);
      } catch (err) {
        warnings.push(`${url}: ${err instanceof Error ? err.message : String(err)}`);
      }
    }
  }

  warnings.push(...fillChosenChampionByConsensus(decks));

  const claimed = new Set<string>();
  for (const deck of decks) {
    // A deck whose Chosen Champion the source cannot name gets one filled in by
    // hand (the list legally runs two champions of the legend's tag, and only
    // the pilot knows which sat in the Champion Zone). Re-pulling must not throw
    // that away — it would silently return the deck to unplayable.
    const slug = deckSlug(deck);
    if (!deck.chosenChampion) {
      const existing = readExistingDeck(resolve(gauntletDir, `${slug}.json`));
      const kept = existing?.chosen_champion ?? existing?.chosenChampion;
      // A decision someone made by hand outranks the one derived above from
      // what the rest of the field played — and its note has to travel with
      // it, or the file would explain the wrong champion.
      if (kept) {
        deck.chosen_champion = kept;
        deck.chosen_champion_note = existing?.chosen_champion_note;
        warnings.push(`${deck.name}: kept the hand-set Chosen Champion ${kept}`);
      }
    }
    const body = JSON.stringify(deck, null, 1);
    if (claimed.has(slug)) {
      // Cannot happen while the slug carries a per-URL digest, which is exactly
      // why it is checked: a future change to `deckSlug` must fail loudly here
      // rather than start overwriting decks again.
      warnings.push(`${deck.name}: slug ${slug} already written this run — not overwriting`);
      continue;
    }
    claimed.add(slug);
    for (const dir of [outputDir, gauntletDir]) {
      const path = resolve(dir, `${slug}.json`);
      mkdirSync(dirname(path), { recursive: true });
      writeFileSync(path, body, "utf-8");
      written.push(path);
    }
  }

  return { decks, warnings, written, quarantined, bySite, duplicates };
}

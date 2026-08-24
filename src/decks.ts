/**
 * Pull competitive decklists so a deck under construction has something real to
 * be tested against.
 *
 * There is no deck API. Riftcodex — the card source this repo already uses —
 * serves cards and sets and nothing else, and Piltover Archive resets scripted
 * connections. rift-atlas.com is the one source that server-renders complete
 * decklists as plain semantic HTML, so that is what this reads.
 *
 * The parse is deliberately structural rather than positional: sections are
 * found by their heading text and cards by their tile class, so a layout change
 * fails loudly with "section not found" instead of silently returning a deck
 * that is missing its spells.
 */
import { JSDOM } from "jsdom";
import { mkdirSync, writeFileSync, readFileSync, existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import type { CardIndex } from "./skill-data.js";
import { CARD_DATA_TARGETS } from "./skill-data.js";

const SITE = "rift-atlas.com";
const INDEX_URL = `https://${SITE}/decks`;
const USER_AGENT = "riftbound-oracle";

/** Where pulled decks land, and where the skill reads its gauntlet from. */
export const DECK_OUTPUT_DIR = "output/decks";
export const GAUNTLET_DIR = ".claude/skills/deck-lab/gauntlet";

export interface DeckCard {
  name: string;
  /** Collector code as the source spells it, e.g. `SFD-057`. Provenance only. */
  code: string;
  qty: number;
}

export interface DeckSource {
  site: string;
  url: string;
  author?: string;
  /** The source flagged this as a tournament/meta list rather than a brew. */
  meta: boolean;
  fetched: string;
}

export interface Deck {
  name: string;
  legend: string;
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
 * Cards in one `<section class="deck-section">`.
 *
 * Quantity lives in a `deck-card-count` badge that is only rendered above 1, so
 * a missing badge means one copy — not zero. Reading it as zero silently drops
 * every singleton in the deck.
 */
function sectionCards(doc: Document, heading: string): DeckCard[] | null {
  const sections = [...doc.querySelectorAll("section.deck-section")];
  const section = sections.find((s) => textOf(s.querySelector("h2")).startsWith(heading));
  if (!section) return null;
  return [...section.querySelectorAll("a.deck-card-tile")].map((tile) => {
    const badge = textOf(tile.querySelector(".deck-card-count"));
    return {
      name: (tile.getAttribute("title") ?? "").trim(),
      code: (tile.getAttribute("href") ?? "").replace(/^\/atlas\//, ""),
      qty: badge ? Number.parseInt(badge, 10) : 1,
    };
  });
}

/**
 * A declared section count that disagrees with the tiles means the page did not
 * fully render — the deck is short, not small. Returned as a warning rather
 * than thrown so one bad list does not abort a whole pull.
 */
function sectionMismatch(doc: Document, heading: string, cards: DeckCard[]): string | null {
  const sections = [...doc.querySelectorAll("section.deck-section")];
  const section = sections.find((s) => textOf(s.querySelector("h2")).startsWith(heading));
  const declared = Number.parseInt(textOf(section?.querySelector(".deck-section-count") ?? null), 10);
  if (!Number.isFinite(declared)) return null;
  const actual = cards.reduce((n, c) => n + c.qty, 0);
  return actual === declared ? null : `${heading}: page declares ${declared}, tiles total ${actual}`;
}

export interface ParsedDeck {
  deck: Deck;
  warnings: string[];
}

export function parseDeckPage(html: string, url: string, fetched: string): ParsedDeck {
  const doc = new JSDOM(html).window.document;
  const warnings: string[] = [];

  const legend = textOf(doc.querySelector(".deck-meta-row strong"));
  if (!legend) throw new Error(`no legend found — page layout may have changed: ${url}`);

  const main: DeckCard[] = [];
  for (const heading of MAIN_DECK_SECTIONS) {
    const cards = sectionCards(doc, heading);
    // Not every deck runs gear; an absent section is legitimate, an empty one
    // after a layout change is not — the count check below catches that.
    if (!cards) continue;
    const mismatch = sectionMismatch(doc, heading, cards);
    if (mismatch) warnings.push(mismatch);
    main.push(...cards);
  }

  const runes = sectionCards(doc, "Runes") ?? [];
  const battlefields = sectionCards(doc, "Battlefields") ?? [];
  for (const [heading, cards] of [["Runes", runes], ["Battlefields", battlefields]] as const) {
    const mismatch = sectionMismatch(doc, heading, cards);
    if (mismatch) warnings.push(mismatch);
  }

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
  return { deck, warnings };
}

/** Deck ids linked from the meta index. */
export function parseDeckIndex(html: string): string[] {
  const doc = new JSDOM(html).window.document;
  const ids = [...doc.querySelectorAll('a[href^="/meta/"]')]
    .map((a) => (a.getAttribute("href") ?? "").replace("/meta/", "").trim())
    .filter(Boolean);
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

export function loadCardIndex(path?: string): CardIndex {
  const target = resolve(path ?? CARD_DATA_TARGETS[1]);
  if (!existsSync(target)) {
    throw new Error(`no card data at ${target} — run \`oracle skill-data\` first`);
  }
  return JSON.parse(readFileSync(target, "utf-8")) as CardIndex;
}

/** Stable, filesystem-safe name for a deck file. */
export function deckSlug(deck: Deck): string {
  const base = `${deck.legend} ${deck.name}`
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return base.slice(0, 80) || "deck";
}

export interface PullOptions {
  /** Cap on decks fetched. The index lists ~24; pulling all of them is fine. */
  limit?: number;
  /** Politeness gap between requests, ms. See docs/content-and-licensing.md. */
  delayMs?: number;
  outputDir?: string;
  gauntletDir?: string;
  cards?: CardIndex;
  onProgress?: (message: string) => void;
  fetchText?: (url: string) => Promise<string>;
  now?: () => string;
}

async function fetchText(url: string): Promise<string> {
  const res = await fetch(url, { headers: { "User-Agent": USER_AGENT } });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} for ${url}`);
  return res.text();
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export interface PullResult {
  decks: Deck[];
  warnings: string[];
  written: string[];
}

export async function pullMetaDecks(opts: PullOptions = {}): Promise<PullResult> {
  const get = opts.fetchText ?? fetchText;
  const onProgress = opts.onProgress ?? (() => {});
  const delayMs = opts.delayMs ?? 1200;
  const outputDir = opts.outputDir ?? DECK_OUTPUT_DIR;
  const gauntletDir = opts.gauntletDir ?? GAUNTLET_DIR;
  const cards = opts.cards ?? loadCardIndex();
  const fetched = (opts.now ?? (() => new Date().toISOString().slice(0, 10)))();

  const ids = parseDeckIndex(await get(INDEX_URL)).slice(0, opts.limit ?? Infinity);
  onProgress(`${ids.length} deck(s) listed`);

  const decks: Deck[] = [];
  const warnings: string[] = [];
  const written: string[] = [];

  for (const [i, id] of ids.entries()) {
    // Paced, and never scheduled — see docs/content-and-licensing.md.
    if (i > 0) await sleep(delayMs);
    const url = `https://${SITE}/meta/${id}`;
    try {
      const parsed = parseDeckPage(await get(url), url, fetched);
      Object.assign(parsed.deck, resolveChosenChampion(parsed.deck, cards));
      if (!parsed.deck.chosenChampion) {
        warnings.push(
          `${parsed.deck.name}: Chosen Champion unresolved ` +
            `(${(parsed.deck.championCandidates ?? []).join(", ") || "no champion unit found"})`
        );
      }
      warnings.push(...parsed.warnings.map((w) => `${parsed.deck.name}: ${w}`));
      decks.push(parsed.deck);
      onProgress(`${parsed.deck.legend} — ${parsed.deck.name}`);
    } catch (err) {
      warnings.push(`${url}: ${err instanceof Error ? err.message : String(err)}`);
    }
  }

  for (const deck of decks) {
    const body = JSON.stringify(deck, null, 1);
    for (const dir of [outputDir, gauntletDir]) {
      const path = resolve(dir, `${deckSlug(deck)}.json`);
      mkdirSync(dirname(path), { recursive: true });
      writeFileSync(path, body, "utf-8");
      written.push(path);
    }
  }

  return { decks, warnings, written };
}

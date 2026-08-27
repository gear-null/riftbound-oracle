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
import { createHash } from "node:crypto";
import { mkdirSync, writeFileSync, readFileSync, existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import type { CardIndex } from "./skill-data.js";
import { DECK_LAB_CARD_DATA } from "./skill-data.js";

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
  /** Parsed but NOT written, because the parse itself was untrustworthy. */
  quarantined: { name: string; reasons: string[] }[];
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
  const quarantined: { name: string; reasons: string[] }[] = [];

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
      if (parsed.structural.length) {
        // Writing a half-parsed deck over a good committed one loses data that
        // was correct. A named gap in the gauntlet beats silent corruption.
        quarantined.push({ name: parsed.deck.name, reasons: parsed.structural });
        continue;
      }
      decks.push(parsed.deck);
      onProgress(`${parsed.deck.legend} — ${parsed.deck.name}`);
    } catch (err) {
      warnings.push(`${url}: ${err instanceof Error ? err.message : String(err)}`);
    }
  }

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
      if (kept) {
        deck.chosen_champion = kept;
        if (existing?.chosen_champion_note) deck.chosen_champion_note = existing.chosen_champion_note;
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

  return { decks, warnings, written, quarantined };
}

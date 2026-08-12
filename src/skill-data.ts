/**
 * Build the data the rules-report skill ships with.
 *
 * The skill is the product: someone copies `.claude/skills/rules-report/`
 * into their own project and it answers questions immediately, offline, with
 * no clone and no build. That only works if everything it needs is vendored,
 * so this is the maintainer step that produces `data/cards.json` — every
 * card's printed text and artwork URL folded into one file.
 *
 * Previously the skill globbed the repo's `output/cards-*.md` and read a
 * separate `card-index.json` for images. Both lived outside the skill, so a
 * copied skill silently lost card lookup entirely and every report rendered an
 * artwork placeholder.
 */
import { writeFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fetchSets, fetchCardsBySet, type RiftcodexCard } from "./riftcodex.js";
import { decodeEntities } from "./normalize.js";

export const SKILL_DATA_DIR = ".claude/skills/rules-report/data";

export interface SkillCard {
  name: string;
  text: string;
  image?: string;
}

/** Keyed by lowercased lookup name; see `keysFor`. */
export type CardIndex = Record<string, SkillCard>;

/**
 * Every name a card should answer to.
 *
 * Cards print as "Viktor - Machine Herald", but people ask about "Viktor". Both
 * resolve. Keys shorter than four characters are dropped — a two-letter key
 * matches inside half the questions ever asked.
 */
export function keysFor(displayName: string): string[] {
  const base = displayName.replace(/\s*\(.*?\)\s*$/, "").trim();
  const beforeSubtitle = base.split(" - ")[0].trim();
  return [...new Set([base.toLowerCase(), beforeSubtitle.toLowerCase()])].filter(
    (k) => k.length > 3
  );
}

/**
 * Printed text in the shape `card_bridge.py` already parses: the stats line
 * followed by the card's plain text.
 *
 * `text.plain` is deliberate — it keeps the `[Keyword]` brackets and
 * `:rb_energy_1:` shortcodes, which is precisely what the bridge maps onto
 * glossary rule sections (805-829). Substituting a prettier rendering would
 * silently sever the card→rules link that makes card questions answerable.
 *
 * Entities must be decoded here. Riftcodex serves `text.plain` HTML-escaped,
 * so the keyword marker [>] arrives as `[&gt;]` — 93 occurrences across the
 * card pool. The markdown path ran this through `normalize()`, which decoded
 * them; going straight from the API to cards.json skipped that, which printed
 * a literal `[&gt;]` in reports and hid the `>` row from the symbol legend,
 * whose token scan saw four characters instead of one.
 */
export function cardText(card: RiftcodexCard): string {
  const stats: string[] = [];
  const { energy, might, power } = card.attributes ?? {};
  if (energy != null) stats.push(`**Energy:** ${energy}`);
  if (might != null) stats.push(`**Might:** ${might}`);
  if (power != null) stats.push(`**Power:** ${power}`);
  if (card.classification?.type) stats.push(`**Type:** ${card.classification.type}`);
  if (card.classification?.rarity) stats.push(`**Rarity:** ${card.classification.rarity}`);
  if (card.classification?.domain?.length) {
    stats.push(`**Domain:** ${card.classification.domain.join(", ")}`);
  }

  const parts = [stats.join(" | ")];
  const body = card.text?.plain?.trim();
  if (body) parts.push(body);
  return decodeEntities(parts.filter(Boolean).join("\n\n"));
}

/** Fold fetched cards into the lookup index, first printing of a name winning. */
export function buildCardIndex(cards: RiftcodexCard[]): CardIndex {
  const index: CardIndex = {};
  for (const card of cards) {
    const display = card.name.replace(/\s*\(.*?\)\s*$/, "").trim();
    const entry: SkillCard = { name: display, text: cardText(card) };
    const image = card.media?.image_url;
    if (image) entry.image = image;

    for (const key of keysFor(card.name)) {
      const existing = index[key];
      // A reprint may be the copy that carries artwork; take the image even
      // when keeping the earlier text, rather than losing it to ordering.
      if (existing) {
        if (!existing.image && entry.image) existing.image = entry.image;
        continue;
      }
      index[key] = { ...entry };
    }
  }
  return index;
}

export interface BuildSkillDataOptions {
  outputPath?: string;
  onProgress?: (message: string) => void;
  /** Injectable so tests never hit the network. */
  listSets?: typeof fetchSets;
  listCards?: typeof fetchCardsBySet;
}

export async function buildSkillData(opts: BuildSkillDataOptions = {}) {
  const onProgress = opts.onProgress ?? (() => {});
  const listSets = opts.listSets ?? fetchSets;
  const listCards = opts.listCards ?? fetchCardsBySet;
  const outputPath = resolve(opts.outputPath ?? `${SKILL_DATA_DIR}/cards.json`);

  const sets = await listSets();
  const all: RiftcodexCard[] = [];
  for (const set of sets) {
    onProgress(`${set.set_id}`);
    all.push(...(await listCards(set.set_id)));
  }

  const index = buildCardIndex(all);
  const withArt = Object.values(index).filter((c) => c.image).length;

  mkdirSync(dirname(outputPath), { recursive: true });
  // Sorted keys so an unchanged corpus regenerates byte-identically and a real
  // change shows up as a reviewable diff rather than a reshuffle.
  const sorted = Object.fromEntries(Object.entries(index).sort(([a], [b]) => a.localeCompare(b)));
  writeFileSync(outputPath, JSON.stringify(sorted, null, 1), "utf-8");

  return { outputPath, cards: all.length, keys: Object.keys(index).length, withArt };
}

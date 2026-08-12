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
import { writeFileSync, mkdirSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { parse as parseYaml } from "yaml";
import { loadErrata, sameWording, type Erratum } from "./errata.js";
import { fetchSets, fetchCardsBySet, type RiftcodexCard } from "./riftcodex.js";
import { decodeEntities } from "./normalize.js";

export const SKILL_DATA_DIR = ".claude/skills/rules-report/data";
export const OVERLAY_PATH = "manifests/card-overlays.yaml";

/** Hand-transcribed text the API does not carry. See the file's header. */
export interface CardOverlay {
  name: string;
  source?: string;
  granted_might?: number;
  granted_text?: string;
}

export function loadOverlays(path = OVERLAY_PATH): Map<string, CardOverlay> {
  let raw: string;
  try {
    raw = readFileSync(resolve(path), "utf-8");
  } catch {
    return new Map();   // optional: the pool is merely flagged without it
  }
  const parsed = parseYaml(raw) as { cards?: CardOverlay[] } | null;
  return new Map((parsed?.cards ?? []).map((c) => [c.name.toLowerCase(), c]));
}

/**
 * Fold a transcription into a card, and clear its `incomplete` flag.
 *
 * The granted Might is appended to the printed text rather than written into
 * `stats.might`: on the card it is a bonus the gear confers on its holder, not
 * the gear's own might, and putting it in the stats row would read as the
 * latter.
 */
/**
 * Replace API text with Riot's errata where the WORDING differs.
 *
 * Notation-only differences are left alone: the errata prints `[1][C]` where
 * the API sends `:rb_energy_1:`, and rewriting every reprinted card into the
 * other notation would churn the corpus for no gain.
 */
export function applyErratum(entry: SkillCard, erratum?: Erratum): SkillCard {
  if (!erratum || sameWording(entry.text, erratum.text)) return entry;
  return { ...entry, text: erratum.text, errata: "Riot errata (Rules Hub)" };
}

export function applyOverlay(entry: SkillCard, overlay?: CardOverlay): SkillCard {
  if (!overlay) return entry;
  const extra = [
    overlay.granted_text?.trim(),
    overlay.granted_might != null ? `Grants +${overlay.granted_might} Might.` : undefined,
  ].filter(Boolean);
  if (!extra.length) return entry;
  const merged: SkillCard = {
    ...entry,
    text: [entry.text, ...extra].filter(Boolean).join(" "),
  };
  delete merged.incomplete;
  return merged;
}

export interface CardStats {
  energy: number | null;
  might: number | null;
  power: number | null;
  type: string | null;
  rarity: string | null;
  domain: string[];
}

export interface SkillCard {
  name: string;
  /** Printed rules text only. Stats live in `stats`, not glued on as markdown. */
  text: string;
  stats: CardStats;
  image?: string;
  /**
   * Set when the upstream API is known to be missing part of the card's
   * printed text, so nothing downstream presents `text` as complete.
   *
   * Equipment gear is the known case: the API returns only the [Equip] clause
   * and omits the ability the gear grants once attached — the part anyone
   * would actually ask about. It is absent from `text.plain`, `text.rich` and
   * `media.accessibility_text` alike, so no field choice recovers it.
   */
  incomplete?: string;
  /**
   * Set when Riot's published errata replaced the card text the API served.
   * Riftcodex lags Riot by months, so where the two disagree the errata wins —
   * and the report says which text the reader is looking at.
   */
  errata?: string;
  /**
   * Set when a bare base name is shared by genuinely DIFFERENT cards — "Ahri"
   * covers Alluring, Inquisitive and Nine-Tailed Fox. Lists every full name so
   * the caller can refuse to guess instead of binding to whichever printing
   * the API happened to return first.
   */
  ambiguous?: string[];
}

/**
 * Print treatments Riftcodex reports in the rarity field. They are not
 * rarities, and a reprint carrying one would otherwise win the base-name slot
 * and display "Promo" where the card's actual rarity belongs.
 */
const PRINT_TREATMENTS = new Set(["promo", "showcase"]);

function isTreatment(rarity: string | null): boolean {
  return !!rarity && PRINT_TREATMENTS.has(rarity.toLowerCase());
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
 * The card's printed rules text, and nothing else.
 *
 * Stats used to be glued on as a markdown line — `**Energy:** 4 | **Might:**
 * 3 | ...` — which then rendered literally in reports, asterisks and all,
 * because nothing downstream parses markdown. They are structured fields now
 * (see `cardStats`) and the presentation layer decides how to show them.
 *
 * `text.plain` is deliberate: it keeps the `[Keyword]` brackets and
 * `:rb_energy_1:` shortcodes, which is exactly what `card_bridge.py` maps onto
 * glossary rule sections (805-829). A prettier rendering here would silently
 * sever the card→rules link that makes card questions answerable.
 *
 * Entities must be decoded. Riftcodex serves `text.plain` HTML-escaped, so the
 * keyword marker [>] arrives as `[&gt;]` — 93 occurrences across the pool. The
 * old markdown path ran normalize(), which decoded them; reading the API
 * directly skipped that, printing a literal `[&gt;]` and hiding the `>` row
 * from the symbol legend, whose token scan saw four characters instead of one.
 */
export function cardText(card: RiftcodexCard): string {
  return decodeEntities((card.text?.plain ?? "").trim());
}

/**
 * Does the API's text omit part of this card's printed text?
 *
 * Detected structurally, not by guessing: Riftcodex tags equipment gear
 * `Equipment`, and for exactly those cards `text.plain` stops after the
 * [Equip] clause. Measured over the pool, the tag and the truncation agree —
 * 27 of 107 gear cards, and no non-Equipment card affected. Returns the reason
 * to show a reader, or undefined when the text is whole.
 */
export function missingText(card: RiftcodexCard, text: string): string | undefined {
  if (!card.tags?.includes("Equipment")) return undefined;
  // Strip the [Equip] clause and its reminder parenthetical; if that is the
  // whole of the printed text, the granted ability never arrived.
  const rest = text.replace(/\[Equip\][^(]*(\([^)]*\))?/, "").trim();
  if (rest) return undefined;
  return "the ability this gear grants once attached is not in the source data";
}

/** The numbers and classifications, kept as data rather than prose. */
export function cardStats(card: RiftcodexCard): CardStats {
  const { energy = null, might = null, power = null } = card.attributes ?? {};
  return {
    energy,
    might,
    power,
    type: card.classification?.type ?? null,
    rarity: card.classification?.rarity ?? null,
    domain: card.classification?.domain ?? [],
  };
}

/**
 * Fold fetched cards into the lookup index.
 *
 * Two things must not be decided by fetch order:
 *
 * A reprint carrying a print treatment ("Promo", "Showcase") must not win the
 * slot and report that as the card's rarity — 126 of 954 cards did.
 *
 * A base name shared by genuinely different cards ("Ahri" covers three) must
 * not bind to one of them silently. `card_bridge.find_cards` refuses near-miss
 * matches precisely because returning a DIFFERENT card is worse than returning
 * nothing; an ambiguous alias reached the same outcome through the one path
 * that bypassed that guard, and now prints the wrong card's stats as fact.
 */
export function buildCardIndex(
  cards: RiftcodexCard[],
  overlays: Map<string, CardOverlay> = new Map(),
  errata: Map<string, Erratum> = new Map()
): CardIndex {
  const index: CardIndex = {};
  // Full display names seen per key, so a collision is detectable.
  const namesFor = new Map<string, Set<string>>();

  // Fold in a STABLE order. The API paginates without a guaranteed sort, so
  // "first printing wins" was decided by whatever order the fetch happened to
  // return: two consecutive runs of `oracle skill-data` differed in 27 entries,
  // 5 of which bound a base name to a genuinely different card ("ahri" landed
  // on Nine-Tailed Fox one run and Alluring the next). That churn also destroys
  // the reason the data is committed at all — a regeneration is supposed to
  // produce a reviewable diff, not noise.
  const ordered = [...cards].sort((a, b) => {
    const setA = a.set?.set_id ?? "";
    const setB = b.set?.set_id ?? "";
    if (setA !== setB) return setA < setB ? -1 : 1;
    const nA = a.collector_number ?? 0;
    const nB = b.collector_number ?? 0;
    if (nA !== nB) return nA - nB;
    return (a.riftbound_id ?? a.id ?? "") < (b.riftbound_id ?? b.id ?? "") ? -1 : 1;
  });

  for (const card of ordered) {
    const display = card.name.replace(/\s*\(.*?\)\s*$/, "").trim();
    const body = cardText(card);
    let entry: SkillCard = { name: display, text: body, stats: cardStats(card) };
    const gap = missingText(card, body);
    if (gap) entry.incomplete = gap;
    // Errata first: it is the authoritative text. An overlay then adds what no
    // text field carries at all (the granted-effect band), so the two compose.
    entry = applyErratum(entry, errata.get(display.toLowerCase()));
    entry = applyOverlay(entry, overlays.get(display.toLowerCase()));
    const image = card.media?.image_url;
    if (image) entry.image = image;

    for (const key of keysFor(card.name)) {
      if (!namesFor.has(key)) namesFor.set(key, new Set());
      namesFor.get(key)!.add(display);

      const existing = index[key];
      if (!existing) {
        index[key] = { ...entry };
        continue;
      }
      // A reprint may be the copy that carries artwork; take the image even
      // when keeping the earlier text, rather than losing it to ordering.
      if (!existing.image && entry.image) existing.image = entry.image;
      // Prefer a real rarity over a print treatment, whichever arrived first.
      if (existing.name === display
          && isTreatment(existing.stats.rarity) && !isTreatment(entry.stats.rarity)) {
        existing.stats = entry.stats;
      }
    }
  }

  for (const [key, names] of namesFor) {
    if (names.size > 1) index[key].ambiguous = [...names].sort();
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

  const overlays = loadOverlays();
  const errata = loadErrata();
  const index = buildCardIndex(all, overlays, errata);
  const errataApplied = new Set(
    Object.values(index).filter((c) => c.errata).map((c) => c.name)
  );
  const stillMissing = new Set(
    Object.values(index).filter((c) => c.incomplete).map((c) => c.name)
  );
  const withArt = Object.values(index).filter((c) => c.image).length;

  mkdirSync(dirname(outputPath), { recursive: true });
  // Sorted keys so an unchanged corpus regenerates byte-identically and a real
  // change shows up as a reviewable diff rather than a reshuffle.
  const sorted = Object.fromEntries(Object.entries(index).sort(([a], [b]) => a.localeCompare(b)));
  writeFileSync(outputPath, JSON.stringify(sorted, null, 1), "utf-8");

  return {
    outputPath,
    cards: all.length,
    keys: Object.keys(index).length,
    withArt,
    overlaid: overlays.size,
    errataApplied: errataApplied.size,
    errataAvailable: errata.size,
    stillMissing: [...stillMissing].sort(),
  };
}

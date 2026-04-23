import { mkdirSync, createWriteStream } from "node:fs";
import { join } from "node:path";
import { pipeline } from "node:stream/promises";
import { Readable } from "node:stream";
import type { RiftcodexCard } from "./riftcodex.js";

export interface PrintOptions {
  cards: RiftcodexCard[];
  outputDir: string;
  onProgress?: (message: string) => void;
}

type CardBucket = "legends" | "runes" | "tokens" | "battlefields" | "cards";

function getBucket(card: RiftcodexCard): CardBucket {
  if (card.classification.type === "Legend") return "legends";
  if (card.classification.type === "Rune") return "runes";
  if (card.classification.type === "Battlefield") return "battlefields";
  if (card.classification.supertype === "Token") return "tokens";
  return "cards";
}

function isUnique(card: RiftcodexCard): boolean {
  if (card.metadata.alternate_art) return false;
  if (card.metadata.overnumbered) return false;
  if (card.classification.rarity === "Showcase") return false;
  return true;
}

function domainSortKey(card: RiftcodexCard): string {
  const domains = card.classification.domain;
  if (domains.length === 0) return "ZZZ_Colorless";
  if (domains.length > 1) return "ZZZ_Multi_" + domains.sort().join("_");
  return domains[0];
}

function sortCards(cards: RiftcodexCard[]): RiftcodexCard[] {
  return [...cards].sort((a, b) => {
    // 1. Domain: single domains alphabetically, multi at end, colorless at end
    const domainA = domainSortKey(a);
    const domainB = domainSortKey(b);
    if (domainA !== domainB) return domainA.localeCompare(domainB);

    // 2. Energy cost ascending (null → 0)
    const energyA = a.attributes.energy ?? 0;
    const energyB = b.attributes.energy ?? 0;
    if (energyA !== energyB) return energyA - energyB;

    // 3. Power ascending (null → 0)
    const powerA = a.attributes.power ?? 0;
    const powerB = b.attributes.power ?? 0;
    if (powerA !== powerB) return powerA - powerB;

    // 4. Name alphabetical
    return a.name.localeCompare(b.name);
  });
}

function sanitize(name: string): string {
  return name.replace(/[^a-zA-Z0-9]/g, "_").replace(/_+/g, "_");
}

function buildFilename(index: number, card: RiftcodexCard): string {
  const num = String(index + 1).padStart(3, "0");
  const domains = card.classification.domain;
  const domainStr =
    domains.length === 0
      ? "Colorless"
      : domains.sort().join("_");
  const energy = card.attributes.energy !== null ? `${card.attributes.energy}E` : "";
  const power = card.attributes.power !== null ? `${card.attributes.power}P` : "";
  const name = sanitize(card.metadata.clean_name || card.name);

  const parts = [num, domainStr, energy, power, name].filter(Boolean);
  return parts.join("_") + ".png";
}

async function downloadImage(url: string, dest: string): Promise<void> {
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`Failed to download ${url}: ${res.status}`);
  }
  const body = res.body;
  if (!body) throw new Error(`No response body for ${url}`);
  await pipeline(Readable.fromWeb(body as any), createWriteStream(dest));
}

export async function downloadPrintCards(opts: PrintOptions): Promise<{
  legends: number;
  cards: number;
  runes: number;
  tokens: number;
}> {
  const { cards, outputDir, onProgress } = opts;

  // Filter to unique cards only
  const unique = cards.filter(isUnique);

  // Bucket into folders
  const buckets: Record<CardBucket, RiftcodexCard[]> = {
    legends: [],
    runes: [],
    tokens: [],
    battlefields: [],
    cards: [],
  };

  for (const card of unique) {
    buckets[getBucket(card)].push(card);
  }

  // Sort each bucket
  for (const key of Object.keys(buckets) as CardBucket[]) {
    buckets[key] = sortCards(buckets[key]);
  }

  // Create directories
  for (const key of Object.keys(buckets) as CardBucket[]) {
    if (buckets[key].length > 0) {
      mkdirSync(join(outputDir, key), { recursive: true });
    }
  }

  // Download images
  const total = unique.length;
  let downloaded = 0;

  for (const bucket of Object.keys(buckets) as CardBucket[]) {
    const bucketCards = buckets[bucket];
    for (let i = 0; i < bucketCards.length; i++) {
      const card = bucketCards[i];
      const filename = buildFilename(i, card);
      const dest = join(outputDir, bucket, filename);

      onProgress?.(`${++downloaded}/${total} — ${card.name}`);
      await downloadImage(card.media.image_url, dest);
    }
  }

  return {
    legends: buckets.legends.length,
    cards: buckets.cards.length,
    runes: buckets.runes.length,
    tokens: buckets.tokens.length,
    battlefields: buckets.battlefields.length,
  };
}

/**
 * Riftcodex API client — fetches card and set data from https://api.riftcodex.com
 */

const BASE_URL = process.env.RIFTCODEX_API_URL ?? "https://api.riftcodex.com";
const DEFAULT_PAGE_SIZE = 50;

export interface RiftcodexCard {
  id: string;
  name: string;
  riftbound_id: string;
  tcgplayer_id: string;
  collector_number: number;
  attributes: {
    energy: number | null;
    might: number | null;
    power: number | null;
  };
  classification: {
    type: string;
    supertype: string | null;
    rarity: string;
    domain: string[];
  };
  text: {
    rich: string;
    plain: string;
    flavour: string | null;
  };
  set: {
    set_id: string;
    label: string;
  };
  media: {
    image_url: string;
    artist: string;
    accessibility_text: string;
  };
  tags: string[];
  orientation: string;
  metadata: {
    clean_name: string;
    updated_on: string;
    alternate_art: boolean;
    overnumbered: boolean;
    signature: boolean;
  };
}

export interface RiftcodexSet {
  id: string;
  name: string;
  set_id: string;
  card_count: number;
  tcgplayer_id: string;
  cardmarket_id: string | string[];
  published_on: string;
}

interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  pages: number;
}

async function fetchJson<T>(path: string, params?: Record<string, string>): Promise<T> {
  const url = new URL(path, BASE_URL);
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      url.searchParams.set(key, value);
    }
  }

  const res = await fetch(url.toString());
  if (!res.ok) {
    throw new Error(`Riftcodex API error: ${res.status} ${res.statusText} for ${url}`);
  }
  return res.json() as Promise<T>;
}

export async function fetchSets(): Promise<RiftcodexSet[]> {
  const data = await fetchJson<{ items: RiftcodexSet[] }>("/sets");
  return data.items;
}

export async function fetchCardsBySet(setId: string): Promise<RiftcodexCard[]> {
  const allCards: RiftcodexCard[] = [];
  let page = 1;

  while (true) {
    const data = await fetchJson<PaginatedResponse<RiftcodexCard>>("/cards", {
      set_id: setId,
      limit: String(DEFAULT_PAGE_SIZE),
      page: String(page),
    });

    allCards.push(...data.items);

    if (page >= data.pages) break;
    page++;
  }

  return allCards;
}

export function cardToMarkdown(card: RiftcodexCard): string {
  const lines: string[] = [];

  lines.push(`### ${card.name}`);
  lines.push("");

  // Stats line
  const stats: string[] = [];
  if (card.attributes.energy !== null) stats.push(`**Energy:** ${card.attributes.energy}`);
  if (card.attributes.might !== null) stats.push(`**Might:** ${card.attributes.might}`);
  if (card.attributes.power !== null) stats.push(`**Power:** ${card.attributes.power}`);
  stats.push(`**Type:** ${card.classification.type}`);
  stats.push(`**Rarity:** ${card.classification.rarity}`);
  if (card.classification.domain.length > 0) {
    stats.push(`**Domain:** ${card.classification.domain.join(", ")}`);
  }

  lines.push(stats.join(" | "));
  lines.push("");

  // Card text
  if (card.text.plain) {
    lines.push(card.text.plain);
    lines.push("");
  }

  // Flavour text
  if (card.text.flavour) {
    lines.push(`> *${card.text.flavour}*`);
    lines.push("");
  }

  // Tags
  if (card.tags.length > 0) {
    lines.push(`**Tags:** ${card.tags.join(", ")}`);
    lines.push("");
  }

  // Metadata
  lines.push(`*Artist: ${card.media.artist} | ${card.set.label} #${card.collector_number}*`);
  lines.push("");

  return lines.join("\n");
}

export function cardsToMarkdown(cards: RiftcodexCard[], setLabel: string): string {
  // Sort by collector number
  const sorted = [...cards].sort((a, b) => a.collector_number - b.collector_number);

  // Group by type
  const byType = new Map<string, RiftcodexCard[]>();
  for (const card of sorted) {
    const type = card.classification.type;
    if (!byType.has(type)) byType.set(type, []);
    byType.get(type)!.push(card);
  }

  const sections: string[] = [];
  sections.push(`# ${setLabel} — Complete Card List`);
  sections.push("");
  sections.push(`**Total cards:** ${cards.length}`);
  sections.push("");

  for (const [type, typeCards] of byType) {
    sections.push(`## ${type}s (${typeCards.length})`);
    sections.push("");
    for (const card of typeCards) {
      sections.push(cardToMarkdown(card));
      sections.push("---");
      sections.push("");
    }
  }

  return sections.join("\n");
}

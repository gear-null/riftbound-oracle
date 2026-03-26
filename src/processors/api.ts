import { readFileSync, writeFileSync } from "node:fs";
import { basename, resolve } from "node:path";
import { normalize } from "../normalize.js";
import type { ProcessOptions } from "./index.js";

interface CardData {
  id?: string;
  name?: string;
  cost?: number | string;
  attack?: number | string;
  health?: number | string;
  type?: string;
  region?: string;
  rarity?: string;
  text?: string;
  flavor?: string;
  set?: string;
  [key: string]: unknown;
}

function cardToMarkdown(card: CardData): string {
  const lines: string[] = [];
  lines.push(`### ${card.name ?? "Unknown Card"}`);
  lines.push("");

  const meta: string[] = [];
  if (card.cost !== undefined) meta.push(`**Cost:** ${card.cost}`);
  if (card.attack !== undefined) meta.push(`**Attack:** ${card.attack}`);
  if (card.health !== undefined) meta.push(`**Health:** ${card.health}`);
  if (card.type) meta.push(`**Type:** ${card.type}`);
  if (card.region) meta.push(`**Region:** ${card.region}`);
  if (card.rarity) meta.push(`**Rarity:** ${card.rarity}`);
  if (card.set) meta.push(`**Set:** ${card.set}`);

  if (meta.length > 0) {
    lines.push(meta.join(" | "));
    lines.push("");
  }

  if (card.text) {
    lines.push(card.text);
    lines.push("");
  }

  if (card.flavor) {
    lines.push(`> ${card.flavor}`);
    lines.push("");
  }

  return lines.join("\n");
}

export async function processApi(opts: ProcessOptions): Promise<string> {
  const absolutePath = resolve(opts.sourcePath);
  const raw = readFileSync(absolutePath, "utf-8");
  const data = JSON.parse(raw);

  let markdown: string;

  if (Array.isArray(data)) {
    const cards = data as CardData[];
    const cardsMd = cards.map(cardToMarkdown).join("\n---\n\n");
    markdown = normalize(`# Riftbound Cards\n\n${cardsMd}`, opts.category);
  } else if (data.cards && Array.isArray(data.cards)) {
    const cards = data.cards as CardData[];
    const cardsMd = cards.map(cardToMarkdown).join("\n---\n\n");
    const title = data.set ?? data.name ?? "Riftbound Cards";
    markdown = normalize(`# ${title}\n\n${cardsMd}`, opts.category);
  } else {
    markdown = normalize(
      `# ${opts.category}\n\n\`\`\`json\n${JSON.stringify(data, null, 2)}\n\`\`\``,
      opts.category
    );
  }

  const outputName = basename(opts.sourcePath, ".json");
  const outputPath = opts.outputPath ?? `output/${outputName}.md`;

  writeFileSync(resolve(outputPath), markdown, "utf-8");

  return outputPath;
}

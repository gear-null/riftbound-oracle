/**
 * Riot's card errata, parsed out of the crawled Rules Hub articles.
 *
 * Card text comes from Riftcodex, a third-party database, and it lags: the API
 * still served Stalking Wolf's pre-errata wording months after Riot published
 * the correction. Riot's own errata is already in this repo — the Rules Hub
 * crawl writes it into `output/rules.md` as `[NEW TEXT]` / `[OLD TEXT]` blocks
 * under a heading per card.
 *
 * So the fix needs no new source and no transcription: where the two disagree,
 * Riot wins. That is the same Tier 1 precedence the project already applies to
 * rules, extended to the one dataset that was quietly exempt from it.
 *
 * Measured when this was written: 47 errata'd cards in the corpus, 36 of them
 * present in the card pool, 28 whose wording actually differed.
 */
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

export const RULES_MD = "output/rules.md";

export interface Erratum {
  name: string;
  text: string;
}

/** `\[Ambush\]` -> `[Ambush]`, and collapse the article's paragraph breaks. */
function unescapeMarkdown(s: string): string {
  return s.replace(/\\([[\]])/g, "$1").replace(/\s+/g, " ").trim();
}

/**
 * Compare on words alone, ignoring symbol notation.
 *
 * The errata prints `[1][C]` where the API sends `:rb_energy_1:`, so a literal
 * comparison marks every errata'd card as changed. Only a genuine wording
 * change should override — that keeps notation consistent across cards that
 * were merely reprinted, and keeps the diff honest.
 */
export function wordsOf(text: string): string[] {
  return (text || "")
    .replace(/:rb_\w+:/g, " ")
    .replace(/\[[^\]]*\]/g, " ")
    .toLowerCase()
    .match(/[a-z]+/g) ?? [];
}

export function sameWording(a: string, b: string): boolean {
  const x = wordsOf(a);
  const y = wordsOf(b);
  return x.length === y.length && x.every((w, i) => w === y[i]);
}

/** Every card the crawled errata articles give new text for. */
export function parseErrata(markdown: string): Map<string, Erratum> {
  const out = new Map<string, Erratum>();
  // Headings run `## Card Name`; a block ends at the next heading of any level.
  // `$` with the /m flag means end of LINE, which truncated every body to
  // nothing; `(?![\s\S])` is end of input.
  const blocks = markdown.matchAll(
    /^## ([^\n#]{2,60})\n([\s\S]*?)(?=\n## |\n# |(?![\s\S]))/gm
  );
  for (const [, rawName, body] of blocks) {
    // `▲` separates new from old in Riot's articles; stop at whichever comes first.
    const m = body.match(/\*\*\\\[NEW TEXT\\\]\*\*([\s\S]*?)(?:\n▲|\*\*\\\[OLD TEXT)/);
    if (!m) continue;
    const text = unescapeMarkdown(m[1]);
    if (!text) continue;
    out.set(rawName.trim().toLowerCase(), { name: rawName.trim(), text });
  }
  return out;
}

export function loadErrata(path = RULES_MD): Map<string, Erratum> {
  const full = resolve(path);
  if (!existsSync(full)) return new Map();   // rules not crawled yet; not fatal
  return parseErrata(readFileSync(full, "utf-8"));
}

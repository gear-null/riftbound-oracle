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
 * Measured: 63 errata'd cards in the corpus. It read 47 for a long time, and
 * the missing 16 were a whole article whose headings use a different depth —
 * see `parseErrata`. That is why `loadErrata` now counts the markers instead of
 * trusting the parse.
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
    // Digits KEPT. `[a-z]+` discarded them, so "Deal 4 to a unit" and "Deal 5
    // to a unit" compared equal — and a numeric nerf, which is the commonest
    // kind of TCG erratum there is, was dropped as "merely reprinted".
    .match(/[a-z0-9]+/g) ?? [];
}

export function sameWording(a: string, b: string): boolean {
  const x = wordsOf(a);
  const y = wordsOf(b);
  return x.length === y.length && x.every((w, i) => w === y[i]);
}

/** Every card the crawled errata articles give new text for. */
export function parseErrata(markdown: string): Map<string, Erratum> {
  const out = new Map<string, Erratum>();
  // Riot does not use one heading shape. The Origins article writes
  // `## Card Name`; Spiritforged writes `# **Card Name**`. Anchoring to exactly
  // two hashes skipped that whole article — 16 of 63 errata, six of which
  // changed wording, so those cards served text Riot had RETRACTED with no
  // banner, no marker and nothing on stderr. Accept both depths and strip the
  // bold wrapper, but not `# **_Origins Cards_**`: bold+italic is a group
  // heading, not a card.
  //
  // `$` with the /m flag means end of LINE, which truncated every body to
  // nothing; `(?![\s\S])` is end of input.
  const blocks = markdown.matchAll(
    /^#{1,2} (?!\*\*_)(?:\*\*)?([^\n#*][^\n#]{1,58}?)(?:\*\*)?[ \t]*\n([\s\S]*?)(?=\n#{1,2} |(?![\s\S]))/gm
  );
  for (const [, rawName, body] of blocks) {
    // `▲` separates new from old, and it is not always bare: the corpus writes
    // `#### ▲` and `#### **▲**` far more often than `▲` alone. Matching only
    // the bare form let the marker and its markdown scaffolding be captured AS
    // CARD TEXT, so 17 cards shipped `#### ▲ #####` under a banner asserting it
    // was Riot's corrected wording.
    const m = body.match(
      /\*\*\\\[NEW TEXT\\\]\*\*([\s\S]*?)(?:\n#{0,6}[ \t]*\*{0,2}▲|\*\*\\\[OLD TEXT)/
    );
    if (!m) continue;
    const text = unescapeMarkdown(m[1]);
    if (!text) continue;
    out.set(rawName.trim().toLowerCase(), { name: rawName.trim(), text });
  }
  return out;
}

/**
 * How many cards the article text claims an erratum for.
 *
 * Compared against `parseErrata().size` at build time. The heading-shape bug
 * above was silent for months precisely because nothing counted: the parser
 * returned 47 entries from a document carrying 63, and 47 looks like a fine
 * number on its own.
 */
export function countErrataMarkers(markdown: string): number {
  return (markdown.match(/\\\[NEW TEXT\\\]/g) ?? []).length;
}

export function loadErrata(path = RULES_MD): Map<string, Erratum> {
  const full = resolve(path);
  if (!existsSync(full)) return new Map();   // rules not crawled yet; not fatal
  const md = readFileSync(full, "utf-8");
  const parsed = parseErrata(md);
  // Loud, because the alternative is silence: a heading shape this parser does
  // not know produces FEWER entries, not an error, and the cards it missed then
  // serve text Riot has retracted with nothing to indicate it. Riot can change
  // the shape in any article; the count is what notices.
  const claimed = countErrataMarkers(md);
  if (parsed.size < claimed) {
    console.warn(
      `  errata: the article claims ${claimed} cards but only ${parsed.size} parsed — ` +
      "a heading shape changed; those cards will serve pre-errata text"
    );
  }
  return parsed;
}

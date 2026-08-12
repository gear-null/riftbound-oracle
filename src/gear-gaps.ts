/**
 * Prepare the transcription task for cards whose text the API does not carry.
 *
 * Equipment gear prints its granted effect in a band at the foot of the card —
 * a "+N Might" badge and sometimes rules text — and none of it reaches the
 * Riftcodex API. Checked: `text.plain`, `text.rich` and
 * `media.accessibility_text` all stop after the [Equip] clause,
 * `attributes.might` is null, the OpenAPI schema has no other field, and Riot's
 * Sanity dataset is private. It exists only on the artwork.
 *
 * So a human transcribes it once per set, into `manifests/card-overlays.yaml`.
 * This command removes the legwork from that: it downloads each flagged card's
 * artwork, and writes a YAML stub with the names and provenance URLs already
 * filled in. Someone opens the images and types the numbers.
 *
 * Nothing here parses the images. The pipeline stays deterministic and
 * model-free, which is what lets a full regeneration run unattended — see
 * docs/maintaining.md.
 */
import { writeFileSync, mkdirSync } from "node:fs";
import { join, resolve } from "node:path";
import { loadOverlays, type SkillCard } from "./skill-data.js";

export interface GearGap {
  name: string;
  image?: string;
  reason: string;
}

/** Cards still missing text, in name order, excluding anything already transcribed. */
export function findGaps(
  index: Record<string, SkillCard>,
  overlays: Map<string, unknown> = new Map()
): GearGap[] {
  const seen = new Map<string, GearGap>();
  for (const card of Object.values(index)) {
    if (!card.incomplete) continue;
    if (overlays.has(card.name.toLowerCase())) continue;
    seen.set(card.name, { name: card.name, image: card.image, reason: card.incomplete });
  }
  return [...seen.values()].sort((a, b) => a.name.localeCompare(b.name));
}

/**
 * A stub the maintainer edits rather than authors. Every field that can be
 * filled in mechanically already is; the reader supplies only what the image
 * shows, which is the part no tool here can determine.
 */
export function stubYaml(gaps: GearGap[]): string {
  if (!gaps.length) return "# No cards are missing text. Nothing to transcribe.\n";
  const body = gaps
    .map((g) =>
      [
        `  - name: ${JSON.stringify(g.name)}`,
        g.image ? `    source: ${g.image}` : "    # no artwork URL on record",
        `    # ${g.reason}`,
        `    granted_might: # +N from the badge at the foot of the card`,
        `    # granted_text: >-   # only if the band also has rules text`,
        `    #   ...`,
      ].join("\n")
    )
    .join("\n\n");
  return (
    "# Generated stub — move completed entries into manifests/card-overlays.yaml.\n" +
    "# Transcribe from the artwork; a wrong transcription is worse than a flagged gap.\n\n" +
    `cards:\n${body}\n`
  );
}

export interface CollectOptions {
  outputDir?: string;
  onProgress?: (message: string) => void;
  fetchImage?: (url: string) => Promise<ArrayBuffer>;
}

async function defaultFetchImage(url: string): Promise<ArrayBuffer> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.arrayBuffer();
}

/** Download each gap's artwork next to the stub, so the images are to hand. */
export async function collectGaps(gaps: GearGap[], opts: CollectOptions = {}) {
  const dir = resolve(opts.outputDir ?? "gear-gaps");
  const onProgress = opts.onProgress ?? (() => {});
  const fetchImage = opts.fetchImage ?? defaultFetchImage;

  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, "overlay-stub.yaml"), stubYaml(gaps), "utf-8");

  let saved = 0;
  const failed: string[] = [];
  for (const gap of gaps) {
    if (!gap.image) continue;
    onProgress(gap.name);
    try {
      const buf = await fetchImage(gap.image);
      const slug = gap.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
      writeFileSync(join(dir, `${slug}.png`), Buffer.from(buf));
      saved++;
    } catch (err) {
      // One unreachable image must not abandon the other 24.
      failed.push(`${gap.name} (${err instanceof Error ? err.message : String(err)})`);
    }
  }
  return { dir, gaps: gaps.length, saved, failed };
}

export { loadOverlays };

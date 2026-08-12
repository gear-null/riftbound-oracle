import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { parse, parseDocument, stringify } from "yaml";

const MANIFEST_PATH = resolve(
  import.meta.dirname,
  "../manifests/sources.yaml"
);

/** Fields every source type carries, whatever it fetches. */
export interface SourceCommon {
  category: string;
  output: string;
  processed?: string;
}

/** A local file (PDF, HTML, JSON) */
export interface FileSource extends SourceCommon {
  type: "pdf" | "html" | "json";
  path: string;
  url?: string;
  /** If true, convert PDF to markdown. Default: false (keep the original PDF) */
  convert?: boolean;
}

/** A URL to fetch and convert */
export interface UrlSource extends SourceCommon {
  type: "url";
  url: string;
}

/** A Riftcodex API set to fetch */
export interface RiftcodexSource extends SourceCommon {
  type: "riftcodex";
  set_id: string;
}

/** The Riftbound Rules Hub — a landing page with linked PDFs and articles */
export interface RulesHubSource extends SourceCommon {
  type: "rules-hub";
  url: string;
  /** Sibling PDFs auto-discovered from the hub; populated by the processor on each run. */
  pdfs?: string[];
  /** Extra article URLs to include even if the hub doesn't link to them (e.g. FAQs). */
  extra_articles?: string[];
}

export type ManifestEntry =
  | FileSource
  | UrlSource
  | RiftcodexSource
  | RulesHubSource;

export interface Manifest {
  entries: ManifestEntry[];
}

export function readManifest(): Manifest {
  try {
    const raw = readFileSync(MANIFEST_PATH, "utf-8");
    const data = parse(raw) as Manifest;
    return { entries: data?.entries ?? [] };
  } catch {
    return { entries: [] };
  }
}

/**
 * Merge processing state into the manifest's existing YAML text.
 *
 * `setIn` updates and adds keys but never removes them, which is fine here:
 * processors only ever set fields (`processed`, `pdfs`).
 */
export function applyManifestToYaml(yamlText: string, manifest: Manifest): string {
  const doc = parseDocument(yamlText);
  manifest.entries.forEach((entry, i) => {
    for (const [key, value] of Object.entries(entry)) {
      doc.setIn(["entries", i, key], value);
    }
  });
  return doc.toString({ lineWidth: 120 });
}

/**
 * Write processing state back, preserving the file's comments.
 *
 * A plain `stringify(manifest)` drops every `#` line, and `handleProcess`
 * writes the manifest at the end of every run — so any comment explaining a
 * source would vanish on a user's first ordinary run, leaving them a
 * spurious dirty diff to puzzle over.
 */
export function writeManifest(manifest: Manifest): void {
  let existing: string | undefined;
  try {
    existing = readFileSync(MANIFEST_PATH, "utf-8");
  } catch {
    // Nothing on disk to merge into (first run, or removed mid-run) — fall
    // back to a plain serialization rather than losing the state entirely.
  }

  const raw = existing
    ? applyManifestToYaml(existing, manifest)
    : stringify(manifest, { lineWidth: 120 });
  writeFileSync(MANIFEST_PATH, raw, "utf-8");
}

export function markProcessed(manifest: Manifest, output: string): void {
  const entry = manifest.entries.find((e) => e.output === output);
  if (entry) {
    entry.processed = new Date().toISOString().split("T")[0];
  }
}

/**
 * Choose which entries a run touches, given an optional `--only=` selector.
 *
 * `only` matches either a category (`rules`, `cards`) or a substring of the
 * output path. No selector means every entry.
 */
export function selectEntries(
  entries: ManifestEntry[],
  only?: string
): ManifestEntry[] {
  if (!only) return entries;
  return entries.filter((e) => e.category === only || e.output.includes(only));
}

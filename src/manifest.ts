import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { parse, stringify } from "yaml";

const MANIFEST_PATH = resolve(
  import.meta.dirname,
  "../manifests/sources.yaml"
);

/** A local file (PDF, HTML, JSON) */
export interface FileSource {
  type: "pdf" | "html" | "json";
  path: string;
  category: string;
  output: string;
  url?: string;
  /** If true, convert PDF to markdown. Default: false (upload original PDF) */
  convert?: boolean;
  processed?: string;
}

/** A URL to fetch and convert */
export interface UrlSource {
  type: "url";
  url: string;
  category: string;
  output: string;
  processed?: string;
}

/** A Riftcodex API set to fetch */
export interface RiftcodexSource {
  type: "riftcodex";
  set_id: string;
  category: string;
  output: string;
  processed?: string;
}

/** The Riftbound Rules Hub — a landing page with linked PDFs and articles */
export interface RulesHubSource {
  type: "rules-hub";
  url: string;
  category: string;
  output: string;
  /** Sibling PDFs auto-discovered from the hub; populated by the processor on each run. */
  pdfs?: string[];
  /** Extra article URLs to include even if the hub doesn't link to them (e.g. FAQs). */
  extra_articles?: string[];
  processed?: string;
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

export function writeManifest(manifest: Manifest): void {
  const raw = stringify(manifest, { lineWidth: 120 });
  writeFileSync(MANIFEST_PATH, raw, "utf-8");
}

export function markProcessed(manifest: Manifest, output: string): void {
  const entry = manifest.entries.find((e) => e.output === output);
  if (entry) {
    entry.processed = new Date().toISOString().split("T")[0];
  }
}

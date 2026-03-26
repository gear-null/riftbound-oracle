import "dotenv/config";
import * as p from "@clack/prompts";
import color from "picocolors";
import { writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { processSource } from "./processors/index.js";
import { processUrl } from "./processors/url.js";
import { uploadToDrive } from "./upload.js";
import {
  readManifest,
  writeManifest,
  markProcessed,
  type Manifest,
  type ManifestEntry,
} from "./manifest.js";
import { fetchCardsBySet, cardsToMarkdown } from "./riftcodex.js";
import { normalize } from "./normalize.js";

const command = process.argv[2];

async function main() {
  p.intro(color.bgMagenta(color.white(" riftbound-oracle ")));

  if (!command || command === "help") {
    showHelp();
    return;
  }

  switch (command) {
    case "process":
      await handleProcess();
      break;
    case "upload":
      await handleUpload();
      break;
    case "status":
      await handleStatus();
      break;
    default:
      p.log.error(`Unknown command: ${command}`);
      showHelp();
  }

  p.outro(color.dim("done"));
}

function showHelp() {
  p.log.message(`
${color.bold("Commands:")}
  ${color.cyan("process")}            Process all sources from manifest
  ${color.cyan("process --only=X")}   Process only entries matching category or output path
  ${color.cyan("upload")}             Upload output markdown to Google Drive
  ${color.cyan("status")}             Show manifest status
  ${color.cyan("help")}               Show this help message
  `);
}

function filterEntries(entries: ManifestEntry[]): ManifestEntry[] {
  const only = process.argv.find((a) => a.startsWith("--only="))?.split("=")[1];
  if (!only) return entries;

  return entries.filter(
    (e) => e.category === only || e.output.includes(only)
  );
}

async function processEntry(
  entry: ManifestEntry,
  manifest: Manifest
): Promise<boolean> {
  const s = p.spinner();
  const startTime = performance.now();
  const label = entryLabel(entry);

  s.start(`Processing ${label}`);

  try {
    switch (entry.type) {
      case "pdf": {
        if (!entry.convert) {
          // PDFs are uploaded directly to Drive — no conversion needed
          s.stop(`${label} — skipped (uploaded as original PDF)`);
          markProcessed(manifest, entry.output);
          return true;
        }
        // Fall through to process if convert: true
      }
      case "html":
      case "json": {
        await processSource({
          sourcePath: entry.path,
          category: entry.category,
          outputPath: entry.output,
          onProgress: (progress) => {
            s.message(`Processing ${label} — ${progress}`);
          },
        });
        break;
      }
      case "url": {
        await processUrl(entry.url, entry.category, entry.output, (progress) => {
          s.message(`Processing ${label} — ${progress}`);
        });
        break;
      }
      case "riftcodex": {
        s.message(`Fetching ${label} from Riftcodex API`);
        const cards = await fetchCardsBySet(entry.set_id);
        const rawMarkdown = cardsToMarkdown(cards, `${entry.set_id} Set`);
        const markdown = normalize(rawMarkdown, entry.category);
        writeFileSync(resolve(entry.output), markdown, "utf-8");
        break;
      }
    }

    markProcessed(manifest, entry.output);
    const elapsed = ((performance.now() - startTime) / 1000).toFixed(1);
    s.stop(`${label} → ${color.cyan(entry.output)} ${color.dim(`(${elapsed}s)`)}`);
    return true;
  } catch (err) {
    s.error(`Failed: ${label}`);
    p.log.error(String(err));
    return false;
  }
}

function entryLabel(entry: ManifestEntry): string {
  switch (entry.type) {
    case "pdf":
    case "html":
    case "json":
      return entry.path;
    case "url":
      return new URL(entry.url).pathname.split("/").filter(Boolean).pop() ?? entry.url;
    case "riftcodex":
      return `riftcodex:${entry.set_id}`;
  }
}

async function handleProcess() {
  const manifest = readManifest();
  const entries = filterEntries(manifest.entries);

  if (entries.length === 0) {
    p.log.warning("No entries to process. Add sources to manifests/sources.yaml.");
    return;
  }

  p.log.info(`Processing ${color.bold(String(entries.length))} source(s) from manifest`);

  let succeeded = 0;
  let failed = 0;

  for (const entry of entries) {
    const ok = await processEntry(entry, manifest);
    if (ok) succeeded++;
    else failed++;
  }

  writeManifest(manifest);

  if (failed > 0) {
    p.log.warning(`${succeeded} succeeded, ${failed} failed`);
  } else {
    p.log.success(`All ${succeeded} source(s) processed`);
  }
}

async function handleUpload() {
  const s = p.spinner();
  s.start("Uploading output to Google Drive");

  try {
    const uploaded = await uploadToDrive();
    s.stop(`Uploaded ${uploaded.length} file(s) to Drive`);
    for (const file of uploaded) {
      p.log.info(`  ${color.dim("→")} ${file}`);
    }
  } catch (err) {
    s.error("Upload failed");
    p.log.error(String(err));
  }
}

async function handleStatus() {
  const manifest = readManifest();

  if (manifest.entries.length === 0) {
    p.log.warning("No entries in manifest.");
    return;
  }

  p.log.message(color.bold(`${manifest.entries.length} source(s) in manifest:`));
  for (const entry of manifest.entries) {
    const label = entryLabel(entry);
    const status = entry.processed
      ? color.green(`processed ${entry.processed}`)
      : color.yellow("pending");
    p.log.info(
      `  ${color.cyan(entry.output)} ← ${color.dim(label)} [${status}]`
    );
  }
}

main().catch((err) => {
  p.log.error(String(err));
  process.exit(1);
});

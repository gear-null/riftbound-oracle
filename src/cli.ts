import "dotenv/config";
import * as p from "@clack/prompts";
import color from "picocolors";
import { writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { processSource } from "./processors/index.js";
import { processUrl } from "./processors/url.js";
import { processRulesHub } from "./processors/rules-hub.js";
import { uploadToDrive, cleanupDrive, listDriveFiles } from "./upload.js";
import {
  readManifest,
  writeManifest,
  markProcessed,
  type Manifest,
  type ManifestEntry,
} from "./manifest.js";
import { fetchSets, fetchCardsBySet, cardsToMarkdown } from "./riftcodex.js";
import { normalize } from "./normalize.js";
import { downloadPrintCards } from "./print.js";

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
    case "print":
      await handlePrint();
      break;
    case "upload":
      await handleUpload();
      break;
    case "cleanup":
      await handleCleanup();
      break;
    case "drive-status":
      await handleDriveStatus();
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
  ${color.cyan("print --set=X")}      Download card images for printing
  ${color.cyan("upload")}             Upload output markdown to Google Drive
  ${color.cyan("drive-status")}       Show every Drive file the app can see
  ${color.cyan("cleanup [--confirm]")}  Delete Drive orphans & duplicates (dry-run by default)
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
      case "rules-hub": {
        const result = await processRulesHub({
          hubUrl: entry.url,
          category: entry.category,
          outputPath: entry.output,
          onProgress: (progress) => {
            s.message(`Processing ${label} — ${progress}`);
          },
        });
        // Persist the discovered PDFs so the uploader can pick them up.
        entry.pdfs = result.pdfOutputs.map((p) =>
          p.startsWith("output/") ? p : p.replace(/^.*\/output\//, "output/")
        );
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
    case "rules-hub":
      return `rules-hub:${new URL(entry.url).hostname}`;
    case "riftcodex":
      return `riftcodex:${entry.set_id}`;
  }
}

async function handlePrint() {
  const setArg = process.argv.find((a) => a.startsWith("--set="))?.split("=")[1];
  const outputArg = process.argv.find((a) => a.startsWith("--output="))?.split("=")[1];

  let setId: string;
  let sets;

  if (setArg) {
    setId = setArg.toUpperCase();
  } else {
    // Interactive: pick a set
    const s = p.spinner();
    s.start("Fetching available sets from Riftcodex");
    sets = await fetchSets();
    s.stop(`Found ${sets.length} set(s)`);

    const selected = await p.select({
      message: "Which set do you want to download for printing?",
      options: sets.map((set) => ({
        value: set.set_id,
        label: `${set.name} (${set.set_id}) — ${set.card_count} cards`,
      })),
    });

    if (p.isCancel(selected)) {
      p.cancel("Cancelled.");
      process.exit(0);
    }
    setId = selected as string;
  }

  const outputDir = resolve(outputArg ?? `print/${setId.toLowerCase()}`);

  const s = p.spinner();
  const startTime = performance.now();
  s.start(`Fetching ${setId} card data`);

  const cards = await fetchCardsBySet(setId);
  s.message(`Downloading ${setId} card images`);

  const counts = await downloadPrintCards({
    cards,
    outputDir,
    onProgress: (msg) => s.message(`Downloading — ${msg}`),
  });

  const elapsed = ((performance.now() - startTime) / 1000).toFixed(1);
  s.stop(`Downloaded to ${outputDir} ${color.dim(`(${elapsed}s)`)}`);

  p.log.info(`  ${color.cyan("legends/")}      — ${counts.legends} card(s) ${color.dim("(print 1 copy)")}`);
  p.log.info(`  ${color.cyan("cards/")}        — ${counts.cards} card(s) ${color.dim("(print 3 copies)")}`);
  p.log.info(`  ${color.cyan("battlefields/")} — ${counts.battlefields} card(s)`);
  p.log.info(`  ${color.cyan("runes/")}        — ${counts.runes} card(s)`);
  p.log.info(`  ${color.cyan("tokens/")}       — ${counts.tokens} card(s)`);
  const total = counts.legends + counts.cards + counts.battlefields + counts.runes + counts.tokens;
  p.log.success(`Total: ${total} unique cards`);
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

async function handleDriveStatus() {
  const s = p.spinner();
  s.start("Listing files visible to this app in Drive");
  try {
    const files = await listDriveFiles();
    s.stop(`Found ${files.length} file(s) in the target folder`);

    if (files.length === 0) {
      p.log.warning("No files visible — either the folder is empty or none were created by this OAuth session.");
      return;
    }

    const sorted = [...files].sort((a, b) =>
      b.modifiedTime.localeCompare(a.modifiedTime)
    );
    for (const f of sorted) {
      const date = f.modifiedTime.slice(0, 10);
      const size = f.size ? `${Math.round(Number(f.size) / 1024)} KB` : "—";
      p.log.info(
        `  ${color.cyan(f.name)} ${color.dim(`[${date}, ${size}, ${f.mimeType}]`)}`
      );
    }
  } catch (err) {
    s.error("Drive listing failed");
    p.log.error(String(err));
  }
}

async function handleCleanup() {
  const confirm = process.argv.includes("--confirm");
  const s = p.spinner();
  s.start(confirm ? "Cleaning up Drive folder" : "Planning Drive cleanup (dry-run)");

  try {
    const result = await cleanupDrive({ confirm });
    s.stop(confirm ? "Cleanup complete" : "Cleanup plan ready");

    if (result.kept.length > 0) {
      p.log.message(color.bold(`Keeping ${result.kept.length} file(s):`));
      for (const f of result.kept) {
        p.log.info(`  ${color.green("✓")} ${f.name} ${color.dim(`(${f.modifiedTime.slice(0, 10)})`)}`);
      }
    }

    if (result.toDelete.length === 0) {
      p.log.success("No orphans or duplicates visible to the app.");
    } else {
      p.log.message(
        color.bold(
          `${confirm ? "Deleted" : "Would delete"} ${result.toDelete.length} file(s):`
        )
      );
      for (const { file, reason } of result.toDelete) {
        p.log.info(
          `  ${color.red("✗")} ${file.name} ${color.dim(`(${file.modifiedTime.slice(0, 10)}) — ${reason}`)}`
        );
      }
      if (!confirm) {
        p.log.message(
          `\nRun ${color.cyan("npm run oracle -- cleanup --confirm")} to actually delete these files.`
        );
      }
    }
  } catch (err) {
    s.error("Cleanup failed");
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

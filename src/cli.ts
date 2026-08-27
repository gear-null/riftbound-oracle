import "dotenv/config";
import * as p from "@clack/prompts";
import color from "picocolors";
import { readFileSync, readdirSync, writeFileSync } from "node:fs";
import { resolve, basename } from "node:path";
import { execFileSync } from "node:child_process";
import { processSource } from "./processors/index.js";
import { processUrl } from "./processors/url.js";
import { processRulesHub } from "./processors/rules-hub.js";
import { extractPdfText } from "./processors/pdf.js";
import {
  readManifest,
  writeManifest,
  markProcessed,
  selectEntries,
  type Manifest,
  type ManifestEntry,
} from "./manifest.js";
import { fetchSets, fetchCardsBySet, cardsToMarkdown, fetchSetLabel } from "./riftcodex.js";
import { buildSkillData, SKILL_DATA_DIR } from "./skill-data.js";
import { pullMetaDecks } from "./decks.js";
import { normalize } from "./normalize.js";
import { downloadPrintCards } from "./print.js";
import { syncToVault, resolveVaultDir } from "./vault.js";

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
    case "extract":
      await handleExtract();
      break;
    case "watch":
      await handleWatch();
      break;
    case "changelog":
      await handleChangelog();
      break;
    case "package":
      await handlePackage();
      break;
    case "gear-gaps":
      await handleGearGaps();
      break;
    case "skill-data":
      await handleSkillData();
      break;
    case "decks":
      await handleDecks();
      break;
    case "vault-sync":
      await handleVaultSync();
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
  ${color.cyan("extract")}            Extract downloaded rulebook PDFs to markdown
  ${color.cyan("skill-data")}         Rebuild the skill's vendored card data (needs network)
  ${color.cyan("decks pull")}         Pull competitive decklists into the deck-lab gauntlet (needs network)
  ${color.cyan("gear-gaps")}          Collect artwork + a YAML stub for cards the API can't supply
  ${color.cyan("package")}            Build every skill's release archive into dist/
  ${color.cyan("package --skill=X")}  Build just that skill's archive
  ${color.cyan("changelog")}          Draft the next changelog entry from git + the corpus
  ${color.cyan("watch")}              Check upstream for new sets or changed card counts
  ${color.cyan("vault-sync")}         Mirror output/ into an Obsidian wiki's raw/ folder
  ${color.cyan("status")}             Show manifest status
  ${color.cyan("help")}               Show this help message
  `);
}

function filterEntriesFromArgv(entries: ManifestEntry[]): ManifestEntry[] {
  return selectEntries(
    entries,
    process.argv.find((a) => a.startsWith("--only="))?.split("=")[1]
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
          // Kept as the original PDF; `oracle extract` turns it into markdown.
          s.stop(`${label} — skipped (kept as PDF; run \`extract\`)`);
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
          extraArticles: entry.extra_articles,
          onProgress: (progress) => {
            s.message(`Processing ${label} — ${progress}`);
          },
        });
        // Record which PDFs this run downloaded. Traceability only — `extract`
        // and `vault-sync` find PDFs by scanning output/, not by reading this.
        entry.pdfs = result.pdfOutputs.map((p) =>
          p.startsWith("output/") ? p : p.replace(/^.*\/output\//, "output/")
        );
        break;
      }
      case "riftcodex": {
        s.message(`Fetching ${label} from Riftcodex API`);
        const cards = await fetchCardsBySet(entry.set_id);
        const rawMarkdown = cardsToMarkdown(cards, await fetchSetLabel(entry.set_id, cards));
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
  const entries = filterEntriesFromArgv(manifest.entries);

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


/**
 * Turn the downloaded rulebook PDFs into markdown inside output/.
 *
 * Without this a fresh clone has core-rules.pdf but nothing readable, because
 * extraction used to happen only as a side effect of vault-sync. The rules
 * answerer needs core-rules.md and tournament-rules.md to exist locally.
 */
async function handleExtract() {
  const s = p.spinner();
  const pdfs = readdirSync(resolve("output")).filter((f) => f.endsWith(".pdf"));
  if (pdfs.length === 0) {
    p.log.warning("No PDFs in output/. Run `oracle process --only=rules` first.");
    return;
  }
  for (const pdf of pdfs) {
    const out = `output/${basename(pdf, ".pdf")}.md`;
    s.start(`Extracting ${pdf}`);
    try {
      const text = await extractPdfText(resolve("output", pdf), (m) =>
        s.message(`Extracting ${pdf} — ${m}`)
      );
      writeFileSync(resolve(out), normalize(text, "rules"), "utf-8");
      s.stop(`${pdf} → ${color.cyan(out)}`);
    } catch (err) {
      s.error(`Failed: ${pdf}`);
      p.log.error(String(err));
    }
  }
}

/**
 * Rebuild `.claude/skills/rules-report/data/cards.json`.
 *
 * This is the maintainer step that makes the skill portable: card text and
 * artwork URLs are folded into one file that ships inside the skill, so a
 * copied skill answers card questions with no repo, no network and no build.
 *
 * Failure is non-fatal. The committed cards.json stays valid, and rules-only
 * questions never touched card data anyway.
 */
/**
 * Gather everything a maintainer needs to transcribe the card text the API
 * does not carry. Downloads the artwork and writes a pre-filled stub; the
 * human supplies only what the image shows. No parsing, no model.
 */
/**
 * Report upstream card-side drift, and record the new state when asked.
 *
 * Exits 0 with `changed=false` when nothing moved, so a scheduled job can act
 * on the output without parsing prose. `--write` updates the committed state,
 * which a rebuild does once it has actually regenerated against it.
 */
async function handleWatch() {
  const { checkUpstream, saveState } = await import("./watch.js");
  const s = p.spinner();
  s.start("Checking upstream");
  try {
    const result = await checkUpstream();

    if (!result.reachable) {
      // Not an error in this repository: hosted CI is blocked by Cloudflare at
      // both upstreams. Say so, and do not claim all-clear.
      s.stop("Could not reach upstream");
      p.log.warning(
        `${result.reason} — no conclusion drawn. Riftcodex and Riot's hub both ` +
          "refuse datacenter IPs; run this from an ordinary connection."
      );
      if (process.env.GITHUB_OUTPUT) {
        writeFileSync(
          process.env.GITHUB_OUTPUT,
          `changed=false\nreachable=false\nsummary=upstream unreachable from this runner\n`,
          { flag: "a" }
        );
      }
      return;
    }

    const { drift, live } = result;
    s.stop(drift.changed ? "Upstream has moved" : "Upstream unchanged");
    p.log.message(drift.summary);

    if (process.argv.includes("--write")) {
      saveState(live, new Date().toISOString().slice(0, 10));
      p.log.info("Recorded current upstream state");
    }
    if (process.env.GITHUB_OUTPUT) {
      writeFileSync(
        process.env.GITHUB_OUTPUT,
        `changed=${drift.changed}\nreachable=true\nsummary=${drift.summary}\n`,
        { flag: "a" }
      );
    }
  } catch (err) {
    s.error("Upstream check failed");
    p.log.error(String(err instanceof Error ? err.message : err));
    process.exitCode = 1;
  }
}

/**
 * Draft the next changelog entry. Prints rather than writes: it is a draft to
 * edit into CHANGELOG.md, because a generated changelog nobody reads is how
 * "various fixes" happens.
 */
async function handleChangelog() {
  const { commitsSince, previousTag, corpusDiff, renderEntry } = await import("./changelog.js");
  const { describeSkill } = await import("./package.js");
  const { SKILL_SRC } = await import("./package.js");

  const prev = previousTag();
  const commits = commitsSince(prev);
  const version = JSON.parse(readFileSync(resolve("package.json"), "utf-8")).version as string;
  const m = describeSkill(resolve(SKILL_SRC), version);

  // Compare against the corpus the previous release shipped, read from its tag
  // rather than remembered.
  let before;
  if (prev) {
    try {
      const raw = execFileSync(
        "git", ["show", `${prev}:.claude/skills/rules-report/data/cards.json`],
        { encoding: "utf-8", maxBuffer: 64 * 1024 * 1024 }
      );
      const cards = JSON.parse(raw) as Record<string, { name: string; errata?: string; incomplete?: string }>;
      const seen = new Map(Object.values(cards).map((c) => [c.name, c]));
      const rules = JSON.parse(
        execFileSync("git", ["show", `${prev}:.claude/skills/rules-report/data/rules.json`],
          { encoding: "utf-8", maxBuffer: 64 * 1024 * 1024 })
      ) as Array<{ version: string }>;
      before = {
        rules_version: rules[0]?.version ?? "unknown",
        rules: rules.length,
        cards: seen.size,
        errata_applied: [...seen.values()].filter((c) => c.errata).length,
        cards_awaiting_transcription: [...seen.values()].filter((c) => c.incomplete).length,
      };
    } catch {
      // Previous tag predates the vendored corpus; report absolutes instead.
    }
  }

  const now = {
    rules_version: m.rules_version,
    rules: m.rules,
    cards: m.cards,
    errata_applied: 0,
    cards_awaiting_transcription: m.cards_awaiting_transcription,
  };
  const cards = JSON.parse(
    readFileSync(resolve(`${SKILL_DATA_DIR}/cards.json`), "utf-8")
  ) as Record<string, { name: string; errata?: string }>;
  now.errata_applied = new Set(
    Object.values(cards).filter((c) => c.errata).map((c) => c.name)
  ).size;

  const date = new Date().toISOString().slice(0, 10);
  p.log.info(`${commits.length} commit(s) since ${prev ?? "the beginning"}`);
  p.log.message(renderEntry(version, date, commits, corpusDiff(now, before)));
}

/** Build the archives a release attaches and a non-building agent installs. */
async function handlePackage() {
  const { packageAll, packageSkill, SKILLS } = await import("./package.js");
  const only = process.argv.find((a) => a.startsWith("--skill="))?.split("=")[1];
  if (only && !(only in SKILLS)) {
    p.log.error(`Unknown skill ${only} — known: ${Object.keys(SKILLS).join(", ")}`);
    process.exitCode = 1;
    return;
  }

  const s = p.spinner();
  s.start(only ? `Packaging ${only}` : "Packaging every shipping skill");
  try {
    // A release carries every shipping skill or it carries none. Packaging was
    // hardcoded to rules-report while a second skill shipped in the same repo,
    // so that skill had no release archive and `install.sh` could not fetch it.
    const results = only ? [packageSkill({ skill: only })] : packageAll();
    s.stop(`${results.length} archive(s)`);

    for (const r of results) {
      p.log.success(
        `${r.skill}  ${Math.round(r.bytes / 1024)}KB → ${color.cyan(r.archive)}`
      );
      const m = r.manifest;
      const facts = [
        m.rules_version ? `rules ${m.rules_version}` : null,
        m.rules ? `${m.rules} rules` : null,
        `${m.cards} cards`,
        m.gauntlet_decks !== undefined ? `${m.gauntlet_decks} gauntlet decks` : null,
        m.gauntlet_pulled ? `pulled ${m.gauntlet_pulled}` : null,
      ].filter(Boolean);
      p.log.info(`  ${facts.join(" · ")}`);
      if (m.cards_awaiting_transcription) {
        p.log.warning(
          `  ${m.cards_awaiting_transcription} card(s) still awaiting transcription ` +
            `(${color.cyan("oracle gear-gaps")})`
        );
      }
      p.log.message(`  sha256  ${r.sha256}`);
    }
  } catch (err) {
    s.error("Packaging failed");
    p.log.error(String(err instanceof Error ? err.message : err));
    process.exitCode = 1;
  }
}

async function handleGearGaps() {
  const { findGaps, collectGaps, loadOverlays } = await import("./gear-gaps.js");
  const index = JSON.parse(
    readFileSync(resolve(`${SKILL_DATA_DIR}/cards.json`), "utf-8")
  );
  const gaps = findGaps(index, loadOverlays());
  if (!gaps.length) {
    p.log.success("No cards are missing text — nothing to transcribe.");
    return;
  }

  const s = p.spinner();
  s.start(`Collecting artwork for ${gaps.length} card(s)`);
  const result = await collectGaps(gaps, { onProgress: (m) => s.message(`Fetching ${m}`) });
  s.stop(`${result.saved}/${result.gaps} image(s) → ${color.cyan(result.dir)}`);
  if (result.failed.length) {
    p.log.warning(`${result.failed.length} image(s) unavailable: ${result.failed.join(", ")}`);
  }
  p.log.info(
    `Fill in ${color.cyan(`${result.dir}/overlay-stub.yaml`)} from the images, then move the ` +
      `completed entries into ${color.cyan("manifests/card-overlays.yaml")} and re-run ` +
      color.cyan("skill-data")
  );
}

async function handleSkillData() {
  const s = p.spinner();
  s.start("Fetching card data for the skill");
  try {
    const result = await buildSkillData({ onProgress: (m) => s.message(`Fetching ${m}`) });
    s.stop(
      `${result.cards} cards → ${result.keys} lookup names ` +
        `(${result.withArt} with artwork) → ` +
        result.outputPaths.map((path) => color.cyan(path)).join(", ")
    );
    if (result.withArt === 0) {
      p.log.warning("No artwork URLs returned — reports will render placeholders");
    }
    // Equipment gear prints its granted effect only on the artwork, so the
    // gap is named rather than left to be discovered in a report.
    if (result.errataApplied) {
      p.log.info(
        `${result.errataApplied} card(s) corrected from Riot errata ` +
          `(${result.errataAvailable} errata in the rules corpus)`
      );
    } else if (!result.errataAvailable) {
      p.log.warning(
        "No errata found in output/rules.md — run " +
          `${color.cyan("oracle process -- --only=rules")} first, or card text may be stale`
      );
    }
    if (result.stillMissing.length) {
      p.log.warning(
        `${result.stillMissing.length} card(s) still missing text the API does not carry. ` +
          `Transcribe from the artwork into ${color.cyan("manifests/card-overlays.yaml")}:`
      );
      p.log.message(result.stillMissing.join(", "));
    } else if (result.overlaid) {
      p.log.info(`${result.overlaid} card overlay(s) applied; no gaps remain`);
    }
  } catch (err) {
    s.error("skill-data failed — the committed cards.json is unchanged");
    p.log.error(String(err));
  }
}

/**
 * Refresh the gauntlet a deck under construction is tested against.
 *
 * Run on demand, never on a schedule — the same etiquette the Rules Hub
 * processor follows. See docs/content-and-licensing.md.
 */
async function handleDecks() {
  if (process.argv[3] && process.argv[3] !== "pull") {
    p.log.error(`Unknown decks subcommand: ${process.argv[3]}`);
    return;
  }
  const limitArg = process.argv.find((a) => a.startsWith("--limit="))?.split("=")[1];
  const s = p.spinner();
  s.start("Pulling competitive decklists");
  try {
    const result = await pullMetaDecks({
      limit: limitArg ? Number.parseInt(limitArg, 10) : undefined,
      onProgress: (m) => s.message(m),
    });
    s.stop(`${result.decks.length} deck(s) → ${result.written.length} file(s)`);
    // A quarantined deck is a hole in the gauntlet with a name on it, which is
    // the point — the alternative is a half-parsed list overwriting a good one.
    if (result.quarantined.length) {
      p.log.error(`${result.quarantined.length} deck(s) NOT written — the page did not parse cleanly:`);
      for (const q of result.quarantined) {
        p.log.message(`${q.name}\n  ${q.reasons.join("\n  ")}`);
      }
    }
    const meta = result.decks.filter((d) => d.source?.meta).length;
    p.log.info(`${meta} flagged as tournament/meta lists by the source`);
    // A deck whose Chosen Champion did not resolve is still written, because a
    // gauntlet entry with a named gap is more useful than a missing one — but
    // it cannot be played until the field is filled in by hand.
    if (result.warnings.length) {
      p.log.warning(`${result.warnings.length} warning(s):`);
      p.log.message(result.warnings.join("\n"));
    }
  } catch (err) {
    s.error("decks pull failed — committed decks are unchanged");
    p.log.error(String(err instanceof Error ? err.message : err));
  }
}

async function handleVaultSync() {
  const s = p.spinner();

  let vaultDir: string;
  try {
    vaultDir = resolveVaultDir();
  } catch (err) {
    p.log.error(String(err instanceof Error ? err.message : err));
    return;
  }

  s.start(`Syncing output into ${vaultDir}`);

  try {
    const result = await syncToVault({
      vaultDir,
      onProgress: (msg) => s.message(`Syncing — ${msg}`),
    });

    s.stop(
      `${result.written.length} file(s) updated, ${result.unchanged.length} already current`
    );

    for (const name of result.written) {
      p.log.info(`  ${color.green("↑")} ${name}`);
    }
    if (result.unchanged.length > 0) {
      p.log.message(color.dim(`  unchanged: ${result.unchanged.join(", ")}`));
    }
    if (result.written.length > 0) {
      p.log.message(
        `\nNext: ask an agent to ingest the changed sources into ${color.cyan("pages/")}.`
      );
    }
  } catch (err) {
    s.error("Vault sync failed");
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

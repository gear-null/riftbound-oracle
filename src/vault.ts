/**
 * Sync processed output into an Obsidian vault's LLM-wiki `raw/` folder.
 *
 * The wiki treats `raw/` as its immutable source layer: pages cite it, and the
 * ingest step reads from it. Keeping it in sync by hand means the wiki quietly
 * drifts from the pipeline, so this makes the vault a first-class target of a
 * processing run.
 *
 * PDFs are extracted to text on the way in, because the wiki cites readable
 * source and a binary PDF cannot be quoted or verified against.
 */
import { readFileSync, writeFileSync, mkdirSync, existsSync, readdirSync } from "node:fs";
import { resolve, join, basename, extname } from "node:path";
import { extractPdfText } from "./processors/pdf.js";
import { normalize } from "./normalize.js";

export interface VaultSyncResult {
  written: string[];
  unchanged: string[];
}

export interface VaultSyncOptions {
  vaultDir: string;
  outputDir?: string;
  onProgress?: (message: string) => void;
  /** Injectable for tests so the suite never shells out to Python. */
  extractPdf?: (absolutePath: string, onProgress: (m: string) => void) => Promise<string>;
}

/**
 * Drop the `generated:` frontmatter line so two renders of identical source
 * compare equal. Without this every sync rewrites every file purely because
 * the date advanced, which would bury the real diffs we care about.
 */
export function stripGeneratedDate(markdown: string): string {
  return markdown.replace(/^generated:.*$\n?/m, "");
}

/** True when the target already holds this content, ignoring the render date. */
function isCurrent(targetPath: string, nextContent: string): boolean {
  if (!existsSync(targetPath)) return false;
  const existing = readFileSync(targetPath, "utf-8");
  return stripGeneratedDate(existing) === stripGeneratedDate(nextContent);
}

/**
 * Resolve the vault's raw directory from the environment.
 *
 * Deliberately has no default: this points at a personal Obsidian vault, so a
 * wrong guess would scatter files somewhere unexpected.
 */
export function resolveVaultDir(): string {
  const dir = process.env.VAULT_RAW_DIR;
  if (!dir || !dir.trim()) {
    throw new Error(
      "VAULT_RAW_DIR is not set.\n" +
        "Point it at your wiki's raw source folder, e.g.\n" +
        '  VAULT_RAW_DIR="/Users/you/Obsidian/Wiki/raw/riftbound"'
    );
  }
  return dir.trim();
}

/**
 * Copy every processed artifact in `outputDir` into `vaultDir`.
 *
 * Only ever creates or updates — never deletes. The wiki's `raw/` may hold
 * curated sources this pipeline doesn't manage, and removing those would
 * silently break the pages citing them.
 */
export async function syncToVault(opts: VaultSyncOptions): Promise<VaultSyncResult> {
  const outputDir = resolve(opts.outputDir ?? "output");
  const vaultDir = resolve(opts.vaultDir);
  const onProgress = opts.onProgress ?? (() => {});
  const extractPdf = opts.extractPdf ?? extractPdfText;

  if (!existsSync(outputDir)) {
    throw new Error(`Output directory not found: ${outputDir}`);
  }

  mkdirSync(vaultDir, { recursive: true });

  const sources = readdirSync(outputDir)
    .filter((name) => [".md", ".pdf"].includes(extname(name).toLowerCase()))
    .sort();

  const written: string[] = [];
  const unchanged: string[] = [];

  for (const name of sources) {
    const sourcePath = join(outputDir, name);
    const isPdf = extname(name).toLowerCase() === ".pdf";
    const targetName = `${basename(name, extname(name))}.md`;
    const targetPath = join(vaultDir, targetName);

    onProgress(targetName);

    let content: string;
    if (isPdf) {
      const text = await extractPdf(sourcePath, (m) => onProgress(`${targetName} — ${m}`));
      content = normalize(text, "rules");
    } else {
      content = readFileSync(sourcePath, "utf-8");
    }

    if (isCurrent(targetPath, content)) {
      unchanged.push(targetName);
      continue;
    }

    writeFileSync(targetPath, content, "utf-8");
    written.push(targetName);
  }

  return { written, unchanged };
}

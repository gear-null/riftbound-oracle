/**
 * Package the skill as a distributable archive.
 *
 * The skill is the product, so shipping it should be one command rather than a
 * hand-assembled zip. This is also the artifact a GitHub release attaches, and
 * the thing an agent that cannot run a build step installs.
 *
 * Two properties matter beyond "it produces a file":
 *
 * REPRODUCIBLE. Zip records each entry's mtime, so archiving the same bytes
 * twice normally yields two different files and a meaningless checksum. Every
 * entry is stamped with one fixed timestamp, so identical content produces an
 * identical archive — a release checksum then means something, and a rebuild
 * that changes nothing is visibly a no-op.
 *
 * TRACEABLE. An installed skill is cut off from this repository, so it carries
 * a manifest recording what corpus it was built from: rules version, card and
 * rule counts, the commit, and how many cards are still awaiting transcription.
 *
 * That manifest is written into the SOURCE skill folder and committed, not
 * injected at package time. `npx skills add` installs straight from git and
 * never sees the archive, so a manifest that existed only inside the zip left
 * registry users with no way to tell which corpus they had.
 */
import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync, cpSync, readdirSync, statSync, utimesSync } from "node:fs";
import { createHash } from "node:crypto";
import { join, resolve } from "node:path";
import { tmpdir } from "node:os";

export const SKILL_SRC = ".claude/skills/rules-report";
export const DIST_DIR = "dist";

/** Build outputs and caches that must not travel with the skill. */
const EXCLUDE = new Set(["reports", "__pycache__", "rules.db", ".DS_Store"]);

/** Every entry gets this mtime so the archive is byte-stable. */
const FIXED_MTIME = new Date("2020-01-01T00:00:00Z");

export interface SkillManifest {
  name: string;
  version: string;
  built_from: string;
  rules_version: string;
  rules: number;
  cards: number;
  cards_awaiting_transcription: number;
  commit: string;
}

function gitCommit(): string {
  try {
    return execFileSync("git", ["rev-parse", "--short", "HEAD"], { encoding: "utf-8" }).trim();
  } catch {
    return "unknown";   // a tarball export has no git; not worth failing over
  }
}

/** Read the corpus the skill actually carries, so the manifest is not asserted. */
export function describeSkill(skillDir: string, version: string): SkillManifest {
  const rules = JSON.parse(readFileSync(join(skillDir, "data/rules.json"), "utf-8"));
  const cards = JSON.parse(readFileSync(join(skillDir, "data/cards.json"), "utf-8"));
  const names = new Set(Object.values(cards).map((c) => (c as { name: string }).name));
  const awaiting = new Set(
    Object.values(cards)
      .filter((c) => (c as { incomplete?: string }).incomplete)
      .map((c) => (c as { name: string }).name)
  );
  return {
    name: "rules-report",
    version,
    built_from: "https://github.com/gear-null/riftbound-oracle",
    rules_version: rules[0]?.version ?? "unknown",
    rules: rules.length,
    cards: names.size,
    cards_awaiting_transcription: awaiting.size,
    commit: gitCommit(),
  };
}

function stampRecursively(dir: string): void {
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) stampRecursively(path);
    utimesSync(path, FIXED_MTIME, FIXED_MTIME);
  }
  utimesSync(dir, FIXED_MTIME, FIXED_MTIME);
}

export interface PackageOptions {
  skillDir?: string;
  distDir?: string;
  version?: string;
}

export function packageSkill(opts: PackageOptions = {}) {
  const skillDir = resolve(opts.skillDir ?? SKILL_SRC);
  const distDir = resolve(opts.distDir ?? DIST_DIR);
  if (!existsSync(join(skillDir, "data/rules.json"))) {
    throw new Error(
      `No corpus at ${skillDir}/data — run \`npm run oracle skill-data\` and ` +
        "`rules_cli.py build` before packaging."
    );
  }

  const version =
    opts.version ??
    (JSON.parse(readFileSync(resolve("package.json"), "utf-8")).version as string);
  const manifest = describeSkill(skillDir, version);

  // Write it into the source tree so every channel carries it — git installs
  // included. It shows up in `git status` when the corpus moves, which is the
  // reminder to commit it.
  writeFileSync(
    join(skillDir, "SKILL-VERSION.json"),
    JSON.stringify(manifest, null, 2) + "\n",
    "utf-8"
  );

  const staging = mkdtempSync(join(tmpdir(), "skill-pkg-"));
  try {
    const root = join(staging, "rules-report");
    cpSync(skillDir, root, {
      recursive: true,
      filter: (src) => !EXCLUDE.has(src.split("/").pop() ?? ""),
    });
    stampRecursively(root);

    mkdirSync(distDir, { recursive: true });
    const archive = join(distDir, `riftbound-rules-report-v${version}.zip`);
    rmSync(archive, { force: true });
    // -X drops extra file attributes (uid/gid, timestamps beyond the entry's)
    // which would otherwise vary between machines.
    execFileSync("zip", ["-qrX", archive, "rules-report"], { cwd: staging });

    const bytes = readFileSync(archive);
    const sha = createHash("sha256").update(bytes).digest("hex");
    writeFileSync(`${archive}.sha256`, `${sha}  ${archive.split("/").pop()}\n`, "utf-8");

    return { archive, sha256: sha, bytes: bytes.length, manifest };
  } finally {
    rmSync(staging, { recursive: true, force: true });
  }
}

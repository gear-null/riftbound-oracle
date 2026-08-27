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
 *
 * It records no commit hash, deliberately. The manifest is committed, so a
 * hash of "the commit this was built from" is self-referential: building at A
 * writes A, committing that yields B, rebuilding writes B, and the archive can
 * never be reproduced from its own tag — which is the one thing reproducibility
 * is for. The version identifies the release and the tag identifies the commit.
 */
import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync, cpSync, readdirSync, statSync, utimesSync } from "node:fs";
import { createHash } from "node:crypto";
import { join, resolve } from "node:path";
import { tmpdir } from "node:os";

export const SKILL_SRC = ".claude/skills/rules-report";
export const DECK_LAB_SRC = ".claude/skills/deck-lab";
export const DIST_DIR = "dist";

/**
 * A skill that ships.
 *
 * The repo grew a second product — `deck-lab` — and packaging stayed hardcoded
 * to the first, so the CI job proving a registry install works covered one of
 * the two and `install.sh` could not fetch the other at all. Everything that
 * differs between them lives here: what corpus proves the folder is complete,
 * what the manifest should record, and which CLI proves the install works.
 */
export interface SkillSpec {
  name: string;
  dir: string;
  /** Files without which the folder is not a working skill. */
  requires: string[];
  /** How to rebuild the missing corpus, shown when `requires` fails. */
  buildHint: string;
  /** The selftest an installer runs to prove the copy works. */
  verify: string;
  describe(skillDir: string, version: string): SkillManifest;
}

export const SKILLS: Record<string, SkillSpec> = {
  "rules-report": {
    name: "rules-report",
    dir: SKILL_SRC,
    requires: ["data/rules.json", "data/cards.json"],
    buildHint: "npm run oracle skill-data && (cd .claude/skills/rules-report/lib && python3 rules_cli.py build)",
    verify: "rules_cli.py selftest",
    describe: describeRulesReport,
  },
  "deck-lab": {
    name: "deck-lab",
    dir: DECK_LAB_SRC,
    requires: ["data/cards.json", "gauntlet"],
    buildHint: "npm run oracle skill-data && npm run oracle decks pull",
    verify: "deck_cli.py selftest",
    describe: describeDeckLab,
  },
};

/** Build outputs and caches that must not travel with the skill. */
const EXCLUDE = new Set(["reports", "__pycache__", "rules.db", ".DS_Store"]);

/** Every entry gets this mtime so the archive is byte-stable. */
const FIXED_MTIME = new Date("2020-01-01T00:00:00Z");

export interface SkillManifest {
  name: string;
  version: string;
  built_from: string;
  cards: number;
  /** rules-report only. */
  rules_version?: string;
  rules?: number;
  cards_awaiting_transcription?: number;
  /** deck-lab only — a gauntlet of tournament lists goes stale on its own clock. */
  gauntlet_decks?: number;
  gauntlet_pulled?: string;
}

/**
 * rules-report's manifest, with its own fields required.
 *
 * The changelog diffs rule and card counts release to release, so those cannot
 * be optional at that call site even though the shared shape allows it.
 */
export interface RulesReportManifest extends SkillManifest {
  rules_version: string;
  rules: number;
  cards_awaiting_transcription: number;
}

/** Read the corpus the skill actually carries, so the manifest is not asserted. */
export function describeSkill(skillDir: string, version: string): RulesReportManifest {
  return describeRulesReport(skillDir, version);
}

function describeRulesReport(skillDir: string, version: string): RulesReportManifest {
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
  };
}

/**
 * What a deck-lab install actually carries.
 *
 * There is no rulebook here, so the traceable facts are different: how many
 * cards it can resolve, and how stale its gauntlet is. A gauntlet of tournament
 * decklists goes out of date on its own schedule, and an installed copy is cut
 * off from the repo that could tell it so — hence the pull date.
 */
function describeDeckLab(skillDir: string, version: string): SkillManifest {
  const cards = JSON.parse(readFileSync(join(skillDir, "data/cards.json"), "utf-8"));
  const names = new Set(Object.values(cards).map((c) => (c as { name: string }).name));

  const gauntletDir = join(skillDir, "gauntlet");
  const decks = existsSync(gauntletDir)
    ? readdirSync(gauntletDir).filter((f) => f.endsWith(".json"))
    : [];
  let pulled = "unknown";
  for (const file of decks) {
    const deck = JSON.parse(readFileSync(join(gauntletDir, file), "utf-8"));
    const fetched = deck?.source?.fetched;
    if (typeof fetched === "string" && (pulled === "unknown" || fetched > pulled)) pulled = fetched;
  }

  return {
    name: "deck-lab",
    version,
    built_from: "https://github.com/gear-null/riftbound-oracle",
    cards: names.size,
    gauntlet_decks: decks.length,
    gauntlet_pulled: pulled,
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
  /** Which skill to package. Defaults to rules-report for back-compatibility. */
  skill?: string;
  skillDir?: string;
  distDir?: string;
  version?: string;
}

export function packageSkill(opts: PackageOptions = {}) {
  const spec = SKILLS[opts.skill ?? "rules-report"];
  if (!spec) {
    throw new Error(
      `unknown skill ${JSON.stringify(opts.skill)} — known: ${Object.keys(SKILLS).join(", ")}`
    );
  }
  const skillDir = resolve(opts.skillDir ?? spec.dir);
  const distDir = resolve(opts.distDir ?? DIST_DIR);
  for (const needed of spec.requires) {
    if (!existsSync(join(skillDir, needed))) {
      throw new Error(
        `${spec.name} is missing ${needed} — run \`${spec.buildHint}\` before packaging.`
      );
    }
  }

  const version =
    opts.version ??
    (JSON.parse(readFileSync(resolve("package.json"), "utf-8")).version as string);
  const manifest = spec.describe(skillDir, version);

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
    const root = join(staging, spec.name);
    cpSync(skillDir, root, {
      recursive: true,
      filter: (src) => !EXCLUDE.has(src.split("/").pop() ?? ""),
    });
    // The licence travels WITH the archive. The zip and install.sh paths hand
    // someone the code without the repository around it, so without this they
    // receive an unlicensed copy — which is the state the licence was added to
    // end, and the state most likely to be redistributed further.
    const licence = resolve("LICENSE");
    if (existsSync(licence)) cpSync(licence, join(root, "LICENSE"));
    stampRecursively(root);

    mkdirSync(distDir, { recursive: true });
    const archive = join(distDir, `riftbound-${spec.name}-v${version}.zip`);
    rmSync(archive, { force: true });
    // -X drops extra file attributes (uid/gid, timestamps beyond the entry's)
    // which would otherwise vary between machines.
    execFileSync("zip", ["-qrX", archive, spec.name], { cwd: staging });

    const bytes = readFileSync(archive);
    const sha = createHash("sha256").update(bytes).digest("hex");
    writeFileSync(`${archive}.sha256`, `${sha}  ${archive.split("/").pop()}\n`, "utf-8");

    return { archive, sha256: sha, bytes: bytes.length, manifest, skill: spec.name };
  } finally {
    rmSync(staging, { recursive: true, force: true });
  }
}

/** Package every shipping skill. A release carries both or it carries neither. */
export function packageAll(opts: Omit<PackageOptions, "skill" | "skillDir"> = {}) {
  return Object.keys(SKILLS).map((skill) => packageSkill({ ...opts, skill }));
}

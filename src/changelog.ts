/**
 * Draft a changelog entry from the git history and the corpus.
 *
 * Why not changesets: it exists to coordinate versions across a monorepo, and
 * this is one package released roughly when Riot ships a set. Its ceremony
 * (a `.changeset/` file per PR) buys nothing here, and the history is already
 * conventional-commit shaped.
 *
 * Why not a plain conventional-commit generator either: for this project the
 * most important thing in a release usually is not a code change. "Rules
 * 2026-07-16 -> 2026-08-20, 12 rules renumbered, 28 cards corrected by errata"
 * is what a user needs to know, and no generic tool can derive it. So the
 * entry is commits AND a corpus diff, and the corpus half is computed from the
 * data rather than remembered by whoever cuts the release.
 *
 * Output is a draft. It is meant to be edited before shipping — a generated
 * changelog that nobody reads is how "various fixes" happens.
 */
import { execFileSync } from "node:child_process";

export interface Commit {
  type: string;
  scope?: string;
  breaking: boolean;
  subject: string;
  hash: string;
}

/** Conventional-commit types, in the order a reader cares about them. */
const SECTIONS: Array<[string, string]> = [
  ["feat", "Added"],
  ["fix", "Fixed"],
  ["perf", "Performance"],
  ["refactor", "Changed"],
  ["docs", "Documentation"],
  ["test", "Tests"],
  ["build", "Build"],
  ["ci", "CI"],
  ["chore", "Chores"],
];

const CONVENTIONAL = /^(\w+)(?:\(([^)]+)\))?(!)?:\s*(.+)$/;

export function parseCommit(line: string): Commit | null {
  const [hash, ...rest] = line.split(" ");
  const subject = rest.join(" ");
  const m = CONVENTIONAL.exec(subject);
  if (!m) return { type: "other", breaking: false, subject, hash };
  return { type: m[1], scope: m[2], breaking: Boolean(m[3]), subject: m[4], hash };
}

export function commitsSince(ref?: string): Commit[] {
  const range = ref ? `${ref}..HEAD` : "HEAD";
  const out = execFileSync("git", ["log", "--no-merges", "--pretty=%h %s", range], {
    encoding: "utf-8",
  }).trim();
  if (!out) return [];
  return out.split("\n").map(parseCommit).filter((c): c is Commit => c !== null);
}

export function previousTag(): string | undefined {
  try {
    return execFileSync("git", ["describe", "--tags", "--abbrev=0"], {
      encoding: "utf-8",
    }).trim() || undefined;
  } catch {
    return undefined;   // no tags yet: the first release covers everything
  }
}

export interface CorpusStats {
  rules_version: string;
  rules: number;
  cards: number;
  errata_applied: number;
  cards_awaiting_transcription: number;
}

/** The half of a release note that no commit message contains. */
export function corpusDiff(now: CorpusStats, before?: CorpusStats): string[] {
  const lines: string[] = [];
  const delta = (a: number, b?: number) =>
    b === undefined || a === b ? "" : ` (${a > b ? "+" : ""}${a - b})`;

  if (!before) {
    lines.push(
      `Rules **${now.rules_version}** — ${now.rules} rules, ${now.cards} cards.`
    );
  } else {
    if (now.rules_version !== before.rules_version) {
      lines.push(
        `Rules updated **${before.rules_version} → ${now.rules_version}**` +
          ` — ${now.rules} rules${delta(now.rules, before.rules)}.`
      );
    }
    if (now.cards !== before.cards) {
      lines.push(`Card pool now ${now.cards}${delta(now.cards, before.cards)}.`);
    }
  }
  if (now.errata_applied) {
    lines.push(
      `${now.errata_applied} card(s) corrected from Riot errata` +
        (before ? delta(now.errata_applied, before.errata_applied) : "") + "."
    );
  }
  if (now.cards_awaiting_transcription) {
    lines.push(
      `${now.cards_awaiting_transcription} equipment card(s) still awaiting transcription ` +
        "— their granted effect is not in the source data."
    );
  }
  return lines;
}

export function renderEntry(
  version: string,
  date: string,
  commits: Commit[],
  corpus: string[]
): string {
  const out = [`## [${version}] — ${date}`, ""];

  if (corpus.length) {
    out.push("### Corpus", "");
    for (const line of corpus) out.push(`- ${line}`);
    out.push("");
  }

  const breaking = commits.filter((c) => c.breaking);
  if (breaking.length) {
    out.push("### Breaking", "");
    for (const c of breaking) out.push(`- ${c.subject} (${c.hash})`);
    out.push("");
  }

  for (const [type, heading] of SECTIONS) {
    const group = commits.filter((c) => c.type === type && !c.breaking);
    if (!group.length) continue;
    out.push(`### ${heading}`, "");
    for (const c of group) {
      out.push(`- ${c.scope ? `**${c.scope}:** ` : ""}${c.subject} (${c.hash})`);
    }
    out.push("");
  }

  const other = commits.filter(
    (c) => c.type === "other" && !c.breaking
  );
  if (other.length) {
    out.push("### Other", "");
    for (const c of other) out.push(`- ${c.subject} (${c.hash})`);
    out.push("");
  }

  return out.join("\n");
}

import { describe, it, expect } from "vitest";
import { execFileSync } from "node:child_process";
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync, existsSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { describeSkill, packageSkill, packageAll, SKILLS } from "../package.js";

function fakeSkill(dir: string, over: Record<string, unknown> = {}) {
  mkdirSync(join(dir, "data"), { recursive: true });
  mkdirSync(join(dir, "lib"), { recursive: true });
  mkdirSync(join(dir, "reports"), { recursive: true });
  mkdirSync(join(dir, "lib", "__pycache__"), { recursive: true });
  writeFileSync(join(dir, "SKILL.md"), "---\nname: x\n---\n");
  writeFileSync(join(dir, "lib", "rules_cli.py"), "print('hi')\n");
  writeFileSync(join(dir, "lib", "rules.db"), "binary");
  writeFileSync(join(dir, "reports", "old.html"), "<html></html>");
  writeFileSync(join(dir, "lib", "__pycache__", "x.pyc"), "cached");
  writeFileSync(join(dir, "data", "rules.json"),
    JSON.stringify([{ id: "1", version: "2026-07-16" }, { id: "2", version: "2026-07-16" }]));
  writeFileSync(join(dir, "data", "cards.json"), JSON.stringify({
    "a": { name: "Alpha" },
    "alpha": { name: "Alpha" },                         // alias of the same card
    "b": { name: "Beta", incomplete: "granted ability missing" },
    ...over,
  }));
}

describe("describeSkill", () => {
  it("reports the corpus it actually carries, counting cards not aliases", () => {
    const dir = mkdtempSync(join(tmpdir(), "sk-"));
    try {
      fakeSkill(dir);
      const m = describeSkill(dir, "9.9.9");
      expect(m.rules).toBe(2);
      expect(m.cards).toBe(2);                          // Alpha counted once
      expect(m.cards_awaiting_transcription).toBe(1);
      expect(m.rules_version).toBe("2026-07-16");
      expect(m.version).toBe("9.9.9");
    } finally { rmSync(dir, { recursive: true }); }
  });
});

describe("packageSkill", () => {
  it("records nothing self-referential, so a release reproduces from its tag", () => {
    // A commit hash here cannot be stable: the manifest is committed, so
    // building at A writes A, committing yields B, rebuilding writes B. The
    // archive could then never be rebuilt from its own tag.
    const dir = mkdtempSync(join(tmpdir(), "sk-"));
    try {
      fakeSkill(dir);
      const m = describeSkill(dir, "1.2.3") as unknown as Record<string, unknown>;
      expect(m).not.toHaveProperty("commit");
      expect(JSON.stringify(m)).not.toMatch(/\b[0-9a-f]{7,40}\b/);
      // and it is a pure function of the corpus + version
      expect(describeSkill(dir, "1.2.3")).toEqual(m);
    } finally { rmSync(dir, { recursive: true }); }
  });

  it("records nothing self-referential in ANY skill's manifest", () => {
    // The test above predates the second skill and calls one producer through
    // `describeSkill`. Splitting manifest generation in two left the other
    // producer outside the invariant: a commit hash added to deck-lab's
    // manifest passed the whole suite, with its SKILL-VERSION.json committed
    // and the instability therefore fully reachable. An invariant that covers
    // half the producers is not an invariant, and the count of producers is
    // exactly the thing that changed.
    //
    // Run against the real skill dirs rather than a fixture: these are the
    // manifests that actually ship, and purity has to hold for the corpus we
    // have, not a synthetic one.
    for (const [key, spec] of Object.entries(SKILLS)) {
      const m = spec.describe(spec.dir, "1.2.3") as unknown as Record<string, unknown>;
      expect(m, `${key} records a commit`).not.toHaveProperty("commit");
      expect(JSON.stringify(m), `${key} records something hash-shaped`)
        .not.toMatch(/\b[0-9a-f]{7,40}\b/);
      expect(spec.describe(spec.dir, "1.2.3"), `${key} is not a pure function of its corpus`)
        .toEqual(m);
    }
  });

  it("is byte-reproducible across builds", () => {
    // A release checksum is meaningless if archiving identical bytes twice
    // yields two different files.
    const src = mkdtempSync(join(tmpdir(), "sk-"));
    const out = mkdtempSync(join(tmpdir(), "dist-"));
    try {
      fakeSkill(src);
      const a = packageSkill({ skillDir: src, distDir: out, version: "1.2.3" });
      const b = packageSkill({ skillDir: src, distDir: out, version: "1.2.3" });
      expect(b.sha256).toBe(a.sha256);
      expect(readFileSync(`${a.archive}.sha256`, "utf-8")).toContain(a.sha256);
    } finally { rmSync(src, { recursive: true }); rmSync(out, { recursive: true }); }
  });

  it("leaves build artifacts and stale reports out of the archive", () => {
    const src = mkdtempSync(join(tmpdir(), "sk-"));
    const out = mkdtempSync(join(tmpdir(), "dist-"));
    try {
      fakeSkill(src);
      const { archive } = packageSkill({ skillDir: src, distDir: out, version: "1.2.3" });
      const listing = readFileSync(archive).toString("latin1");
      expect(listing).toContain("rules-report/SKILL.md");
      expect(listing).toContain("SKILL-VERSION.json");
      expect(listing).not.toContain("rules.db");
      expect(listing).not.toContain("__pycache__");
      expect(listing).not.toContain("old.html");
    } finally { rmSync(src, { recursive: true }); rmSync(out, { recursive: true }); }
  });

  it("ships the licence inside EVERY archive", () => {
    // The zip and install.sh hand someone the code WITHOUT the repository
    // around it. Without this they receive an unlicensed copy — the exact
    // state the licence was added to end, in the path most likely to be
    // redistributed onward.
    //
    // Written first against rules-report alone, by name, while it was the only
    // skill. That made it the third place in this packaging path to check the
    // first of N and report on all of them: a second skill could ship
    // unlicensed with this test still green. It loops now, so a skill is
    // covered the day it is added.
    const out = mkdtempSync(join(tmpdir(), "dist-"));
    try {
      const built = packageAll({ distDir: out, version: "9.9.9" });
      expect(built.length).toBe(Object.keys(SKILLS).length);
      for (const { archive, skill } of built) {
        const list = execFileSync("unzip", ["-Z1", archive], { encoding: "utf-8" });
        expect(list, `${skill} shipped without a licence`).toContain(`${skill}/LICENSE`);
      }
    } finally { rmSync(out, { recursive: true, force: true }); }
  });

  it("refuses to package at all when the licence is missing", () => {
    // The guard this pins replaced an `existsSync` that skipped the copy
    // silently. Under it, a moved or renamed LICENSE reproduced the unlicensed
    // archive the licence work existed to end — with every other check green,
    // because nothing else in the build looks at the file.
    const out = mkdtempSync(join(tmpdir(), "dist-"));
    try {
      expect(() => packageSkill({ distDir: out, licencePath: join(out, "nope/LICENSE") }))
        .toThrow(/must carry one/);
      expect(existsSync(join(out, "riftbound-rules-report-v1.0.0.zip"))).toBe(false);
    } finally { rmSync(out, { recursive: true, force: true }); }
  });

  it("leaves the committed manifests alone when packaging at a throwaway version", () => {
    // Packaging rewrites each skill's SKILL-VERSION.json on purpose, so the
    // committed one tracks the corpus. A TEST doing it is a trap: the suite
    // dirties tracked files, a `git add -A` sweeps them in, and CI then fails
    // on a stale manifest nobody knowingly edited. That happened once.
    //
    // Note what is NOT passed below: the safety is the default, so a packaging
    // test written later that has never heard of this flag is safe by writing
    // nothing. That is the point — this check would otherwise only catch the
    // authors who already knew.
    const before = Object.values(SKILLS).map(
      (spec) => readFileSync(join(spec.dir, "SKILL-VERSION.json"), "utf-8"));
    const out = mkdtempSync(join(tmpdir(), "dist-"));
    try {
      packageAll({ distDir: out, version: "9.9.9" });
      const after = Object.values(SKILLS).map(
        (spec) => readFileSync(join(spec.dir, "SKILL-VERSION.json"), "utf-8"));
      expect(after).toEqual(before);
    } finally { rmSync(out, { recursive: true, force: true }); }
  });

  it("states the packaged version in the archive's manifest regardless", () => {
    // The archive's manifest must describe the build it is in, even when the
    // source tree was deliberately left untouched — otherwise turning off the
    // source write would silently ship whatever version was committed last.
    const out = mkdtempSync(join(tmpdir(), "dist-"));
    const unpacked = mkdtempSync(join(tmpdir(), "unz-"));
    try {
      packageAll({ distDir: out, version: "9.9.9" });
      for (const spec of Object.values(SKILLS)) {
        execFileSync("unzip", ["-qo", join(out, `riftbound-${spec.name}-v9.9.9.zip`),
                               "-d", unpacked]);
        const shipped = JSON.parse(
          readFileSync(join(unpacked, spec.name, "SKILL-VERSION.json"), "utf-8"));
        expect(shipped.version, `${spec.name}'s archive states the wrong version`).toBe("9.9.9");
      }
    } finally {
      rmSync(out, { recursive: true, force: true });
      rmSync(unpacked, { recursive: true, force: true });
    }
  });

  it("still updates the committed manifest when the CLI asks it to", () => {
    // The flip side of the safe default: `oracle package` is the one caller
    // that MUST write into the source tree, because CI's stale-manifest check
    // and every git install depend on that file tracking the corpus. Making the
    // default safe is only correct if the opt-in still works — otherwise the
    // manifest quietly stops being maintained and nothing says so.
    const dir = mkdtempSync(join(tmpdir(), "sk-"));
    const out = mkdtempSync(join(tmpdir(), "dist-"));
    try {
      fakeSkill(dir);
      rmSync(join(dir, "SKILL-VERSION.json"), { force: true });
      packageSkill({ skillDir: dir, distDir: out, version: "4.5.6",
                     updateSourceManifest: true });
      const written = JSON.parse(readFileSync(join(dir, "SKILL-VERSION.json"), "utf-8"));
      expect(written.version).toBe("4.5.6");
    } finally {
      rmSync(dir, { recursive: true, force: true });
      rmSync(out, { recursive: true, force: true });
    }
  });

  it("ships a runnable verify command in every skill's manifest", () => {
    // CI installs each archive and runs the command the manifest names, so a
    // skill whose manifest omits it — or names a file the archive does not
    // carry — would be published untested. That is not hypothetical: one
    // `unzip dist/*.zip` used to take the first archive and read the second as
    // a member name inside it, so deck-lab shipped for a while with its
    // selftest never once run against a packaged copy.
    for (const [key, spec] of Object.entries(SKILLS)) {
      const manifest = spec.describe(spec.dir, "1.2.3");
      expect(manifest.verify, `${key} has no verify command`).toBeTruthy();
      const [interpreter, script] = manifest.verify.split(" ");
      expect(interpreter, `${key}'s verify must name its interpreter`).toBe("python3");
      expect(existsSync(join(spec.dir, "lib", script)),
        `${key}'s verify names lib/${script}, which is not in the skill`).toBe(true);
    }
  });

  it("refuses to package a skill with no corpus", () => {
    // Shipping an empty skill is worse than failing the build.
    const src = mkdtempSync(join(tmpdir(), "sk-"));
    const out = mkdtempSync(join(tmpdir(), "dist-"));
    try {
      mkdirSync(join(src, "data"), { recursive: true });
      expect(() => packageSkill({ skillDir: src, distDir: out })).toThrow(/skill-data/);
      expect(existsSync(join(out, "riftbound-rules-report-v1.0.0.zip"))).toBe(false);
    } finally { rmSync(src, { recursive: true }); rmSync(out, { recursive: true }); }
  });
});

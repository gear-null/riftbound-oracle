import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { SKILL_SRC, SKILLS } from "../package.js";

const SH = readFileSync("install.sh", "utf-8");

describe("install.sh", () => {
  it("asks for the asset name that package.ts actually produces", () => {
    // Renaming the archive breaks the installer for everyone at once, and
    // nothing else connects the two.
    const version = JSON.parse(readFileSync("package.json", "utf-8")).version;
    const pattern = SH.match(/ASSET="([^"]+)"/)![1];
    for (const skill of Object.keys(SKILLS)) {
      const resolved = pattern.replace("$SKILL", skill).replace("$VERSION", `v${version}`);
      expect(resolved).toBe(`riftbound-${skill}-v${version}.zip`);
    }
  });

  it("installs every skill the packager ships", () => {
    // The drift this exists to catch: a second skill was added to the repo and
    // packaging stayed hardcoded to the first, so one of the two had no release
    // archive and the installer could not fetch it at all.
    const listed = SH.match(/^SKILLS="([^"]+)"/m)![1].split(/\s+/);
    expect(listed.sort()).toEqual(Object.keys(SKILLS).sort());
    expect(SKILL_SRC.endsWith("rules-report")).toBe(true);
  });

  it("knows how to verify each skill it installs", () => {
    // A skill in the list with no selftest mapping would install unverified.
    for (const skill of Object.keys(SKILLS)) {
      // Tolerate the column alignment in the case statement.
      const branch = new RegExp(`^\\s*${skill}\\)\\s+echo "\\S+\\.py"`, "m");
      expect(SH, `${skill} has no selftest_for branch`).toMatch(branch);
    }
  });

  it("is POSIX sh, not bash", () => {
    // It runs under dash and busybox on machines we do not control.
    expect(SH.startsWith("#!/bin/sh")).toBe(true);
    expect(SH).not.toMatch(/\[\[|\bfunction \w+\(|<<</);
  });

  it("refuses to proceed on a checksum mismatch", () => {
    // The whole point of publishing a .sha256 is that something checks it.
    expect(SH).toMatch(/checksum mismatch/);
    expect(SH).toMatch(/"\$ACTUAL" != "\$EXPECTED"/);
    expect(SH.indexOf("checksum mismatch")).toBeLessThan(SH.indexOf("unzip -q"));
  });

  it("verifies the install by running the selftest", () => {
    expect(SH).toMatch(/"\$CLI" selftest/);
    expect(SH).toMatch(/not trustworthy/);
  });

  it("checks the Python floor before downloading anything", () => {
    expect(SH).toContain("(3,9)");
    expect(SH.indexOf("version_info")).toBeLessThan(SH.indexOf("curl -fsSL \"$BASE/$ASSET\""));
  });

  it("refuses an existing install before spending a download on it", () => {
    expect(SH.indexOf("already exists")).toBeLessThan(SH.indexOf('curl -fsSL "$BASE/$ASSET"'));
  });

  it("parses its options and rejects unknown ones", () => {
    const help = execFileSync("sh", ["install.sh", "--help"], { encoding: "utf-8" });
    for (const flag of ["--skill", "--dir", "--version", "--force", "--no-verify"]) {
      expect(help).toContain(flag);
    }
    expect(() => execFileSync("sh", ["install.sh", "--bogus"], { stdio: "pipe" })).toThrow();
  });
});

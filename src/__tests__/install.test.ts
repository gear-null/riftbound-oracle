import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { SKILL_SRC } from "../package.js";

const SH = readFileSync("install.sh", "utf-8");

describe("install.sh", () => {
  it("asks for the asset name that package.ts actually produces", () => {
    // Renaming the archive breaks the installer for everyone at once, and
    // nothing else connects the two.
    const version = JSON.parse(readFileSync("package.json", "utf-8")).version;
    const expected = `riftbound-rules-report-v${version}.zip`;
    const pattern = SH.match(/ASSET="([^"]+)"/)![1].replace("$VERSION", `v${version}`);
    expect(pattern).toBe(expected);
  });

  it("installs the skill folder the archive actually contains", () => {
    // package.ts stages the skill under `rules-report/`; the installer asserts
    // that directory exists after unzipping.
    expect(SH).toContain('SKILL="rules-report"');
    expect(SKILL_SRC.endsWith("rules-report")).toBe(true);
  });

  it("is POSIX sh, not bash", () => {
    // It runs under dash and busybox on machines we do not control.
    expect(SH.startsWith("#!/bin/sh")).toBe(true);
    expect(SH).not.toMatch(/\[\[|\bfunction \w+\(|<<</);
  });

  it("refuses to proceed on a checksum mismatch", () => {
    // The whole point of publishing a .sha256 is that something checks it.
    expect(SH).toMatch(/checksum mismatch/);
    expect(SH).toMatch(/\[ "\$ACTUAL" = "\$EXPECTED" \] \|\| die/);
  });

  it("verifies the install by running the selftest", () => {
    expect(SH).toContain("rules_cli.py selftest");
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
    for (const flag of ["--dir", "--version", "--force", "--no-verify"]) {
      expect(help).toContain(flag);
    }
    expect(() => execFileSync("sh", ["install.sh", "--bogus"], { stdio: "pipe" })).toThrow();
  });
});

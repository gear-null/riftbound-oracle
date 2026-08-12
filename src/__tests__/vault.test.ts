import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { syncToVault, stripGeneratedDate, resolveVaultDir } from "../vault.js";

let root: string;
let outputDir: string;
let vaultDir: string;

function md(body: string, generated = "2026-08-06"): string {
  return `---\ncategory: cards\ngenerated: ${generated}\ngenerator: riftbound-oracle\n---\n\n${body}\n`;
}

beforeEach(() => {
  root = mkdtempSync(join(tmpdir(), "vault-test-"));
  outputDir = join(root, "output");
  vaultDir = join(root, "vault");
  mkdirSync(outputDir, { recursive: true });
});

afterEach(() => {
  rmSync(root, { recursive: true, force: true });
});

describe("stripGeneratedDate", () => {
  it("removes only the generated line", () => {
    const stripped = stripGeneratedDate(md("# Vendetta"));
    expect(stripped).not.toContain("generated:");
    expect(stripped).toContain("category: cards");
    expect(stripped).toContain("# Vendetta");
  });

  it("makes two renders of the same source compare equal", () => {
    expect(stripGeneratedDate(md("# Vendetta", "2026-08-06"))).toBe(
      stripGeneratedDate(md("# Vendetta", "2026-01-01"))
    );
  });
});

describe("syncToVault", () => {
  it("creates the vault directory and copies markdown across", async () => {
    writeFileSync(join(outputDir, "cards-ven.md"), md("# Vendetta"));

    const result = await syncToVault({ outputDir, vaultDir });

    expect(result.written).toEqual(["cards-ven.md"]);
    expect(readFileSync(join(vaultDir, "cards-ven.md"), "utf-8")).toContain("# Vendetta");
  });

  it("reports a file as unchanged when only the generated date moved", async () => {
    writeFileSync(join(outputDir, "cards-ven.md"), md("# Vendetta", "2026-01-01"));
    await syncToVault({ outputDir, vaultDir });

    // Same substance, re-rendered today — must not count as a change.
    writeFileSync(join(outputDir, "cards-ven.md"), md("# Vendetta", "2026-08-06"));
    const result = await syncToVault({ outputDir, vaultDir });

    expect(result.unchanged).toEqual(["cards-ven.md"]);
    expect(result.written).toEqual([]);
  });

  it("leaves the existing file untouched when nothing of substance changed", async () => {
    writeFileSync(join(outputDir, "cards-ven.md"), md("# Vendetta", "2026-01-01"));
    await syncToVault({ outputDir, vaultDir });

    writeFileSync(join(outputDir, "cards-ven.md"), md("# Vendetta", "2026-08-06"));
    await syncToVault({ outputDir, vaultDir });

    // The vault keeps its original date rather than churning on every run.
    expect(readFileSync(join(vaultDir, "cards-ven.md"), "utf-8")).toContain("generated: 2026-01-01");
  });

  it("rewrites the file when the content genuinely changed", async () => {
    writeFileSync(join(outputDir, "cards-ven.md"), md("**Total cards:** 357"));
    await syncToVault({ outputDir, vaultDir });

    writeFileSync(join(outputDir, "cards-ven.md"), md("**Total cards:** 358"));
    const result = await syncToVault({ outputDir, vaultDir });

    expect(result.written).toEqual(["cards-ven.md"]);
    expect(readFileSync(join(vaultDir, "cards-ven.md"), "utf-8")).toContain("358");
  });

  it("extracts PDFs to markdown rather than copying the binary", async () => {
    writeFileSync(join(outputDir, "core-rules.pdf"), "%PDF-1.4 binary");

    const result = await syncToVault({
      outputDir,
      vaultDir,
      extractPdf: async () => "403.9. Maximum sideboard size is 10 cards.",
    });

    expect(result.written).toEqual(["core-rules.md"]);
    expect(existsSync(join(vaultDir, "core-rules.pdf"))).toBe(false);
    expect(readFileSync(join(vaultDir, "core-rules.md"), "utf-8")).toContain(
      "Maximum sideboard size is 10 cards."
    );
  });

  it("never deletes vault files the pipeline does not manage", async () => {
    mkdirSync(vaultDir, { recursive: true });
    writeFileSync(join(vaultDir, "hand-curated.md"), "notes I wrote myself");
    writeFileSync(join(outputDir, "cards-ven.md"), md("# Vendetta"));

    await syncToVault({ outputDir, vaultDir });

    expect(readFileSync(join(vaultDir, "hand-curated.md"), "utf-8")).toBe("notes I wrote myself");
  });

  it("ignores non-source files in output/", async () => {
    writeFileSync(join(outputDir, ".gitkeep"), "");
    writeFileSync(join(outputDir, "notes.txt"), "scratch");
    writeFileSync(join(outputDir, "cards-ven.md"), md("# Vendetta"));

    const result = await syncToVault({ outputDir, vaultDir });

    expect(result.written).toEqual(["cards-ven.md"]);
  });

  it("throws when the output directory is missing", async () => {
    await expect(
      syncToVault({ outputDir: join(root, "nope"), vaultDir })
    ).rejects.toThrow(/Output directory not found/);
  });
});

describe("resolveVaultDir", () => {
  const original = process.env.VAULT_RAW_DIR;
  afterEach(() => {
    if (original === undefined) delete process.env.VAULT_RAW_DIR;
    else process.env.VAULT_RAW_DIR = original;
  });

  it("returns the configured directory", () => {
    process.env.VAULT_RAW_DIR = "/tmp/wiki/raw";
    expect(resolveVaultDir()).toBe("/tmp/wiki/raw");
  });

  it("refuses to guess when unset", () => {
    delete process.env.VAULT_RAW_DIR;
    expect(() => resolveVaultDir()).toThrow(/VAULT_RAW_DIR is not set/);
  });

  it("treats a blank value as unset", () => {
    process.env.VAULT_RAW_DIR = "   ";
    expect(() => resolveVaultDir()).toThrow(/VAULT_RAW_DIR is not set/);
  });
});

import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { mkdtempSync, writeFileSync, readFileSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { parse, stringify } from "yaml";
import type { Manifest } from "../manifest.js";

describe("manifest serialization", () => {
  let tempDir: string;

  beforeEach(() => {
    tempDir = mkdtempSync(join(tmpdir(), "oracle-test-"));
  });

  afterEach(() => {
    rmSync(tempDir, { recursive: true });
  });

  it("round-trips riftcodex entries through YAML", () => {
    const manifest: Manifest = {
      entries: [
        {
          type: "riftcodex",
          set_id: "OGN",
          category: "cards",
          output: "output/cards-ogn.md",
          processed: "2026-03-25",
        },
      ],
    };

    const yamlPath = join(tempDir, "sources.yaml");
    writeFileSync(yamlPath, stringify(manifest), "utf-8");

    const raw = readFileSync(yamlPath, "utf-8");
    const parsed = parse(raw) as Manifest;

    expect(parsed.entries).toHaveLength(1);
    expect(parsed.entries[0].type).toBe("riftcodex");
    expect(parsed.entries[0].output).toBe("output/cards-ogn.md");
  });

  it("round-trips url entries through YAML", () => {
    const manifest: Manifest = {
      entries: [
        {
          type: "url",
          url: "https://riftbound.leagueoflegends.com/rules/",
          category: "tournament",
          output: "output/tournament-rules.md",
        },
      ],
    };

    const yamlPath = join(tempDir, "sources.yaml");
    writeFileSync(yamlPath, stringify(manifest), "utf-8");

    const parsed = parse(readFileSync(yamlPath, "utf-8")) as Manifest;

    expect(parsed.entries[0].type).toBe("url");
    expect((parsed.entries[0] as any).url).toContain("riftbound");
    expect(parsed.entries[0].processed).toBeUndefined();
  });

  it("round-trips file entries through YAML", () => {
    const manifest: Manifest = {
      entries: [
        {
          type: "pdf",
          path: "sources/rules/core-rules.pdf",
          category: "rules",
          output: "output/core-rules.md",
          processed: "2026-03-25",
        },
      ],
    };

    const yamlPath = join(tempDir, "sources.yaml");
    writeFileSync(yamlPath, stringify(manifest), "utf-8");

    const parsed = parse(readFileSync(yamlPath, "utf-8")) as Manifest;

    expect(parsed.entries[0].type).toBe("pdf");
    expect((parsed.entries[0] as any).path).toBe("sources/rules/core-rules.pdf");
  });

  it("preserves mixed entry types", () => {
    const manifest: Manifest = {
      entries: [
        { type: "riftcodex", set_id: "OGN", category: "cards", output: "output/cards-ogn.md" },
        { type: "pdf", path: "sources/rules/rules.pdf", category: "rules", output: "output/rules.md" },
        { type: "url", url: "https://example.com", category: "tournament", output: "output/tournament.md" },
      ],
    };

    const yamlPath = join(tempDir, "sources.yaml");
    writeFileSync(yamlPath, stringify(manifest), "utf-8");

    const parsed = parse(readFileSync(yamlPath, "utf-8")) as Manifest;
    expect(parsed.entries).toHaveLength(3);
    expect(parsed.entries.map((e) => e.type)).toEqual(["riftcodex", "pdf", "url"]);
  });
});

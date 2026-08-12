import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { mkdtempSync, writeFileSync, readFileSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { parse, stringify } from "yaml";
import {
  applyManifestToYaml,
  selectEntries,
  type Manifest,
  type ManifestEntry,
} from "../manifest.js";

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

describe("selectEntries", () => {
  const entries: ManifestEntry[] = [
    { type: "riftcodex", set_id: "OGN", category: "cards", output: "output/cards-ogn.md" },
    { type: "riftcodex", set_id: "VEN", category: "cards", output: "output/cards-ven.md" },
    { type: "rules-hub", url: "https://example.com/hub", category: "rules", output: "output/rules.md" },
  ];

  const outputs = (only?: string) => selectEntries(entries, only).map((e) => e.output);

  it("returns everything with no selector", () => {
    expect(outputs()).toHaveLength(3);
  });

  it("selects by category", () => {
    expect(outputs("cards")).toEqual(["output/cards-ogn.md", "output/cards-ven.md"]);
  });

  it("selects a single entry by output path", () => {
    expect(outputs("cards-ven")).toEqual(["output/cards-ven.md"]);
  });

  it("matches nothing for an unknown selector rather than falling back to everything", () => {
    expect(outputs("nope")).toEqual([]);
  });
});

describe("applyManifestToYaml", () => {
  // Every `oracle process` run writes the manifest back. Re-serializing a
  // parsed object drops all comments, so any note explaining a source used to
  // vanish on the user's first ordinary run, leaving a puzzling dirty diff.
  const source = [
    "entries:",
    "  # Fetched from the official hub.",
    "  - type: rules-hub",
    "    url: https://example.com/hub",
    "    category: rules",
    "    output: output/rules.md",
    "  # Cards come from the Riftcodex API, not a local file.",
    "  - type: riftcodex",
    "    set_id: VEN",
    "    category: cards",
    "    output: output/cards-ven.md",
    "",
  ].join("\n");

  const roundTrip = (mutate: (m: Manifest) => void) => {
    const manifest = parse(source) as Manifest;
    mutate(manifest);
    return applyManifestToYaml(source, manifest);
  };

  it("keeps comments when a processor stamps an entry", () => {
    const out = roundTrip((m) => {
      m.entries[0].processed = "2026-08-12";
    });
    expect(out).toContain("# Fetched from the official hub.");
    expect(out).toContain("# Cards come from the Riftcodex API, not a local file.");
    expect(out).toContain("processed: 2026-08-12");
  });

  it("adds a field a processor introduces", () => {
    const out = roundTrip((m) => {
      (m.entries[0] as { pdfs?: string[] }).pdfs = ["output/core-rules.pdf"];
    });
    expect(parse(out)).toEqual(
      expect.objectContaining({
        entries: expect.arrayContaining([
          expect.objectContaining({ pdfs: ["output/core-rules.pdf"] }),
        ]),
      })
    );
    expect(out).toContain("# Cards come from the Riftcodex API, not a local file.");
  });

  it("is a no-op when nothing changed", () => {
    expect(applyManifestToYaml(source, parse(source) as Manifest)).toBe(source);
  });
});

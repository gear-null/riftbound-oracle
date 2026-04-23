import { describe, it, expect, vi } from "vitest";
import {
  expectedDriveNames,
  planCleanup,
  executeCleanupPlan,
  escapeDriveQuery,
  type DriveFile,
  type CleanupPlan,
} from "../upload.js";
import type { ManifestEntry } from "../manifest.js";

function makeFile(overrides: Partial<DriveFile> = {}): DriveFile {
  return {
    id: "id-" + Math.random().toString(36).slice(2, 8),
    name: "Cards OGN",
    mimeType: "application/vnd.google-apps.document",
    createdTime: "2026-04-01T00:00:00Z",
    modifiedTime: "2026-04-01T00:00:00Z",
    ...overrides,
  };
}

describe("expectedDriveNames", () => {
  it("uppercases set codes and rules-hub outputs", () => {
    const entries: ManifestEntry[] = [
      { type: "riftcodex", set_id: "UNL", category: "cards", output: "output/cards-unl.md" },
      { type: "rules-hub", url: "https://x", category: "rules", output: "output/rules.md" },
    ];
    const names = expectedDriveNames(entries);
    expect(names).toEqual(new Set(["Cards UNL", "Rules"]));
  });

  it("adds .pdf suffix for passthrough PDF entries", () => {
    const entries: ManifestEntry[] = [
      { type: "pdf", path: "sources/rules/core.pdf", category: "rules", output: "output/core-rules.md" },
    ];
    expect(expectedDriveNames(entries)).toEqual(new Set(["Core Rules.pdf"]));
  });

  it("omits .pdf suffix when the PDF is configured to convert to markdown", () => {
    const entries: ManifestEntry[] = [
      { type: "pdf", path: "sources/x.pdf", category: "rules", output: "output/x.md", convert: true },
    ];
    expect(expectedDriveNames(entries)).toEqual(new Set(["X"]));
  });

  it("includes rules-hub sibling PDFs in the expected set", () => {
    const entries: ManifestEntry[] = [
      {
        type: "rules-hub",
        url: "https://x",
        category: "rules",
        output: "output/rules.md",
        pdfs: ["output/core-rules.pdf", "output/tournament-rules.pdf"],
      },
    ];
    expect(expectedDriveNames(entries)).toEqual(
      new Set(["Rules", "Core Rules.pdf", "Tournament Rules.pdf"])
    );
  });
});

describe("planCleanup", () => {
  it("marks files not in the expected set as deletable", () => {
    const expected = new Set(["Cards UNL"]);
    const files = [
      makeFile({ name: "Cards UNL" }),
      makeFile({ name: "Core Rules" }),
      makeFile({ name: "Tournament Rules" }),
    ];
    const plan = planCleanup(files, expected);

    expect(plan.kept.map((f) => f.name)).toEqual(["Cards UNL"]);
    expect(plan.toDelete.map(({ file, reason }) => ({ name: file.name, reason }))).toEqual([
      { name: "Core Rules", reason: "not in current manifest" },
      { name: "Tournament Rules", reason: "not in current manifest" },
    ]);
  });

  it("keeps the newest when duplicates exist for an expected name", () => {
    const expected = new Set(["Cards UNL"]);
    const oldest = makeFile({
      id: "old",
      name: "Cards UNL",
      modifiedTime: "2026-03-25T00:00:00Z",
    });
    const newest = makeFile({
      id: "new",
      name: "Cards UNL",
      modifiedTime: "2026-04-23T00:00:00Z",
    });
    const middle = makeFile({
      id: "mid",
      name: "Cards UNL",
      modifiedTime: "2026-04-01T00:00:00Z",
    });

    const plan = planCleanup([oldest, newest, middle], expected);

    expect(plan.kept).toHaveLength(1);
    expect(plan.kept[0].id).toBe("new");
    expect(plan.toDelete.map((d) => d.file.id).sort()).toEqual(["mid", "old"]);
    for (const { reason } of plan.toDelete) {
      expect(reason).toContain("older duplicate");
    }
  });

  it("returns empty plan for a clean folder", () => {
    const expected = new Set(["Cards UNL", "Rules"]);
    const files = [
      makeFile({ name: "Cards UNL", modifiedTime: "2026-04-23T00:00:00Z" }),
      makeFile({ name: "Rules", modifiedTime: "2026-04-23T00:00:00Z" }),
    ];
    const plan = planCleanup(files, expected);
    expect(plan.toDelete).toEqual([]);
    expect(plan.kept).toHaveLength(2);
  });
});

describe("executeCleanupPlan", () => {
  it("calls drive.files.delete for every file in the plan and returns them", async () => {
    const deleteCalls: string[] = [];
    const fakeDrive = {
      files: {
        delete: vi.fn(async ({ fileId }: { fileId: string }) => {
          deleteCalls.push(fileId);
          return {};
        }),
      },
    };

    const plan: CleanupPlan = {
      kept: [makeFile({ id: "keep-1", name: "Rules" })],
      toDelete: [
        { file: makeFile({ id: "del-a", name: "Old One" }), reason: "not in current manifest" },
        { file: makeFile({ id: "del-b", name: "Old Two" }), reason: "not in current manifest" },
      ],
    };

    const deleted = await executeCleanupPlan(fakeDrive as never, plan);

    expect(deleteCalls).toEqual(["del-a", "del-b"]);
    expect(deleted.map((f) => f.id)).toEqual(["del-a", "del-b"]);
  });

  it("is a no-op when the plan has nothing to delete", async () => {
    const deleteMock = vi.fn();
    const fakeDrive = { files: { delete: deleteMock } };
    const plan: CleanupPlan = { kept: [makeFile()], toDelete: [] };

    const deleted = await executeCleanupPlan(fakeDrive as never, plan);

    expect(deleteMock).not.toHaveBeenCalled();
    expect(deleted).toEqual([]);
  });
});

describe("escapeDriveQuery", () => {
  it("escapes single quotes and backslashes so interpolated names can't break queries", () => {
    expect(escapeDriveQuery("Dragon's Rage")).toBe("Dragon\\'s Rage");
    expect(escapeDriveQuery("back\\slash")).toBe("back\\\\slash");
    expect(escapeDriveQuery("a'b\\c")).toBe("a\\'b\\\\c");
  });

  it("leaves ordinary strings untouched", () => {
    expect(escapeDriveQuery("Cards UNL")).toBe("Cards UNL");
    expect(escapeDriveQuery("Core Rules.pdf")).toBe("Core Rules.pdf");
  });
});

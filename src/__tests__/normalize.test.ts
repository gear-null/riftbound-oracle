import { describe, it, expect } from "vitest";
import { normalize } from "../normalize.js";

describe("normalize", () => {
  it("adds frontmatter with category and generator", () => {
    const result = normalize("Hello world", "rules");
    expect(result).toMatch(/^---\n/);
    expect(result).toContain("category: rules");
    expect(result).toContain("generator: riftbound-oracle");
  });

  it("collapses excessive blank lines", () => {
    const result = normalize("Line 1\n\n\n\n\nLine 2", "cards");
    // Should have at most 2 newlines between content lines (after frontmatter)
    expect(result).not.toContain("\n\n\n");
  });

  it("trims trailing whitespace from lines", () => {
    const result = normalize("Hello   \nWorld  ", "cards");
    const lines = result.split("\n");
    for (const line of lines) {
      expect(line).toBe(line.trimEnd());
    }
  });

  it("ends with a single newline", () => {
    const result = normalize("Content", "cards");
    expect(result).toMatch(/[^\n]\n$/);
  });
});

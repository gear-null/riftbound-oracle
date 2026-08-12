import { describe, it, expect } from "vitest";
import { normalize, decodeEntities } from "../normalize.js";

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

  it("decodes entities that leak in from the API's plain text", () => {
    const result = normalize("[Empowered][&gt;] I have [Assault 3].", "cards");
    expect(result).toContain("[Empowered][>] I have [Assault 3].");
    expect(result).not.toContain("&gt;");
  });
});

describe("decodeEntities", () => {
  it("decodes the entities Riftcodex actually emits", () => {
    expect(decodeEntities("[Empowered][&gt;]")).toBe("[Empowered][>]");
    expect(decodeEntities("&quot;Hunt them.&quot;")).toBe('"Hunt them."');
  });

  it("decodes the remaining common named entities", () => {
    expect(decodeEntities("a &lt; b")).toBe("a < b");
    expect(decodeEntities("it&#39;s")).toBe("it's");
    expect(decodeEntities("a&nbsp;b")).toBe("a b");
  });

  it("decodes &amp; last so escaped entities survive one pass", () => {
    expect(decodeEntities("&amp;gt;")).toBe("&gt;");
    expect(decodeEntities("Bilgewater &amp; Noxus")).toBe("Bilgewater & Noxus");
  });

  it("leaves text without entities untouched", () => {
    expect(decodeEntities("When I move, you may [Burn 1].")).toBe(
      "When I move, you may [Burn 1]."
    );
  });
});

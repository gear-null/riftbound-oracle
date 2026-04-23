import { describe, it, expect } from "vitest";
import { mkdtempSync, readFileSync, rmSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { JSDOM } from "jsdom";
import {
  collectHubLinks,
  categorizeLinks,
  extractArticleBody,
  slugify,
  processRulesHub,
} from "../processors/rules-hub.js";

const HUB_URL = "https://riftbound.example.com/en-us/rules-hub/";

function makeHubHtml(): string {
  return `
    <html><body>
      <h1>Rules Hub</h1>
      <p>Banned cards listed below.</p>
      <img src="data:image/svg+xml,<svg/>" />
      <a href="https://cdn.example.com/files/core.pdf">Core Rules</a>
      <a href="https://cdn.example.com/files/tournament.pdf">Tournament Rules</a>
      <a href="/en-us/news/rules-and-releases/core-rules-patch-notes/">Core Rules Patch Notes</a>
      <a href="/en-us/news/rules-and-releases/spiritforged-errata/">Spiritforged Errata</a>
      <a href="/en-us/news/rules-and-releases/how-to-play-get-started/">How to Play: Get Started</a>
      <a href="/en-us/news/rules-and-releases/unleashed-errata-updates/">Unleashed Errata</a>
      <a href="/en-us/news/unrelated/">Unrelated Article</a>
      <div data-testid="article-card-carousel">
        <h2>Related Articles</h2>
        <div>junk</div>
      </div>
    </body></html>
  `;
}

describe("slugify", () => {
  it("converts link text to kebab-case", () => {
    expect(slugify("Core Rules")).toBe("core-rules");
    expect(slugify("Tournament Rules  v2")).toBe("tournament-rules-v2");
    expect(slugify("  Weird/Chars & stuff  ")).toBe("weird-chars-stuff");
  });
});

describe("collectHubLinks", () => {
  it("returns absolute URLs and deduplicates", () => {
    const dom = new JSDOM(makeHubHtml());
    const links = collectHubLinks(dom.window.document, HUB_URL);
    const urls = links.map((l) => l.url);
    expect(urls).toContain("https://cdn.example.com/files/core.pdf");
    expect(new Set(urls).size).toBe(urls.length);
  });
});

describe("categorizeLinks", () => {
  it("only includes patch-notes and errata articles; filters beginner guides and unrelated links", () => {
    const dom = new JSDOM(makeHubHtml());
    const links = collectHubLinks(dom.window.document, HUB_URL);
    const { pdfs, articles } = categorizeLinks(links);

    expect(pdfs.map((p) => p.text)).toEqual(["Core Rules", "Tournament Rules"]);
    expect(articles.map((a) => a.text)).toEqual([
      "Core Rules Patch Notes",
      "Spiritforged Errata",
      "Unleashed Errata",
    ]);
    // how-to-play-get-started and /news/unrelated/ must not leak in
    const urls = articles.map((a) => a.url);
    expect(urls.some((u) => u.includes("how-to-play"))).toBe(false);
    expect(urls.some((u) => u.includes("/news/unrelated/"))).toBe(false);
  });
});

describe("extractArticleBody", () => {
  it("returns only the ArticleRichTextBlade content, dropping sidebars and SVG placeholders", () => {
    const html = `
      <html><body>
        <header>Site chrome</header>
        <img src="data:image/svg+xml,<svg/>" />
        <div data-testid="ArticleRichTextBlade">
          <h2>Patch Notes</h2>
          <p>The real content.</p>
          <img src="data:image/svg+xml,<svg/>" />
        </div>
        <div data-testid="article-card-carousel">
          <h2>Related Articles</h2>
          <p>noise</p>
        </div>
      </body></html>
    `;
    const md = extractArticleBody(html);
    expect(md).toContain("Patch Notes");
    expect(md).toContain("The real content.");
    expect(md).not.toContain("data:image/svg");
    expect(md).not.toContain("Related Articles");
    expect(md).not.toContain("Site chrome");
  });

  it("falls back to full body when the blade selector is missing, still stripping noise", () => {
    const html = `
      <html><body>
        <p>Only a paragraph here.</p>
        <img src="data:image/svg+xml,<svg/>" />
        <div data-testid="article-card-carousel"><p>carousel junk</p></div>
      </body></html>
    `;
    const md = extractArticleBody(html);
    expect(md).toContain("Only a paragraph here.");
    expect(md).not.toContain("data:image/svg");
    expect(md).not.toContain("carousel junk");
  });
});

describe("processRulesHub", () => {
  it("downloads PDFs to sibling files, writes a clean articles-only markdown, returns pdfOutputs", async () => {
    const dir = mkdtempSync(join(tmpdir(), "rules-hub-test-"));
    const outputPath = join(dir, "rules.md");

    const articleHtml = new Map<string, string>([
      [
        "https://riftbound.example.com/en-us/news/rules-and-releases/core-rules-patch-notes/",
        `<html><body>
          <div data-testid="ArticleRichTextBlade">
            <h2>Core Patch Notes</h2>
            <p>Patch body text.</p>
          </div>
          <div data-testid="article-card-carousel"><p>junk</p></div>
        </body></html>`,
      ],
      [
        "https://riftbound.example.com/en-us/news/rules-and-releases/spiritforged-errata/",
        `<html><body>
          <div data-testid="ArticleRichTextBlade">
            <h2>Spiritforged Errata</h2>
            <p>Errata body text.</p>
          </div>
        </body></html>`,
      ],
      [
        "https://riftbound.example.com/en-us/news/rules-and-releases/unleashed-errata-updates/",
        `<html><body>
          <div data-testid="ArticleRichTextBlade">
            <h2>Unleashed Errata</h2>
            <p>Unleashed body.</p>
          </div>
        </body></html>`,
      ],
    ]);

    const fetchedUrls: string[] = [];

    try {
      const result = await processRulesHub({
        hubUrl: HUB_URL,
        category: "rules",
        outputPath,
        fetchHtml: async (url) => {
          fetchedUrls.push(url);
          if (url === HUB_URL) return makeHubHtml();
          const body = articleHtml.get(url);
          if (!body) throw new Error(`Unexpected URL: ${url}`);
          return body;
        },
        fetchPdf: async (url) => {
          fetchedUrls.push(url);
          return new TextEncoder().encode("%PDF fake " + url).buffer;
        },
      });

      // PDF outputs written as sibling files, named by slugified link text
      expect(result.pdfOutputs).toHaveLength(2);
      expect(result.pdfOutputs[0]).toMatch(/core-rules\.pdf$/);
      expect(result.pdfOutputs[1]).toMatch(/tournament-rules\.pdf$/);
      for (const p of result.pdfOutputs) {
        expect(existsSync(p)).toBe(true);
      }

      const md = readFileSync(outputPath, "utf-8");

      // Frontmatter + clean structure
      expect(md).toMatch(/^---\ncategory: rules\n/);
      expect(md).toContain("# Riftbound Rules");
      expect(md).toContain("Banned cards listed below.");

      // PDFs are REFERENCED, not inlined
      expect(md).toContain("Core Documents");
      expect(md).toContain("`core-rules.pdf`");
      expect(md).toContain("`tournament-rules.pdf`");
      // No PDF content dumped into the markdown
      expect(md).not.toContain("%PDF fake");

      // Articles: only patch-notes + errata, bodies only (no carousel, no SVG)
      expect(md).toContain("## Core Rules Patch Notes");
      expect(md).toContain("Patch body text.");
      expect(md).toContain("## Spiritforged Errata");
      expect(md).toContain("## Unleashed Errata");
      expect(md).not.toContain("data:image/svg");
      expect(md).not.toContain("junk");

      // The beginner-guide link and unrelated news must not have been fetched
      expect(fetchedUrls.some((u) => u.includes("how-to-play"))).toBe(false);
      expect(fetchedUrls.some((u) => u.includes("/news/unrelated/"))).toBe(false);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});

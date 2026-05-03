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
  humanizeSlug,
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
      <a href="/en-us/news/announcements/april-2026-tournament-rules-update-changelog/">April 2026 Changelog</a>
      <a href="/en-us/news/announcements/product-drawing-faq/">Product Drawing FAQ</a>
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

describe("humanizeSlug", () => {
  it("title-cases the last path segment and uppercases known acronyms", () => {
    expect(humanizeSlug("/news/rules-and-releases/unleashed-rules-faq-and-clarifications/")).toBe(
      "Unleashed Rules FAQ and Clarifications"
    );
    expect(humanizeSlug("core-rules-patch-notes")).toBe("Core Rules Patch Notes");
    expect(humanizeSlug("/tcg-api-guide/")).toBe("TCG API Guide");
  });

  it("keeps connector words lowercase mid-phrase but capitalizes them at the start", () => {
    expect(humanizeSlug("the-art-of-play")).toBe("The Art of Play");
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

  it("prefers the inner card-title as the label when an anchor wraps a news card", () => {
    const html = `
      <html><body>
        <a href="/en-us/news/announcements/april-2026-tournament-rules-update-changelog/">
          <span data-testid="card-category">Announcements</span>
          <span data-testid="card-date">2026-04-29T16:00:00.000Z</span>
          <span data-testid="card-title">April 2026 Tournament Rules Update &amp; Changelog</span>
          <span data-testid="card-description">Updates to Riftbound's tournament rules explained.</span>
        </a>
      </body></html>
    `;
    const dom = new JSDOM(html);
    const links = collectHubLinks(dom.window.document, HUB_URL);
    expect(links).toHaveLength(1);
    expect(links[0].text).toBe("April 2026 Tournament Rules Update & Changelog");
  });

  it("strips ISO timestamps from anchor text when no card-title is present", () => {
    const html = `
      <html><body>
        <a href="/news/foo/">Announcements 2026-04-29T16:00:00.000Z Foo Article</a>
      </body></html>
    `;
    const dom = new JSDOM(html);
    const links = collectHubLinks(dom.window.document, HUB_URL);
    expect(links[0].text).toBe("Announcements Foo Article");
  });
});

describe("categorizeLinks", () => {
  it("includes patch-notes / errata / changelog articles; filters beginner guides, product FAQs, and unrelated links", () => {
    const dom = new JSDOM(makeHubHtml());
    const links = collectHubLinks(dom.window.document, HUB_URL);
    const { pdfs, articles } = categorizeLinks(links);

    expect(pdfs.map((p) => p.text)).toEqual(["Core Rules", "Tournament Rules"]);
    expect(articles.map((a) => a.text)).toEqual([
      "Core Rules Patch Notes",
      "Spiritforged Errata",
      "Unleashed Errata",
      "April 2026 Changelog",
    ]);
    const urls = articles.map((a) => a.url);
    // beginner guide, unrelated news, and a non-rules "drawing FAQ" must not leak in
    expect(urls.some((u) => u.includes("how-to-play"))).toBe(false);
    expect(urls.some((u) => u.includes("/news/unrelated/"))).toBe(false);
    expect(urls.some((u) => u.includes("product-drawing-faq"))).toBe(false);
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
      [
        "https://riftbound.example.com/en-us/news/announcements/april-2026-tournament-rules-update-changelog/",
        `<html><body>
          <div data-testid="ArticleRichTextBlade">
            <h2>April Changelog</h2>
            <p>Changelog body.</p>
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

      // Articles: patch-notes + errata + changelog, bodies only (no carousel, no SVG)
      expect(md).toContain("## Core Rules Patch Notes");
      expect(md).toContain("Patch body text.");
      expect(md).toContain("## Spiritforged Errata");
      expect(md).toContain("## Unleashed Errata");
      expect(md).toContain("## April 2026 Changelog");
      expect(md).toContain("Changelog body.");
      expect(md).not.toContain("data:image/svg");
      expect(md).not.toContain("junk");

      // Beginner guide, unrelated news, and product-drawing FAQ must not have been fetched
      expect(fetchedUrls.some((u) => u.includes("how-to-play"))).toBe(false);
      expect(fetchedUrls.some((u) => u.includes("/news/unrelated/"))).toBe(false);
      expect(fetchedUrls.some((u) => u.includes("product-drawing-faq"))).toBe(false);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("includes extra_articles even when the hub doesn't link to them, deduping against hub-discovered URLs", async () => {
    const dir = mkdtempSync(join(tmpdir(), "rules-hub-test-"));
    const outputPath = join(dir, "rules.md");

    const FAQ_URL =
      "https://riftbound.example.com/en-us/news/rules-and-releases/unleashed-rules-faq-and-clarifications/";

    const fetchedUrls: string[] = [];

    try {
      await processRulesHub({
        hubUrl: HUB_URL,
        category: "rules",
        outputPath,
        // Pass the changelog URL twice — once via hub, once explicitly — to verify dedupe.
        extraArticles: [
          FAQ_URL,
          "https://riftbound.example.com/en-us/news/announcements/april-2026-tournament-rules-update-changelog/",
        ],
        fetchHtml: async (url) => {
          fetchedUrls.push(url);
          if (url === HUB_URL) return makeHubHtml();
          if (url === FAQ_URL) {
            return `<html><body>
              <div data-testid="ArticleRichTextBlade">
                <h2>Definition of Play</h2>
                <p>Three meanings of play body.</p>
              </div>
            </body></html>`;
          }
          // Stubs for hub-discovered articles
          return `<html><body>
            <div data-testid="ArticleRichTextBlade"><p>generic</p></div>
          </body></html>`;
        },
        fetchPdf: async () => new TextEncoder().encode("%PDF").buffer,
      });

      const md = readFileSync(outputPath, "utf-8");

      // FAQ shows up via extra_articles, with a humanized heading derived from the URL slug
      expect(md).toContain("Unleashed Rules FAQ and Clarifications");
      expect(md).toContain("Three meanings of play body.");

      // Changelog must be fetched only once (already discovered on the hub)
      const changelogFetches = fetchedUrls.filter((u) =>
        u.includes("april-2026-tournament-rules-update-changelog")
      );
      expect(changelogFetches.length).toBe(1);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});

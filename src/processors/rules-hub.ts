import { writeFileSync } from "node:fs";
import { writeFile } from "node:fs/promises";
import { basename, dirname, join, resolve } from "node:path";
import { JSDOM } from "jsdom";
import TurndownService from "turndown";
import { normalize } from "../normalize.js";

const turndown = new TurndownService({
  headingStyle: "atx",
  codeBlockStyle: "fenced",
  bulletListMarker: "-",
});
turndown.remove(["script", "style", "nav", "footer", "header", "iframe", "noscript"]);

const ARTICLE_PATH_PATTERN = /patch-notes|errata|changelog/i;

interface LinkInfo {
  url: string;
  text: string;
}

export interface RulesHubHtmlFetcher {
  (url: string): Promise<string>;
}

export interface RulesHubPdfFetcher {
  (url: string): Promise<ArrayBuffer>;
}

export interface ProcessRulesHubOptions {
  hubUrl: string;
  category: string;
  outputPath: string;
  /** Extra article URLs to fetch in addition to those discovered on the hub. */
  extraArticles?: string[];
  onProgress?: (message: string) => void;
  // Injectable for testing
  fetchHtml?: RulesHubHtmlFetcher;
  fetchPdf?: RulesHubPdfFetcher;
}

export interface ProcessRulesHubResult {
  /** Absolute paths to downloaded PDFs (for upload pipeline to pick up). */
  pdfOutputs: string[];
}

function absoluteUrl(href: string | null, baseUrl: string): string | null {
  if (!href) return null;
  try {
    return new URL(href, baseUrl).toString();
  } catch {
    return null;
  }
}

function dedupe(links: LinkInfo[]): LinkInfo[] {
  const seen = new Set<string>();
  const out: LinkInfo[] = [];
  for (const link of links) {
    if (seen.has(link.url)) continue;
    seen.add(link.url);
    out.push(link);
  }
  return out;
}

/**
 * Pull a clean display label from an anchor.
 *
 * The Rules Hub wraps news cards in `<a>` tags whose `textContent` concatenates
 * the category badge, ISO publish date, title, and description into one blob
 * (e.g. "Announcements2026-04-29T16:00:00.000ZApril 2026 …Updates explained.").
 * We prefer the inner card title when present, and as a defensive fallback we
 * strip ISO timestamps from raw anchor text.
 */
function anchorLabel(a: Element): string {
  const cardTitle = a.querySelector('[data-testid="card-title"]');
  if (cardTitle) {
    return (cardTitle.textContent ?? "").trim().replace(/\s+/g, " ");
  }
  return (a.textContent ?? "")
    .replace(/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z/g, "")
    .trim()
    .replace(/\s+/g, " ");
}

export function collectHubLinks(document: Document, baseUrl: string): LinkInfo[] {
  const anchors = Array.from(document.querySelectorAll("a[href]"));
  const links: LinkInfo[] = [];
  for (const a of anchors) {
    const href = a.getAttribute("href");
    const url = absoluteUrl(href, baseUrl);
    if (!url) continue;
    links.push({ url, text: anchorLabel(a) });
  }
  return dedupe(links);
}

/** PDFs = .pdf links. Articles = only patch-notes / errata URLs (no stray beginner guides). */
export function categorizeLinks(links: LinkInfo[]): {
  pdfs: LinkInfo[];
  articles: LinkInfo[];
} {
  const pdfs: LinkInfo[] = [];
  const articles: LinkInfo[] = [];
  for (const link of links) {
    const path = (() => {
      try {
        return new URL(link.url).pathname;
      } catch {
        return link.url;
      }
    })();
    if (path.toLowerCase().endsWith(".pdf")) {
      pdfs.push(link);
    } else if (ARTICLE_PATH_PATTERN.test(path)) {
      articles.push(link);
    }
  }
  return { pdfs, articles };
}

/** Strip lazy-load SVG placeholders and "Related Articles" carousels before rendering. */
function stripNoise(root: Element): void {
  for (const img of Array.from(root.querySelectorAll("img"))) {
    const src = img.getAttribute("src") ?? "";
    if (src.startsWith("data:image/svg")) img.remove();
  }
  for (const el of Array.from(
    root.querySelectorAll('[data-testid="article-card-carousel"]')
  )) {
    el.remove();
  }
}

/** Convert the main article body to markdown; falls back to full body if the selector isn't present. */
export function extractArticleBody(html: string): string {
  const dom = new JSDOM(html);
  const doc = dom.window.document;
  const blade = doc.querySelector('[data-testid="ArticleRichTextBlade"]');
  const root = (blade ?? doc.body) as Element;
  stripNoise(root);
  return turndown.turndown(root).trim();
}

/** Convert the hub page's body with sidebars + placeholder images stripped. */
export function extractHubOverview(html: string): string {
  const dom = new JSDOM(html);
  stripNoise(dom.window.document.body);
  return turndown.turndown(dom.window.document.body).trim();
}

/** "Core Rules" → "core-rules". Used to name downloaded PDFs. */
export function slugify(s: string): string {
  return s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

/** Words that should stay fully uppercase when humanizing slugs into headings. */
const UPPERCASE_WORDS = new Set(["faq", "tcg", "api", "pdf", "ord", "cr", "tr", "opl"]);

/**
 * Turn a URL slug or path into a human-readable heading.
 * "/news/.../unleashed-rules-faq-and-clarifications/" → "Unleashed Rules FAQ and Clarifications".
 */
export function humanizeSlug(slugOrPath: string): string {
  const slug = slugOrPath.split("/").filter(Boolean).pop() ?? slugOrPath;
  return slug
    .split("-")
    .map((word, i) => {
      const lower = word.toLowerCase();
      if (UPPERCASE_WORDS.has(lower)) return lower.toUpperCase();
      // Lowercase common connectors mid-phrase
      if (i > 0 && (lower === "and" || lower === "or" || lower === "of" || lower === "the")) {
        return lower;
      }
      return lower.charAt(0).toUpperCase() + lower.slice(1);
    })
    .join(" ");
}

async function defaultFetchHtml(url: string): Promise<string> {
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`Failed to fetch ${url}: ${res.status} ${res.statusText}`);
  }
  return res.text();
}

async function defaultFetchPdf(url: string): Promise<ArrayBuffer> {
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`Failed to fetch PDF ${url}: ${res.status} ${res.statusText}`);
  }
  return res.arrayBuffer();
}

export async function processRulesHub(
  opts: ProcessRulesHubOptions
): Promise<ProcessRulesHubResult> {
  const progress = opts.onProgress ?? (() => {});
  const fetchHtml = opts.fetchHtml ?? defaultFetchHtml;
  const fetchPdf = opts.fetchPdf ?? defaultFetchPdf;

  progress("Fetching hub");
  const hubHtml = await fetchHtml(opts.hubUrl);
  const hubDom = new JSDOM(hubHtml);
  const hubOverview = extractHubOverview(hubHtml);
  const links = collectHubLinks(hubDom.window.document, opts.hubUrl);
  const { pdfs, articles } = categorizeLinks(links);

  // Append explicitly-declared extra articles, deduped against hub-discovered ones.
  const seenArticleUrls = new Set(articles.map((a) => a.url));
  for (const url of opts.extraArticles ?? []) {
    if (seenArticleUrls.has(url)) continue;
    seenArticleUrls.add(url);
    articles.push({ url, text: humanizeSlug(new URL(url).pathname) });
  }

  const outputDir = dirname(resolve(opts.outputPath));
  const pdfOutputs: string[] = [];

  // Download PDFs to sibling files; they'll be uploaded as separate NotebookLM sources.
  for (let i = 0; i < pdfs.length; i++) {
    const pdf = pdfs[i];
    progress(`PDF ${i + 1}/${pdfs.length}: ${pdf.text}`);
    const slug = slugify(pdf.text) || `rules-pdf-${i}`;
    const localPath = join(outputDir, `${slug}.pdf`);
    const buf = await fetchPdf(pdf.url);
    await writeFile(localPath, Buffer.from(buf));
    pdfOutputs.push(localPath);
  }

  const sections: string[] = [];
  sections.push("# Riftbound Rules");
  sections.push("");
  sections.push(`_Consolidated from the official Rules Hub: ${opts.hubUrl}_`);
  sections.push("");
  sections.push(hubOverview);

  if (pdfOutputs.length > 0) {
    sections.push("");
    sections.push("---");
    sections.push("");
    sections.push("# Core Documents");
    sections.push("");
    sections.push(
      "The canonical rules PDFs are uploaded as separate sources so NotebookLM can cite them with native PDF previews:"
    );
    sections.push("");
    for (let i = 0; i < pdfs.length; i++) {
      const pdf = pdfs[i];
      const localFile = basename(pdfOutputs[i]);
      sections.push(`- **${pdf.text}** — \`${localFile}\` (source: ${pdf.url})`);
    }
  }

  if (articles.length > 0) {
    sections.push("");
    sections.push("---");
    sections.push("");
    sections.push("# Patch Notes & Errata");
    for (let i = 0; i < articles.length; i++) {
      const article = articles[i];
      progress(`Article ${i + 1}/${articles.length}: ${article.text}`);
      const html = await fetchHtml(article.url);
      const body = extractArticleBody(html);
      sections.push("");
      sections.push("---");
      sections.push("");
      sections.push(`## ${article.text}`);
      sections.push("");
      sections.push(`_Source: ${article.url}_`);
      sections.push("");
      sections.push(body);
    }
  }

  const combined = sections.join("\n");
  const finalMd = normalize(combined, opts.category);
  writeFileSync(resolve(opts.outputPath), finalMd, "utf-8");

  return { pdfOutputs };
}

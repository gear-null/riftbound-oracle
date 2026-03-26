import { writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { JSDOM } from "jsdom";
import TurndownService from "turndown";
import { normalize } from "../normalize.js";

const turndown = new TurndownService({
  headingStyle: "atx",
  codeBlockStyle: "fenced",
  bulletListMarker: "-",
});

// Remove noise elements
turndown.remove(["script", "style", "nav", "footer", "header", "iframe", "noscript"]);

export async function processUrl(
  url: string,
  category: string,
  outputPath: string,
  onProgress?: (message: string) => void
): Promise<void> {
  onProgress?.("Fetching page");

  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`Failed to fetch ${url}: ${res.status} ${res.statusText}`);
  }

  const html = await res.text();
  onProgress?.("Converting to markdown");

  // Parse with jsdom so turndown has a DOM to work with in Node.js
  const dom = new JSDOM(html);
  const rawMarkdown = turndown.turndown(dom.window.document.body);
  const markdown = normalize(rawMarkdown, category);

  writeFileSync(resolve(outputPath), markdown, "utf-8");
}

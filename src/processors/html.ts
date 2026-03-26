import { readFileSync, writeFileSync } from "node:fs";
import { basename, extname, resolve } from "node:path";
import { JSDOM } from "jsdom";
import TurndownService from "turndown";
import { normalize } from "../normalize.js";
import type { ProcessOptions } from "./index.js";

const turndown = new TurndownService({
  headingStyle: "atx",
  codeBlockStyle: "fenced",
  bulletListMarker: "-",
});

// Remove script/style/nav elements
turndown.remove(["script", "style", "nav", "footer", "header"]);

export async function processHtml(opts: ProcessOptions): Promise<string> {
  const absolutePath = resolve(opts.sourcePath);
  const html = readFileSync(absolutePath, "utf-8");

  const dom = new JSDOM(html);
  const rawMarkdown = turndown.turndown(dom.window.document.body);
  const markdown = normalize(rawMarkdown, opts.category);

  const ext = extname(opts.sourcePath);
  const outputName = basename(opts.sourcePath, ext);
  const outputPath = opts.outputPath ?? `output/${outputName}.md`;

  writeFileSync(resolve(outputPath), markdown, "utf-8");

  return outputPath;
}

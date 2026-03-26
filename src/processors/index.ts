import { extname } from "node:path";
import { processPdf } from "./pdf.js";
import { processHtml } from "./html.js";
import { processApi } from "./api.js";

export interface ProcessOptions {
  sourcePath: string;
  category: string;
  outputPath?: string;
  onProgress?: (message: string) => void;
}

export async function processSource(opts: ProcessOptions): Promise<string> {
  const ext = extname(opts.sourcePath).toLowerCase();

  switch (ext) {
    case ".pdf":
      return processPdf(opts);
    case ".html":
    case ".htm":
      return processHtml(opts);
    case ".json":
      return processApi(opts);
    default:
      throw new Error(
        `Unsupported source format: ${ext}. Supported: .pdf, .html, .json`
      );
  }
}

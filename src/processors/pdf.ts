import { spawn } from "node:child_process";
import { existsSync, writeFileSync } from "node:fs";
import { basename, resolve } from "node:path";
import { normalize } from "../normalize.js";
import type { ProcessOptions } from "./index.js";

const PROJECT_ROOT = resolve(import.meta.dirname, "..");
const PYTHON_SCRIPT = resolve(PROJECT_ROOT, "scripts/pdf-extract.py");
const VENV_PYTHON = resolve(PROJECT_ROOT, ".venv/bin/python3");

function getPython(): string {
  if (existsSync(VENV_PYTHON)) return VENV_PYTHON;
  return "python3";
}

function runPdfExtract(
  absolutePath: string,
  onProgress: (message: string) => void
): Promise<string> {
  return new Promise((resolve, reject) => {
    const child = spawn(getPython(), [PYTHON_SCRIPT, absolutePath]);

    const stdoutChunks: Buffer[] = [];

    child.stdout.on("data", (chunk: Buffer) => {
      stdoutChunks.push(chunk);
    });

    child.stderr.on("data", (chunk: Buffer) => {
      const lines = chunk.toString().split("\n");
      for (const line of lines) {
        const match = line.match(/^PROGRESS:(\d+)\/(\d+)$/);
        if (match) {
          onProgress(`Page ${match[1]}/${match[2]}`);
        }
      }
    });

    child.on("error", (err) => {
      reject(new Error(`Failed to start Python: ${err.message}`));
    });

    child.on("close", (code) => {
      if (code !== 0) {
        reject(new Error(`pdf-extract.py exited with code ${code}`));
        return;
      }
      resolve(Buffer.concat(stdoutChunks).toString("utf-8"));
    });
  });
}

export async function processPdf(opts: ProcessOptions): Promise<string> {
  const absolutePath = resolve(opts.sourcePath);

  const rawText = await runPdfExtract(
    absolutePath,
    opts.onProgress ?? (() => {})
  );

  const markdown = normalize(rawText, opts.category);
  const outputName = basename(opts.sourcePath, ".pdf");
  const outputPath = opts.outputPath ?? `output/${outputName}.md`;

  writeFileSync(resolve(outputPath), markdown, "utf-8");

  return outputPath;
}

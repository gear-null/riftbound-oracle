import { resolve } from "node:path";
import { defineConfig } from "vite";

export default defineConfig({
  build: {
    target: "node22",
    lib: {
      entry: resolve(import.meta.dirname, "src/cli.ts"),
      formats: ["es"],
      fileName: "cli",
    },
    rolldownOptions: {
      external: [/^node:/, "googleapis", "dotenv", "dotenv/config", "jsdom", "fsevents"],
      output: {
        banner: "#!/usr/bin/env node",
      },
    },
    outDir: "dist",
  },
});

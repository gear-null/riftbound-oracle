/**
 * Normalize extracted text into clean, consistent markdown.
 * Shared across all processors.
 */
export function normalize(raw: string, category: string): string {
  let text = raw;

  // Collapse 3+ consecutive blank lines into 2
  text = text.replace(/\n{3,}/g, "\n\n");

  // Trim trailing whitespace from each line
  text = text
    .split("\n")
    .map((line) => line.trimEnd())
    .join("\n");

  // Ensure file ends with a single newline
  text = text.trimEnd() + "\n";

  // Add metadata header
  const header = [
    "---",
    `category: ${category}`,
    `generated: ${new Date().toISOString().split("T")[0]}`,
    `generator: riftbound-oracle`,
    "---",
    "",
    "",
  ].join("\n");

  return header + text;
}

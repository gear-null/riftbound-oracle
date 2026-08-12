/**
 * Normalize extracted text into clean, consistent markdown.
 * Shared across all processors.
 */
/**
 * Decode the HTML entities that leak through Riftcodex's `text.plain` field —
 * it's derived from the rich HTML, so keyword notation arrives as
 * `[Empowered][&gt;]` rather than `[Empowered][>]`.
 *
 * This restores the character the source intended, so citations quote what the
 * card actually says. `&amp;` is decoded last so `&amp;gt;` doesn't collapse
 * into `>` in two passes.
 */
export function decodeEntities(text: string): string {
  return text
    .replace(/&gt;/g, ">")
    .replace(/&lt;/g, "<")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&");
}

export function normalize(raw: string, category: string): string {
  let text = decodeEntities(raw);

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

/**
 * Extract the "lead conclusion" from a role-run markdown report (or its
 * 280-char ``final_report_excerpt``).
 *
 * Role-run reports typically open with a document title followed by a
 * "核心结论" section. We strip markdown syntax, drop table-separator /
 * short label lines, and return the first substantive sentence-like line —
 * the opening result shown on the indicator board.
 */

const TABLE_SEPARATOR_RE = /^\|?[\s:|-]+$/;

function cleanLine(raw: string): string {
  let line = raw.trim();
  if (!line) return "";
  if (TABLE_SEPARATOR_RE.test(line)) return "";
  // Strip block markers / inline emphasis / inline code.
  line = line
    .replace(/^#{1,6}\s*/, "")
    .replace(/^\s*[-*+]\s+/, "")
    .replace(/^>\s*/, "")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/\*([^*]+)\*/g, "$1")
    .replace(/`([^`]+)`/g, "$1");
  // Table rows: turn cells into a single readable line.
  if (line.includes("|")) {
    line = line
      .split("|")
      .map((cell) => cell.trim())
      .filter(Boolean)
      .join(" · ");
  }
  return line.trim();
}

export function extractLeadConclusion(
  markdown: string | null | undefined,
  maxLength = 160,
): string {
  if (!markdown) return "";
  const candidates: string[] = [];
  for (const rawLine of markdown.split(/\r?\n/)) {
    const line = cleanLine(rawLine);
    if (line) candidates.push(line);
  }
  if (candidates.length === 0) return "";
  // Skip short title/label-like opening lines ("核心结论", "宏观分析报告");
  // the first substantive sentence carries the opening result.
  const lead = candidates.find((candidate) => candidate.length >= 14)
    ?? candidates[0];
  return lead.length > maxLength
    ? `${lead.slice(0, maxLength - 1).trimEnd()}…`
    : lead;
}

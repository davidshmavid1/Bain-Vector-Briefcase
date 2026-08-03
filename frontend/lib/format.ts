import type { CompanyBrief, Insight } from "./types";

export function formatDate(value: string | null | undefined): string {
  if (!value) return "Date unknown";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export function formatTimestamp(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Plain-text rendering of the brief for the copy-to-clipboard action. */
export function briefToPlainText(brief: CompanyBrief): string {
  const lines: string[] = [];
  const sourceLabel = (ids: string[]) => {
    const numbers = ids
      .map((id) => brief.sources.findIndex((source) => source.id === id) + 1)
      .filter((position) => position > 0);
    return numbers.length > 0 ? ` [${numbers.join(", ")}]` : "";
  };
  const insightBlock = (heading: string, items: Insight[]) => {
    if (items.length === 0) return;
    lines.push(heading, "");
    items.forEach((item) => {
      lines.push(`- ${item.insight}${sourceLabel(item.source_ids)}`);
      lines.push(`  ${item.rationale}`);
    });
    lines.push("");
  };

  lines.push(`CLIENT BRIEF — ${brief.company.toUpperCase()}`);
  lines.push(
    `Generated ${formatTimestamp(brief.generated_at)} · Last ${brief.time_range} · Confidence: ${brief.confidence}`,
  );
  if (brief.is_demo) lines.push("DEMO MODE — sample content, not live coverage.");
  lines.push("", "EXECUTIVE SUMMARY", "", brief.executive_summary, "");

  if (brief.developments.length > 0) {
    lines.push("RECENT DEVELOPMENTS", "");
    brief.developments.forEach((development) => {
      lines.push(`- ${development.title}${development.date ? ` (${development.date})` : ""}${sourceLabel(development.source_ids)}`);
      lines.push(`  ${development.summary}`);
      lines.push(`  Why it matters: ${development.why_it_matters}`);
    });
    lines.push("");
  }

  insightBlock("RISKS", brief.risks);
  insightBlock("OPPORTUNITIES", brief.opportunities);

  if (brief.talking_points.length > 0) {
    lines.push("TALKING POINTS", "");
    brief.talking_points.forEach((point) => lines.push(`- ${point}`));
    lines.push("");
  }
  if (brief.recommended_questions.length > 0) {
    lines.push("RECOMMENDED QUESTIONS", "");
    brief.recommended_questions.forEach((question) => lines.push(`- ${question}`));
    lines.push("");
  }

  lines.push("SOURCES", "");
  brief.sources.forEach((source, index) => {
    lines.push(`[${index + 1}] ${source.title}`);
    lines.push(`    ${source.publisher} · ${formatDate(source.published_at)} · ${source.url}`);
  });

  return lines.join("\n");
}

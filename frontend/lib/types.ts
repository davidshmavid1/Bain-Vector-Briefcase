export type Confidence = "low" | "medium" | "high";

// Matches Tavily's own time_range values exactly (minus "day", too narrow a
// window for this product) — sent straight through, no client-side date math.
export type TimeRange = "week" | "month" | "year";

export const TIME_RANGE_OPTIONS: { value: TimeRange; label: string }[] = [
  { value: "week", label: "Week" },
  { value: "month", label: "Month" },
  { value: "year", label: "Year" },
];

export const FOCUS_AREAS = [
  { value: "technology", label: "Technology" },
  { value: "operations", label: "Operations" },
  { value: "strategy", label: "Strategy" },
  { value: "finance", label: "Finance" },
  { value: "people", label: "People" },
  { value: "regulatory", label: "Regulatory" },
  { value: "sustainability", label: "Sustainability" },
] as const;

export type FocusArea = (typeof FOCUS_AREAS)[number]["value"];

export interface BriefRequest {
  company: string;
  time_range: TimeRange;
  focus_areas?: FocusArea[];
}

export interface Source {
  id: string;
  title: string;
  url: string;
  publisher: string;
  published_at: string | null;
  snippet: string | null;
}

export interface Development {
  title: string;
  date: string | null;
  summary: string;
  why_it_matters: string;
  source_ids: string[];
}

export interface Insight {
  insight: string;
  rationale: string;
  source_ids: string[];
}

export interface CompanyBrief {
  company: string;
  generated_at: string;
  executive_summary: string;
  developments: Development[];
  risks: Insight[];
  opportunities: Insight[];
  talking_points: string[];
  recommended_questions: string[];
  sources: Source[];
  confidence: Confidence;
  time_range: TimeRange;
  is_demo: boolean;
}

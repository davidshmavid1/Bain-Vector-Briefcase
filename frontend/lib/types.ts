export type Confidence = "low" | "medium" | "high";

export type LookbackDays = 7 | 30 | 90;

export const LOOKBACK_OPTIONS: { value: LookbackDays; label: string }[] = [
  { value: 7, label: "7 days" },
  { value: 30, label: "30 days" },
  { value: 90, label: "90 days" },
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
  lookback_days: LookbackDays;
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
  lookback_days: number;
  is_demo: boolean;
}

import { ShieldAlert, ShieldCheck, ShieldQuestion } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import type { Confidence } from "@/lib/types";

const CONFIDENCE_META: Record<
  Confidence,
  { label: string; variant: "positive" | "caution" | "danger"; hint: string; Icon: typeof ShieldCheck }
> = {
  high: {
    label: "High confidence",
    variant: "positive",
    hint: "Several independent publishers corroborate this picture.",
    Icon: ShieldCheck,
  },
  medium: {
    label: "Medium confidence",
    variant: "caution",
    hint: "Coverage is partial or concentrated in few publishers.",
    Icon: ShieldQuestion,
  },
  low: {
    label: "Low confidence",
    variant: "danger",
    hint: "Coverage is thin or tangential — verify before relying on this.",
    Icon: ShieldAlert,
  },
};

export function ConfidenceBadge({ confidence }: { confidence: Confidence }) {
  const { label, variant, hint, Icon } = CONFIDENCE_META[confidence];
  return (
    <Badge variant={variant} title={hint}>
      <Icon aria-hidden="true" className="h-3.5 w-3.5" />
      {label}
    </Badge>
  );
}

export function confidenceHint(confidence: Confidence): string {
  return CONFIDENCE_META[confidence].hint;
}

/**
 * A more specific company name gives Tavily's search something to lock onto —
 * a bare surname like "Gerber" is genuinely ambiguous, but "Gerber Baby Food"
 * resolves cleanly. Only worth surfacing once confidence is already in doubt.
 */
export function refinementSuggestion(confidence: Confidence): string | null {
  if (confidence === "high") return null;
  return "If these results look off-topic or thin, try adding an industry or product descriptor to the name—for example, 'Gerber Baby Food' instead of just 'Gerber.' You can also extend the time-frame setting to broaden coverage and increase confidence in the results.";
}

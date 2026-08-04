"use client";

import * as React from "react";
import {
  AlertTriangle,
  ChevronDown,
  ExternalLink,
  FlaskConical,
  Lightbulb,
  MessageSquareQuote,
  Newspaper,
  Quote,
  TrendingUp,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfidenceBadge, confidenceHint, refinementSuggestion } from "@/components/confidence-badge";
import { CopyBriefButton } from "@/components/copy-brief-button";
import { formatDate, formatTimestamp } from "@/lib/format";
import type { CompanyBrief, Insight, Source } from "@/lib/types";

interface BriefReportProps {
  brief: CompanyBrief;
  onNewSearch: () => void;
}

export function BriefReport({ brief, onNewSearch }: BriefReportProps) {
  const positionById = React.useMemo(() => {
    const map = new Map<string, number>();
    brief.sources.forEach((source, index) => map.set(source.id, index + 1));
    return map;
  }, [brief.sources]);

  const hasBody =
    brief.developments.length > 0 ||
    brief.risks.length > 0 ||
    brief.opportunities.length > 0 ||
    brief.talking_points.length > 0 ||
    brief.recommended_questions.length > 0;

  // Low confidence means the entity resolution itself is in doubt — showing
  // "10 sources" and a development built from mismatched-entity coverage would
  // read as more authoritative than the brief actually is. The executive
  // summary plus the refinement hint above already tell the user what to do
  // next; everything else stays hidden until they narrow the query.
  const showEvidence = brief.confidence !== "low";

  return (
    <article className="space-y-10">
      <header className="relative space-y-6 border border-border border-t-4 border-t-primary bg-card p-6 shadow-[0_12px_40px_color-mix(in_oklch,var(--foreground)_7%,transparent)] sm:p-8">
        {brief.is_demo && (
          <p className="rounded-md border border-caution/40 bg-muted px-4 py-2.5 text-sm text-caution">
            <FlaskConical aria-hidden="true" className="mr-2 inline h-4 w-4" />
            Demo mode — this is bundled sample content, not live news coverage.
          </p>
        )}

        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="space-y-2">
            <p className="eyebrow text-primary">Client preparation brief</p>
            <h2 className="text-4xl font-semibold tracking-[-0.045em] sm:text-5xl">{brief.company}</h2>
            <p className="text-sm text-muted-foreground">
              Generated {formatTimestamp(brief.generated_at)} · Last {brief.time_range} ·{" "}
              {brief.sources.length} {brief.sources.length === 1 ? "source" : "sources"}
            </p>
          </div>
          <div className="flex shrink-0 flex-col items-start gap-3 sm:items-end">
            <ConfidenceBadge confidence={brief.confidence} />
            <Button variant="ghost" size="sm" onClick={onNewSearch}>
              New search
            </Button>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-border pt-5">
          <CopyBriefButton brief={brief} />
        </div>
      </header>

      <Section title="Executive summary">
        <p className="border-l-4 border-primary bg-card py-4 pl-6 pr-5 text-lg font-medium leading-8 text-foreground sm:text-xl">
          {brief.executive_summary}
        </p>
        <p className="mt-3 text-sm text-muted-foreground">{confidenceHint(brief.confidence)}</p>
        {refinementSuggestion(brief.confidence) && (
          <p className="mt-3 flex items-start gap-2 rounded-md border border-border bg-soft px-3 py-2 text-sm text-primary">
            <Lightbulb aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{refinementSuggestion(brief.confidence)}</span>
          </p>
        )}
      </Section>

      {showEvidence && (
        <>
          {brief.developments.length > 0 && (
            <Section title="Recent developments" icon={<Newspaper aria-hidden="true" className="h-4 w-4" />}>
              <ol className="space-y-4">
                {brief.developments.map((development, index) => (
                  <li key={`${development.title}-${index}`}>
                    <Card>
                      <CardHeader className="gap-2">
                        <div className="flex flex-wrap items-baseline justify-between gap-2">
                          <CardTitle>{development.title}</CardTitle>
                          {development.date && (
                            <span className="text-xs text-muted-foreground">{development.date}</span>
                          )}
                        </div>
                      </CardHeader>
                      <CardContent className="space-y-3">
                        <p className="text-sm leading-relaxed text-foreground">{development.summary}</p>
                        <p className="border-l-2 border-primary bg-soft/70 py-2 pl-4 pr-3 text-sm leading-relaxed text-muted-foreground">
                          <span className="font-medium text-foreground">Why it matters: </span>
                          {development.why_it_matters}
                        </p>
                        <SourceRefs ids={development.source_ids} positionById={positionById} />
                      </CardContent>
                    </Card>
                  </li>
                ))}
              </ol>
            </Section>
          )}

          {(brief.risks.length > 0 || brief.opportunities.length > 0) && (
            <div className="grid gap-8 lg:grid-cols-2">
              <InsightSection
                title="Risks"
                icon={<AlertTriangle aria-hidden="true" className="h-4 w-4 text-caution" />}
                items={brief.risks}
                positionById={positionById}
                emptyLabel="No evidence-backed risks surfaced in this coverage window."
              />
              <InsightSection
                title="Opportunities"
                icon={<TrendingUp aria-hidden="true" className="h-4 w-4 text-positive" />}
                items={brief.opportunities}
                positionById={positionById}
                emptyLabel="No evidence-backed opportunities surfaced in this coverage window."
              />
            </div>
          )}

          {brief.talking_points.length > 0 && (
            <Section title="Talking points" icon={<Quote aria-hidden="true" className="h-4 w-4" />}>
              <ul className="space-y-3">
                {brief.talking_points.map((point, index) => (
                  <li key={index} className="flex gap-3 text-sm leading-relaxed">
                    <span
                      aria-hidden="true"
                      className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-primary"
                    />
                    {point}
                  </li>
                ))}
              </ul>
            </Section>
          )}

          {brief.recommended_questions.length > 0 && (
            <Section
              title="Recommended client questions"
              icon={<MessageSquareQuote aria-hidden="true" className="h-4 w-4" />}
            >
              <ol className="space-y-3">
                {brief.recommended_questions.map((question, index) => (
                  <li key={index} className="flex gap-3 text-sm leading-relaxed">
                    <span className="w-5 shrink-0 font-mono text-xs text-muted-foreground">
                      {String(index + 1).padStart(2, "0")}
                    </span>
                    {question}
                  </li>
                ))}
              </ol>
            </Section>
          )}

          {!hasBody && (
            <Card>
              <CardContent className="p-6 text-sm text-muted-foreground">
                The retrieved coverage was too thin to support specific findings. Try a longer
                timeframe or a more precise company name.
              </CardContent>
            </Card>
          )}
        </>
      )}

      {/* Shown even at low confidence, unlike the model-authored sections above —
          letting the user inspect the raw sources themselves is strictly better
          than hiding everything behind one confidence label. */}
      <Section title={`Sources (${brief.sources.length})`}>
        <ol className="space-y-3">
          {brief.sources.map((source, index) => (
            <li key={source.id}>
              <SourceCard source={source} position={index + 1} />
            </li>
          ))}
        </ol>
      </Section>
    </article>
  );
}

function Section({
  title,
  icon,
  children,
}: {
  title: string;
  icon?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-4">
      <div className="flex items-center gap-4">
        <span aria-hidden="true" className="h-0.5 w-8 bg-primary" />
        <h3 className="flex items-center gap-2 text-xs font-bold uppercase tracking-[0.16em] text-foreground">
          {icon}
          {title}
        </h3>
      </div>
      {children}
    </section>
  );
}

function InsightSection({
  title,
  icon,
  items,
  positionById,
  emptyLabel,
}: {
  title: string;
  icon: React.ReactNode;
  items: Insight[];
  positionById: Map<string, number>;
  emptyLabel: string;
}) {
  return (
    <Section title={title} icon={icon}>
      {items.length === 0 ? (
        <p className="text-sm text-muted-foreground">{emptyLabel}</p>
      ) : (
        <ul className="space-y-4">
          {items.map((item, index) => (
            <li key={index}>
              <Card>
                <CardContent className="space-y-3 p-5">
                  <p className="text-sm font-medium leading-relaxed text-foreground">
                    {item.insight}
                  </p>
                  <p className="text-sm leading-relaxed text-muted-foreground">{item.rationale}</p>
                  <SourceRefs ids={item.source_ids} positionById={positionById} />
                </CardContent>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

function SourceRefs({
  ids,
  positionById,
}: {
  ids: string[];
  positionById: Map<string, number>;
}) {
  const positions = ids
    .map((id) => positionById.get(id))
    .filter((position): position is number => position !== undefined);

  if (positions.length === 0) return null;

  return (
    <p className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
      <span className="sr-only">Supporting sources:</span>
      <span aria-hidden="true">Sources</span>
      {positions.map((position) => (
        <a
          key={position}
          href={`#source-${position}`}
          className="rounded-sm border border-primary/30 bg-soft px-1.5 py-0.5 font-mono text-[0.6875rem] font-semibold text-primary transition-colors hover:border-primary"
        >
          {position}
        </a>
      ))}
    </p>
  );
}

function SourceCard({ source, position }: { source: Source; position: number }) {
  return (
    <Card id={`source-${position}`} className="scroll-mt-24 border-l-2 transition-colors hover:border-l-primary">
      <CardContent className="flex gap-4 p-5">
        <span className="mt-0.5 w-6 shrink-0 font-mono text-xs font-bold text-primary">
          {String(position).padStart(2, "0")}
        </span>
        <div className="min-w-0 flex-1 space-y-2">
          <a
            href={source.url}
            target="_blank"
            rel="noopener noreferrer"
            className="group inline-flex items-start gap-1.5 text-sm font-medium leading-snug text-foreground transition-colors hover:text-primary"
          >
            <span className="underline-offset-4 group-hover:underline">{source.title}</span>
            <ExternalLink
              aria-hidden="true"
              className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground"
            />
            <span className="sr-only">(opens in a new tab)</span>
          </a>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="muted">{source.publisher}</Badge>
            <span className="text-xs text-muted-foreground">{formatDate(source.published_at)}</span>
          </div>
          {source.snippet && (
            <details className="group pt-1">
              <summary className="flex cursor-pointer list-none items-center gap-1.5 text-xs font-semibold text-primary marker:content-none hover:text-foreground">
                <span>Show article excerpt</span>
                <ChevronDown
                  aria-hidden="true"
                  className="h-3.5 w-3.5 transition-transform group-open:rotate-180"
                />
              </summary>
              <p className="mt-3 border-l-2 border-border pl-4 text-sm leading-relaxed text-muted-foreground">
                {source.snippet}
              </p>
            </details>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

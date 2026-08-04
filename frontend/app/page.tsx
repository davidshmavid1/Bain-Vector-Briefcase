"use client";

import * as React from "react";

import { BriefForm, type BriefFormValues } from "@/components/brief-form";
import { BriefLoading } from "@/components/brief-loading";
import { BriefReport } from "@/components/brief-report";
import { ErrorNotice } from "@/components/error-notice";
import { ApiError, generateBrief } from "@/lib/api";
import { addRecentSearch, useRecentSearches } from "@/lib/recent-searches";
import type { CompanyBrief } from "@/lib/types";

const HIGHLIGHTS = [
  {
    title: "Recent coverage only",
    body: "Headlines from the last Week, Month or Year, deduplicated and ranked before any analysis runs.",
  },
  {
    title: "Sourced, not invented",
    body: "Every development, risk and opportunity cites the articles behind it. Unsupported claims are dropped.",
  },
  {
    title: "Built for the meeting",
    body: "Talking points and open questions you can take straight into a client conversation.",
  },
];

export default function HomePage() {
  const [brief, setBrief] = React.useState<CompanyBrief | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [isLoading, setIsLoading] = React.useState(false);
  const [pending, setPending] = React.useState<BriefFormValues | null>(null);
  const recentSearches = useRecentSearches();

  const requestRef = React.useRef<AbortController | null>(null);
  const resultsRef = React.useRef<HTMLDivElement | null>(null);

  React.useEffect(() => () => requestRef.current?.abort(), []);

  const runSearch = React.useCallback(async (values: BriefFormValues) => {
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;

    setPending(values);
    setIsLoading(true);
    setError(null);

    try {
      const result = await generateBrief(
        {
          company: values.company,
          time_range: values.timeRange,
          focus_areas: values.focusAreas.length > 0 ? values.focusAreas : undefined,
        },
        controller.signal,
      );
      if (controller.signal.aborted) return;
      setBrief(result);
      addRecentSearch(result.company);
    } catch (caught) {
      if (controller.signal.aborted) return;
      // The previous successful brief is deliberately left on screen.
      setError(
        caught instanceof ApiError
          ? caught.message
          : "Something went wrong while generating the brief. Please try again.",
      );
    } finally {
      if (!controller.signal.aborted) setIsLoading(false);
    }
  }, []);

  const handleSubmit = (values: BriefFormValues) => {
    void runSearch(values);
    window.requestAnimationFrame(() =>
      resultsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }),
    );
  };

  const handleRetry = () => {
    if (pending) void runSearch(pending);
  };

  const handleNewSearch = () => {
    requestRef.current?.abort();
    setBrief(null);
    setError(null);
    setPending(null);
    setIsLoading(false);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const hasResultsArea = isLoading || error !== null || brief !== null;

  return (
    <div className="min-h-screen">
      <header className="border-t-4 border-t-primary border-b border-b-border bg-background">
        <div className="mx-auto flex w-full max-w-7xl items-center justify-between px-5 py-5 sm:px-8">
          <div className="flex items-baseline gap-3">
            <p className="text-lg font-semibold tracking-[-0.04em]">Bain Vector</p>
            <span aria-hidden="true" className="h-4 w-px bg-border" />
            <p className="eyebrow text-muted-foreground">Briefcase</p>
          </div>
          <p className="hidden text-xs font-medium text-muted-foreground sm:block">Client preparation intelligence</p>
        </div>
      </header>

      <div className="mx-auto w-full max-w-7xl px-5 sm:px-8">
        <section className="grid gap-12 py-16 sm:py-24 lg:grid-cols-[minmax(0,1fr)_15rem] lg:items-end lg:gap-20">
          <div>
            <p className="eyebrow mb-7 flex items-center gap-3 text-primary">
              <span aria-hidden="true" className="h-px w-8 bg-primary" />
              Partner-ready preparation
            </p>
            <h1 className="max-w-4xl text-5xl font-semibold leading-[1.01] tracking-[-0.055em] sm:text-6xl lg:text-7xl">
              Get to the point
              <span className="block">before the meeting does.</span>
            </h1>
            <p className="mt-8 max-w-2xl text-lg leading-8 text-muted-foreground sm:text-xl">
              A clear, sourced view of the company, the forces shaping it, and the questions worth
              bringing into the room.
            </p>
          </div>

          <aside className="border-t border-foreground pt-5" aria-label="Brief qualities">
            <p className="eyebrow text-foreground">The brief</p>
            <dl className="mt-5 space-y-4 text-sm">
              <div className="flex items-baseline justify-between gap-4">
                <dt className="text-muted-foreground">Coverage</dt>
                <dd className="font-semibold">Current</dd>
              </div>
              <div className="flex items-baseline justify-between gap-4">
                <dt className="text-muted-foreground">Analysis</dt>
                <dd className="font-semibold">Evidence-led</dd>
              </div>
              <div className="flex items-baseline justify-between gap-4">
                <dt className="text-muted-foreground">Format</dt>
                <dd className="font-semibold">Meeting-ready</dd>
              </div>
            </dl>
          </aside>
        </section>

        <section className="border-y border-foreground bg-card py-8 sm:py-10">
          <div className="grid gap-8 px-6 sm:px-10 lg:grid-cols-[13rem_minmax(0,1fr)] lg:gap-12">
            <div>
              <p className="eyebrow text-primary">Create a brief</p>
              <h2 className="mt-3 text-2xl font-semibold leading-tight tracking-[-0.035em]">
                Start with the company.
              </h2>
              <p className="mt-3 text-sm leading-6 text-muted-foreground">
                We will handle the recent news, synthesis, and source trail.
              </p>
            </div>
            <BriefForm isSubmitting={isLoading} recentSearches={recentSearches} onSubmit={handleSubmit} />
          </div>
        </section>

        <div ref={resultsRef} className="scroll-mt-8">
          {hasResultsArea && (
            <div className="mx-auto mt-20 max-w-5xl space-y-8">
              {error !== null && (
                <ErrorNotice
                  message={error}
                  onRetry={handleRetry}
                  isRetrying={isLoading}
                  keepsPreviousReport={brief !== null}
                />
              )}

              {isLoading && pending ? (
                <BriefLoading company={pending.company} />
              ) : (
                brief !== null && <BriefReport brief={brief} onNewSearch={handleNewSearch} />
              )}
            </div>
          )}
        </div>

        {!hasResultsArea && (
          <section className="grid border-b border-border py-12 sm:grid-cols-3 sm:divide-x sm:divide-border sm:py-16" aria-label="Why use Vector Briefcase">
            {HIGHLIGHTS.map((item, index) => (
              <div key={item.title} className="py-7 sm:px-8 sm:py-0 first:sm:pl-0 last:sm:pr-0">
                <span className="font-mono text-xs font-semibold text-primary">0{index + 1}</span>
                <h2 className="mt-5 text-lg font-semibold tracking-tight text-foreground">{item.title}</h2>
                <p className="mt-3 text-sm leading-6 text-muted-foreground">{item.body}</p>
              </div>
            ))}
          </section>
        )}

        <footer className="flex flex-col gap-4 py-8 sm:flex-row sm:items-start sm:justify-between">
          <p className="text-sm font-semibold tracking-[-0.02em]">Bain Vector Briefcase</p>
          <p className="max-w-2xl text-xs leading-relaxed text-muted-foreground sm:text-right">
            Briefs are generated from public news metadata and are a starting point for preparation,
            not a substitute for diligence. Nothing here is investment advice.
          </p>
        </footer>
      </div>
    </div>
  );
}

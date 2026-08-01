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
    body: "Headlines from the last 7, 30 or 90 days, deduplicated and ranked before any analysis runs.",
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
          lookback_days: values.lookbackDays,
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
    <div className="mx-auto w-full max-w-4xl px-5 py-12 sm:px-8 sm:py-16">
      <header className="space-y-5">
        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">
          Company intelligence
        </p>
        <h1 className="text-4xl font-semibold leading-[1.1] tracking-tight sm:text-5xl">
          Walk into every client meeting already briefed.
        </h1>
        <p className="max-w-2xl text-lg leading-relaxed text-muted-foreground">
          Enter a company and get a partner-ready brief built from recent news coverage — what
          happened, why it matters, the risks and opportunities it opens, and the questions worth
          asking. Every finding is tied back to the sources it came from.
        </p>
      </header>

      <section className="mt-10 rounded-lg border border-border bg-card p-6 sm:p-8">
        <BriefForm isSubmitting={isLoading} recentSearches={recentSearches} onSubmit={handleSubmit} />
      </section>

      <div ref={resultsRef} className="scroll-mt-8">
        {hasResultsArea && (
          <div className="mt-12 space-y-8">
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
        <section className="mt-12 grid gap-6 sm:grid-cols-3">
          {HIGHLIGHTS.map((item) => (
            <div key={item.title} className="space-y-2">
              <h2 className="text-sm font-semibold text-foreground">{item.title}</h2>
              <p className="text-sm leading-relaxed text-muted-foreground">{item.body}</p>
            </div>
          ))}
        </section>
      )}

      <footer className="mt-16 border-t border-border pt-6">
        <p className="text-xs leading-relaxed text-muted-foreground">
          Briefs are generated from public news metadata and are a starting point for preparation,
          not a substitute for diligence. Nothing here is investment advice.
        </p>
      </footer>
    </div>
  );
}

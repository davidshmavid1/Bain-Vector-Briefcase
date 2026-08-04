"use client";

import * as React from "react";
import { ArrowRight, Check, Clock, Loader2, Search } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import { FOCUS_AREAS, TIME_RANGE_OPTIONS, type FocusArea, type TimeRange } from "@/lib/types";

const EXAMPLE_COMPANIES = ["Microsoft", "Siemens", "Unilever", "Rivian", "Maersk"];

export interface BriefFormValues {
  company: string;
  timeRange: TimeRange;
  focusAreas: FocusArea[];
}

interface BriefFormProps {
  isSubmitting: boolean;
  recentSearches: string[];
  onSubmit: (values: BriefFormValues) => void;
  variant?: "hero" | "compact";
}

export function BriefForm({
  isSubmitting,
  recentSearches,
  onSubmit,
  variant = "hero",
}: BriefFormProps) {
  const [company, setCompany] = React.useState("");
  const [timeRange, setTimeRange] = React.useState<TimeRange>("month");
  const [focusAreas, setFocusAreas] = React.useState<FocusArea[]>([]);
  const [touched, setTouched] = React.useState(false);

  const trimmed = company.trim();
  const isTooShort = trimmed.length > 0 && trimmed.length < 2;
  const showError = touched && (trimmed.length === 0 || isTooShort);

  const toggleFocus = (area: FocusArea) =>
    setFocusAreas((current) =>
      current.includes(area) ? current.filter((item) => item !== area) : [...current, area],
    );

  const submit = (name: string) => {
    const value = name.trim();
    if (value.length < 2) {
      setTouched(true);
      return;
    }
    onSubmit({ company: value, timeRange, focusAreas });
  };

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setTouched(true);
    submit(company);
  };

  const pickSuggestion = (name: string) => {
    setCompany(name);
    setTouched(true);
    submit(name);
  };

  return (
    <form onSubmit={handleSubmit} noValidate>
      <fieldset disabled={isSubmitting} className="space-y-8 disabled:opacity-70">
        <legend className="sr-only">Generate a company brief</legend>

        <div className="space-y-3">
          <Label htmlFor="company">Company or organization</Label>
          <div className="flex flex-col gap-3 sm:flex-row">
            <div className="relative flex-1">
              <Search
                aria-hidden="true"
                className="pointer-events-none absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-primary"
              />
              <Input
                id="company"
                name="company"
                value={company}
                onChange={(event) => setCompany(event.target.value)}
                onBlur={() => setTouched(true)}
                placeholder="Enter a company name, e.g. Microsoft"
                autoComplete="organization"
                maxLength={120}
                className="h-14 pl-12 text-lg"
                aria-invalid={showError}
                aria-describedby={showError ? "company-error" : "company-hint"}
              />
            </div>
            <Button
              type="submit"
              size="lg"
              className={cn("h-14 sm:w-auto", variant === "hero" && "sm:px-9")}
            >
              {isSubmitting ? (
                <>
                  <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />
                  Generating
                </>
              ) : (
                <>
                  Generate brief
                  <ArrowRight aria-hidden="true" className="h-4 w-4" />
                </>
              )}
            </Button>
          </div>
          {showError ? (
            <p id="company-error" role="alert" className="text-sm text-danger">
              Enter a company name of at least 2 characters.
            </p>
          ) : (
            <p id="company-hint" className="text-sm text-muted-foreground">
              Public companies with recent English-language coverage work best.
            </p>
          )}
        </div>

        <div className="grid gap-7 lg:grid-cols-[auto_1fr] lg:gap-12">
          <div className="space-y-2">
            <Label id="timeframe-label">Timeframe</Label>
            <div
              role="radiogroup"
              aria-labelledby="timeframe-label"
              className="inline-flex rounded-sm border border-input bg-muted/50 p-1"
            >
              {TIME_RANGE_OPTIONS.map((option) => {
                const selected = option.value === timeRange;
                return (
                  <button
                    key={option.value}
                    type="button"
                    role="radio"
                    aria-checked={selected}
                    onClick={() => setTimeRange(option.value)}
                    className={cn(
                      "rounded-sm px-4 py-1.5 text-sm font-semibold transition-all",
                      selected
                        ? "bg-primary text-primary-foreground"
                        : "text-muted-foreground hover:text-foreground",
                    )}
                  >
                    {option.label}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="space-y-2">
            <Label id="focus-label">
              Focus areas <span className="font-normal normal-case tracking-normal">(optional)</span>
            </Label>
            <div role="group" aria-labelledby="focus-label" className="flex flex-wrap gap-2">
              {FOCUS_AREAS.map((area) => {
                const selected = focusAreas.includes(area.value);
                return (
                  <button
                    key={area.value}
                    type="button"
                    aria-pressed={selected}
                    data-state={selected ? "on" : "off"}
                    onClick={() => toggleFocus(area.value)}
                    className={cn(
                      "inline-flex cursor-pointer items-center gap-1.5 rounded-sm border px-3 py-1.5 text-sm transition-all active:scale-[0.98]",
                      selected
                        ? "border-primary bg-primary font-semibold text-primary-foreground ring-2 ring-primary/20 ring-offset-1 ring-offset-card"
                        : "border-input bg-card text-muted-foreground hover:border-primary hover:bg-soft hover:text-primary",
                    )}
                  >
                    {selected && <Check aria-hidden="true" className="h-3.5 w-3.5" />}
                    {area.label}
                  </button>
                );
              })}
            </div>
          </div>
        </div>

        {variant === "hero" && (
          <div className="space-y-3 border-t border-border pt-7">
            <SuggestionRow
              label="Try an example"
              names={EXAMPLE_COMPANIES}
              onPick={pickSuggestion}
            />
            {recentSearches.length > 0 && (
              <SuggestionRow
                label="Recent"
                icon={<Clock aria-hidden="true" className="h-3.5 w-3.5" />}
                names={recentSearches}
                onPick={pickSuggestion}
              />
            )}
          </div>
        )}
      </fieldset>
    </form>
  );
}

function SuggestionRow({
  label,
  names,
  onPick,
  icon,
}: {
  label: string;
  names: string[];
  onPick: (name: string) => void;
  icon?: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
      <span className="inline-flex items-center gap-1.5 text-xs font-semibold uppercase tracking-[0.08em] text-muted-foreground">
        {icon}
        {label}
      </span>
      {names.map((name) => (
        <button
          key={name}
          type="button"
          onClick={() => onPick(name)}
          className="border-b border-transparent px-1 py-0.5 text-sm font-medium text-muted-foreground transition-colors hover:border-primary hover:text-primary"
        >
          {name}
        </button>
      ))}
    </div>
  );
}

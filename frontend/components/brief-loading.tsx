"use client";

import * as React from "react";

import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

const LOADING_MESSAGES = [
  "Searching recent company news…",
  "Removing duplicate coverage…",
  "Identifying risks and opportunities…",
  "Preparing your client brief…",
];

const MESSAGE_INTERVAL_MS = 3200;

export function BriefLoading({ company }: { company: string }) {
  const [index, setIndex] = React.useState(0);

  React.useEffect(() => {
    const timer = window.setInterval(
      () => setIndex((current) => (current + 1) % LOADING_MESSAGES.length),
      MESSAGE_INTERVAL_MS,
    );
    return () => window.clearInterval(timer);
  }, []);

  return (
    <div className="space-y-6">
      <div
        role="status"
        aria-live="polite"
        className="flex items-center gap-3 rounded-lg border border-border bg-card px-5 py-4"
      >
        <span
          aria-hidden="true"
          className="h-2.5 w-2.5 shrink-0 animate-pulse rounded-full bg-primary"
        />
        <p className="text-sm text-foreground">
          <span className="font-medium">{company}</span>
          <span className="text-muted-foreground"> — {LOADING_MESSAGES[index]}</span>
        </p>
      </div>

      <Card>
        <CardHeader className="gap-3">
          <Skeleton className="h-3 w-32" />
          <Skeleton className="h-7 w-3/5" />
        </CardHeader>
        <CardContent className="space-y-3">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-4/5" />
        </CardContent>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        {[0, 1, 2, 3].map((key) => (
          <Card key={key}>
            <CardHeader className="gap-3">
              <Skeleton className="h-3 w-24" />
              <Skeleton className="h-5 w-2/3" />
            </CardHeader>
            <CardContent className="space-y-3">
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-5/6" />
              <Skeleton className="h-4 w-1/2" />
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}

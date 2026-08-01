"use client";

import { AlertCircle, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";

interface ErrorNoticeProps {
  message: string;
  onRetry: () => void;
  isRetrying: boolean;
  /** Shown when a retry failed but an earlier brief is still on screen. */
  keepsPreviousReport?: boolean;
}

export function ErrorNotice({
  message,
  onRetry,
  isRetrying,
  keepsPreviousReport = false,
}: ErrorNoticeProps) {
  return (
    <div
      role="alert"
      className="flex flex-col gap-4 rounded-lg border border-danger/35 bg-card p-5 sm:flex-row sm:items-start"
    >
      <AlertCircle aria-hidden="true" className="h-5 w-5 shrink-0 text-danger sm:mt-0.5" />
      <div className="flex-1 space-y-1.5">
        <p className="text-sm font-medium text-foreground">Could not generate the brief</p>
        <p className="text-sm text-muted-foreground">{message}</p>
        {keepsPreviousReport && (
          <p className="text-sm text-muted-foreground">
            Your previous brief is still shown below.
          </p>
        )}
      </div>
      <Button variant="outline" size="sm" onClick={onRetry} disabled={isRetrying}>
        <RefreshCw aria-hidden="true" className={isRetrying ? "h-4 w-4 animate-spin" : "h-4 w-4"} />
        {isRetrying ? "Retrying" : "Try again"}
      </Button>
    </div>
  );
}

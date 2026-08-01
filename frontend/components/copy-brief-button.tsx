"use client";

import * as React from "react";
import { Check, Copy } from "lucide-react";

import { Button } from "@/components/ui/button";
import { briefToPlainText } from "@/lib/format";
import type { CompanyBrief } from "@/lib/types";

type CopyState = "idle" | "copied" | "failed";

export function CopyBriefButton({ brief }: { brief: CompanyBrief }) {
  const [state, setState] = React.useState<CopyState>("idle");

  React.useEffect(() => {
    if (state === "idle") return;
    const timer = window.setTimeout(() => setState("idle"), 2400);
    return () => window.clearTimeout(timer);
  }, [state]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(briefToPlainText(brief));
      setState("copied");
    } catch {
      setState("failed");
    }
  };

  return (
    <div className="flex items-center gap-2">
      <Button variant="outline" size="sm" onClick={copy}>
        {state === "copied" ? (
          <Check aria-hidden="true" className="h-4 w-4 text-positive" />
        ) : (
          <Copy aria-hidden="true" className="h-4 w-4" />
        )}
        Copy brief
      </Button>
      <span role="status" aria-live="polite" className="text-sm text-muted-foreground">
        {state === "copied" && "Copied to clipboard"}
        {state === "failed" && (
          <span className="text-danger">Copy failed — select and copy manually</span>
        )}
      </span>
    </div>
  );
}

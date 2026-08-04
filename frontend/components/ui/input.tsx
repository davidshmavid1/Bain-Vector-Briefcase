import * as React from "react";

import { cn } from "@/lib/utils";

const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, type = "text", ...props }, ref) => (
    <input
      ref={ref}
      type={type}
      className={cn(
        "flex h-12 w-full rounded-sm border border-input bg-card px-4 py-2 text-base text-foreground shadow-[inset_0_1px_0_color-mix(in_oklch,var(--foreground)_4%,transparent)] transition-all focus:border-primary focus:shadow-[0_0_0_3px_color-mix(in_oklch,var(--primary)_12%,transparent)]",
        "placeholder:text-muted-foreground disabled:cursor-not-allowed disabled:opacity-60",
        className,
      )}
      {...props}
    />
  ),
);
Input.displayName = "Input";

export { Input };

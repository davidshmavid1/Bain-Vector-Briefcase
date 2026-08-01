import * as React from "react";

import { cn } from "@/lib/utils";

const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, type = "text", ...props }, ref) => (
    <input
      ref={ref}
      type={type}
      className={cn(
        "flex h-12 w-full rounded-md border border-input bg-card px-4 py-2 text-base text-foreground shadow-[0_1px_2px_rgba(15,23,42,0.04)] transition-colors",
        "placeholder:text-muted-foreground disabled:cursor-not-allowed disabled:opacity-60",
        className,
      )}
      {...props}
    />
  ),
);
Input.displayName = "Input";

export { Input };

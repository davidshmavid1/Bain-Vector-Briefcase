import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium",
  {
    variants: {
      variant: {
        default: "border-transparent bg-soft text-primary",
        outline: "border-border bg-transparent text-muted-foreground",
        muted: "border-transparent bg-muted text-muted-foreground",
        positive: "border-transparent bg-muted text-positive",
        caution: "border-transparent bg-muted text-caution",
        danger: "border-transparent bg-muted text-danger",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge, badgeVariants };

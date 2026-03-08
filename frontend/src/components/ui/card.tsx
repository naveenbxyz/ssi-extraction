import type { HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "rounded-3xl border border-white/70 bg-panel/90 shadow-panel backdrop-blur supports-[backdrop-filter]:bg-panel/75",
        className,
      )}
      {...props}
    />
  );
}

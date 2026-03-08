import type { ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
};

const variants: Record<NonNullable<ButtonProps["variant"]>, string> = {
  primary:
    "bg-accent text-white shadow-panel hover:bg-[hsl(var(--accent)/0.92)] disabled:bg-[hsl(var(--accent)/0.55)]",
  secondary:
    "bg-ink text-white hover:bg-[hsl(var(--ink)/0.92)] disabled:bg-[hsl(var(--ink)/0.55)]",
  ghost:
    "bg-white/70 text-ink ring-1 ring-inset ring-line hover:bg-white disabled:text-muted",
  danger:
    "bg-danger text-white hover:bg-[hsl(var(--danger)/0.9)] disabled:bg-[hsl(var(--danger)/0.55)]",
};

export function Button({ className, variant = "primary", type = "button", ...props }: ButtonProps) {
  return (
    <button
      type={type}
      className={cn(
        "inline-flex items-center justify-center rounded-full px-4 py-2 text-sm font-semibold transition disabled:cursor-not-allowed",
        variants[variant],
        className,
      )}
      {...props}
    />
  );
}

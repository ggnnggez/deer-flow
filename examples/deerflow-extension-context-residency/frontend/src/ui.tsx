import { clsx, type ClassValue } from "clsx";
import type { ButtonHTMLAttributes, HTMLAttributes } from "react";

export function cn(...inputs: ClassValue[]): string {
  return clsx(inputs);
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "secondary" | "ghost" | "outline";
  size?: "sm";
};

const BUTTON_VARIANTS: Record<NonNullable<ButtonProps["variant"]>, string> = {
  secondary: "bg-secondary text-secondary-foreground hover:bg-secondary/80",
  ghost: "hover:bg-muted",
  outline: "border bg-background hover:bg-muted",
};

export function Button({ variant = "outline", size, className, type = "button", ...rest }: ButtonProps) {
  return (
    <button
      type={type}
      className={cn(
        "inline-flex items-center justify-center gap-1.5 rounded-md text-sm font-medium whitespace-nowrap transition-colors disabled:pointer-events-none disabled:opacity-50",
        size === "sm" ? "h-8 px-3 text-xs" : "h-9 px-4",
        BUTTON_VARIANTS[variant],
        className,
      )}
      {...rest}
    />
  );
}

export function Badge({ className, ...rest }: HTMLAttributes<HTMLSpanElement>) {
  return <span className={cn("inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium", className)} {...rest} />;
}

export function Skeleton({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("bg-muted animate-pulse rounded-md", className)} {...rest} />;
}

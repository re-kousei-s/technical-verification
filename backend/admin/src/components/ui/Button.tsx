import type { ButtonHTMLAttributes } from "react";

type Variant = "filled" | "outlined" | "text" | "danger";

const VARIANTS: Record<Variant, string> = {
  filled: "bg-primary text-white hover:opacity-90",
  outlined: "border border-line text-primary hover:bg-primary-soft",
  text: "text-primary hover:bg-primary-soft",
  danger: "border border-bad/40 text-bad hover:bg-bad-soft",
};

export function Button({ variant = "outlined", className = "", ...rest }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      {...rest}
      className={`inline-flex h-9 items-center justify-center gap-1.5 whitespace-nowrap rounded-full px-4 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-40 ${VARIANTS[variant]} ${className}`}
    />
  );
}

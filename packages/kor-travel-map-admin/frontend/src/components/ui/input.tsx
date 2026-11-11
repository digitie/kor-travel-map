"use client";
import type { ComponentProps } from "react";
import { Input as CommonInput } from "@kor-travel/ui/input";
import { cn } from "@/lib/utils";

export type InputProps = Omit<ComponentProps<typeof CommonInput>, "size"> & {
  size?: "sm" | "default";
};
export function Input({ size = "default", className, ...props }: InputProps) {
  return (
    <CommonInput
      data-size={size}
      className={cn(
        "h-control text-sm",
        size === "sm" && "h-control-sm px-2.5 text-xs",
        className,
      )}
      {...props}
    />
  );
}

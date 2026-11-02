import React from "react";
import { cn } from "@/lib/cn";

export interface FieldProps {
  label: string;
  htmlFor?: string;
  hint?: string;
  error?: string;
  required?: boolean;
  children: React.ReactNode;
  className?: string;
}

/** Label + control + hint/error, matching the shared form styles. */
export function Field({
  label,
  htmlFor,
  hint,
  error,
  required,
  children,
  className,
}: FieldProps) {
  return (
    <div className={cn("min-w-0", className)}>
      <label className="field-label" htmlFor={htmlFor}>
        {label}
        {required ? <span className="ml-0.5 text-danger">*</span> : null}
      </label>
      {children}
      {error ? (
        <p className="field-error">{error}</p>
      ) : hint ? (
        <p className="field-hint">{hint}</p>
      ) : null}
    </div>
  );
}

// Field components are forwardRef wrappers so react-hook-form's register()
// ref reaches the native element (required for uncontrolled forms to read
// values back during validation/submit).
export const TextInput = React.forwardRef<
  HTMLInputElement,
  React.InputHTMLAttributes<HTMLInputElement>
>(function TextInput({ className, ...rest }, ref) {
  return <input ref={ref} {...rest} className={cn("input", className)} />;
});

export const TextArea = React.forwardRef<
  HTMLTextAreaElement,
  React.TextareaHTMLAttributes<HTMLTextAreaElement>
>(function TextArea({ className, ...rest }, ref) {
  return <textarea ref={ref} {...rest} className={cn("input", className)} />;
});

export const Select = React.forwardRef<
  HTMLSelectElement,
  React.SelectHTMLAttributes<HTMLSelectElement>
>(function Select({ className, children, ...rest }, ref) {
  return (
    <select ref={ref} {...rest} className={cn("input", className)}>
      {children}
    </select>
  );
});

export const Checkbox = React.forwardRef<
  HTMLInputElement,
  React.InputHTMLAttributes<HTMLInputElement> & { label: React.ReactNode }
>(function Checkbox({ className, label, ...rest }, ref) {
  return (
    <label className="flex cursor-pointer items-center gap-2 text-sm text-ink-soft">
      <input
        type="checkbox"
        ref={ref}
        {...rest}
        className={cn(
          "h-4 w-4 rounded border-border text-water-700 focus:ring-water-600",
          className,
        )}
      />
      <span>{label}</span>
    </label>
  );
});

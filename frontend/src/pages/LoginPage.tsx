import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import { Button } from "@/components/ui/Button";
import { Field, TextInput } from "@/components/ui/Field";
import { ApiError } from "@/lib/api";

const schema = z.object({
  email: z.string().min(1, "Email is required").email("Enter a valid email address"),
  password: z.string().min(1, "Password is required"),
});

type FormValues = z.infer<typeof schema>;

export function LoginPage() {
  const { user, ready, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [formError, setFormError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { email: "", password: "" },
  });

  if (ready && user) {
    const from = (location.state as { from?: string } | null)?.from;
    return <Navigate to={from && from !== "/login" ? from : "/"} replace />;
  }

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      await login(values.email.trim(), values.password);
      navigate("/", { replace: true });
    } catch (error) {
      // The backend deliberately does not distinguish unknown account from bad
      // password; show its message as-is.
      setFormError(
        error instanceof ApiError
          ? error.message
          : "Sign in failed. Please check the API is running.",
      );
    }
  });

  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas px-4 py-12">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-md bg-water-700 text-base font-semibold text-white">
            LW
          </span>
          <div className="leading-tight">
            <p className="text-lg font-semibold text-ink">LakeWatch</p>
            <p className="text-sm text-muted">Lake Malawi monitoring console</p>
          </div>
        </div>

        <div className="card px-6 py-6">
          <h1 className="text-base font-semibold text-ink">Sign in</h1>
          <p className="mt-1 text-sm text-muted">
            Use the account issued by your system administrator.
          </p>

          <form className="mt-5 space-y-4" onSubmit={onSubmit} noValidate>
            <Field label="Email" htmlFor="email" error={errors.email?.message} required>
              <TextInput
                id="email"
                type="email"
                autoComplete="username"
                placeholder="you@example.org"
                {...register("email")}
              />
            </Field>

            <Field label="Password" htmlFor="password" error={errors.password?.message} required>
              <TextInput
                id="password"
                type="password"
                autoComplete="current-password"
                placeholder="••••••••"
                {...register("password")}
              />
            </Field>

            {formError ? (
              <p className="rounded-md border border-danger/30 bg-danger-light px-3 py-2 text-sm text-danger-dark">
                {formError}
              </p>
            ) : null}

            <Button type="submit" className="w-full" loading={isSubmitting}>
              Sign in
            </Button>
          </form>
        </div>

        <p className="mt-4 text-center text-xs text-muted">
          Accounts are created by administrators — there is no self-registration.{" "}
          <Link to="/public" className="text-water-700 underline-offset-4 hover:underline">
            View the public dashboard
          </Link>
          .
        </p>
      </div>
    </div>
  );
}

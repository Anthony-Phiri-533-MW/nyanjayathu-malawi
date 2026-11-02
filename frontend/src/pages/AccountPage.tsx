import { useState } from "react";
import { useAuth } from "@/auth/AuthContext";
import { PageHeader } from "@/components/PageHeader";
import { Badge, Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Field, TextInput } from "@/components/ui/Field";
import { DetailList } from "@/components/PageHeader";
import { ApiError } from "@/lib/api";
import { useChangePassword } from "@/lib/hooks";
import { formatDateTime, titleCase } from "@/lib/format";

/**
 * The signed-in user's own account. Password changes go through the API, which
 * re-checks the current password; there is no self-service profile editing
 * because name/department/roles are administrative fields.
 */
export function AccountPage() {
  const { user, can } = useAuth();
  const changePassword = useChangePassword();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [banner, setBanner] = useState<{ tone: "ok" | "error"; text: string } | null>(null);

  const permissions = user?.permissions ?? [];

  const submit = async () => {
    setBanner(null);
    if (next !== confirm) {
      setBanner({ tone: "error", text: "The new passwords do not match." });
      return;
    }
    if (next.length < 10) {
      setBanner({ tone: "error", text: "The new password must be at least 10 characters." });
      return;
    }
    try {
      const result = await changePassword.mutateAsync({
        current_password: current,
        new_password: next,
      });
      setBanner({ tone: "ok", text: result.message });
      setCurrent("");
      setNext("");
      setConfirm("");
    } catch (error) {
      setBanner({
        tone: "error",
        text: error instanceof ApiError ? error.message : "Could not change the password.",
      });
    }
  };

  return (
    <div>
      <PageHeader
        title="Your account"
        description="Your identity, roles and the permissions the API has granted you on this deployment."
      />

      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader title="Profile" />
          <CardBody>
            <DetailList
              columns={2}
              items={[
                { label: "Name", value: user?.full_name ?? "—" },
                { label: "Email", value: user?.email ?? "—" },
                { label: "Department", value: user?.department ?? "—" },
                {
                  label: "Status",
                  value: (
                    <Badge
                      className={
                        user?.is_active
                          ? "bg-success-light text-success-dark"
                          : "bg-canvas text-muted"
                      }
                    >
                      {user?.is_active ? "Active" : "Inactive"}
                    </Badge>
                  ),
                },
                { label: "Last sign-in", value: formatDateTime(user?.last_login_at) },
                { label: "Created", value: formatDateTime(user?.created_at) },
              ]}
            />
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Change password" description="You must confirm your current password." />
          <form
            className="space-y-4 px-5 py-4"
            onSubmit={(e) => {
              e.preventDefault();
              void submit();
            }}
          >
            <Field label="Current password" htmlFor="pw-current" required>
              <TextInput
                id="pw-current"
                type="password"
                autoComplete="current-password"
                value={current}
                onChange={(e) => setCurrent(e.target.value)}
                required
              />
            </Field>
            <Field label="New password" htmlFor="pw-new" hint="At least 10 characters." required>
              <TextInput
                id="pw-new"
                type="password"
                autoComplete="new-password"
                value={next}
                onChange={(e) => setNext(e.target.value)}
                minLength={10}
                required
              />
            </Field>
            <Field label="Confirm new password" htmlFor="pw-confirm" required>
              <TextInput
                id="pw-confirm"
                type="password"
                autoComplete="new-password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                required
              />
            </Field>
            {banner ? (
              <p
                className={
                  banner.tone === "ok"
                    ? "rounded-md border border-success/30 bg-success-light px-3 py-2 text-sm text-success-dark"
                    : "rounded-md border border-danger/30 bg-danger-light px-3 py-2 text-sm text-danger-dark"
                }
              >
                {banner.text}
              </p>
            ) : null}
            <Button type="submit" loading={changePassword.isPending}>
              Update password
            </Button>
          </form>
        </Card>
      </div>

      <Card className="mt-5">
        <CardHeader
          title="Roles & permissions"
          description="Permissions are defined by the backend and enforced there; this is a read-only view."
        />
        <CardBody>
          <div className="flex flex-wrap gap-2">
            {(user?.roles ?? []).map((role) => (
              <Badge key={role} className="bg-water-50 text-water-700">
                {titleCase(role)}
              </Badge>
            ))}
          </div>
          {permissions.length === 0 ? (
            <p className="mt-3 text-sm text-muted">
              {user?.roles.includes("super_admin")
                ? "Super Administrator: every permission is granted."
                : "No permissions granted."}
            </p>
          ) : (
            <ul className="mt-3 grid gap-1 sm:grid-cols-2 lg:grid-cols-3">
              {permissions.map((permission) => (
                <li key={permission} className="font-mono text-xs text-ink-soft">
                  {permission}
                </li>
              ))}
            </ul>
          )}
          {can("admin.audit.read") ? (
            <p className="mt-4 text-xs text-muted">
              Your administrative actions are recorded in the audit log.
            </p>
          ) : null}
        </CardBody>
      </Card>
    </div>
  );
}

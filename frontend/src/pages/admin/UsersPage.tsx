import { useMemo, useState } from "react";
import { KeyRound, Plus } from "lucide-react";
import { useAuth } from "@/auth/AuthContext";
import { PageHeader } from "@/components/PageHeader";
import { Badge, Card, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Checkbox, Field, TextInput } from "@/components/ui/Field";
import { EmptyState, ErrorState, LoadingRows } from "@/components/ui/States";
import { Pagination, Table, Td, Th, Tr } from "@/components/ui/Table";
import { ApiError } from "@/lib/api";
import {
  useCreateUser,
  useIssuePasswordReset,
  useRoles,
  useSetUserActive,
  useSetUserRoles,
  useUsers,
} from "@/lib/hooks";
import { formatDateTime, titleCase } from "@/lib/format";
import type { PasswordResetOut, User } from "@/lib/types";

/**
 * Role ordering mirrors the backend (`app/core/permissions.py`). A user may
 * only assign roles strictly below their own highest rank; only a Super
 * Administrator sees/assigns `super_admin`. The server re-checks all of this.
 */
const ROLE_RANK: Record<string, number> = { researcher: 1, admin: 2, super_admin: 3 };

function maxRank(roles: string[]): number {
  return roles.reduce((max, r) => Math.max(max, ROLE_RANK[r] ?? 0), 0);
}

export function UsersPage() {
  const { user: me, can } = useAuth();
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [showCreate, setShowCreate] = useState(false);
  const [resetResult, setResetResult] = useState<PasswordResetOut | null>(null);
  const [banner, setBanner] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const [editing, setEditing] = useState<User | null>(null);

  const users = useUsers({ search: search || undefined, page, size: 20 });
  const roles = useRoles();

  const canWrite = can("admin.users.write");
  const isSuper = (me?.roles ?? []).includes("super_admin");
  const myRank = maxRank(me?.roles ?? []);

  // Only roles the current actor may grant are offered.
  const grantableRoles = useMemo(
    () =>
      (roles.data ?? []).filter((r) => (ROLE_RANK[r.name] ?? 0) < myRank || (isSuper && r.name === "super_admin" && myRank >= 3)),
    [roles.data, myRank, isSuper],
  );

  const setActive = useSetUserActive();
  const issueReset = useIssuePasswordReset();

  const report = (tone: "ok" | "error", text: string) => setBanner({ tone, text });

  return (
    <div>
      <PageHeader
        title="Users & roles"
        description="Accounts, role assignments and activation state. Privilege rules are enforced by the API: administrators cannot modify Super Administrators or themselves, and the last active administrator cannot be deactivated."
        actions={
          canWrite ? (
            <Button onClick={() => setShowCreate((v) => !v)}>
              <Plus size={16} /> New user
            </Button>
          ) : null
        }
      />

      {banner ? (
        <div
          className={
            banner.tone === "ok"
              ? "mb-4 rounded-md border border-success/30 bg-success-light px-3 py-2 text-sm text-success-dark"
              : "mb-4 rounded-md border border-danger/30 bg-danger-light px-3 py-2 text-sm text-danger-dark"
          }
        >
          {banner.text}
        </div>
      ) : null}

      {resetResult ? (
        <div className="mb-4 rounded-md border border-signal-200 bg-signal-50 px-4 py-3">
          <p className="text-sm font-semibold text-signal-700">
            One-time reset token issued for user #{resetResult.user_id}
          </p>
          <p className="mt-1 text-xs text-signal-700">
            Expires {formatDateTime(resetResult.expires_at)}. Share it over a secure channel; the
            user redeems it with POST /auth/password-reset/confirm.
          </p>
          <code className="mt-2 block break-all rounded bg-surface px-2 py-1 text-xs text-ink">
            {resetResult.reset_token}
          </code>
          <Button
            variant="secondary"
            size="sm"
            className="mt-2"
            onClick={() => setResetResult(null)}
          >
            Dismiss
          </Button>
        </div>
      ) : null}

      {showCreate && canWrite ? (
        <CreateUserForm
          roles={grantableRoles.map((r) => r.name)}
          onDone={(message) => {
            setShowCreate(false);
            report("ok", message);
          }}
          onError={(message) => report("error", message)}
        />
      ) : null}

      {editing ? (
        <EditUserForm
          user={editing}
          roles={grantableRoles.map((r) => r.name)}
          onClose={() => setEditing(null)}
          onDone={(message) => {
            setEditing(null);
            report("ok", message);
          }}
          onError={(message) => report("error", message)}
        />
      ) : null}

      <Card>
        <CardHeader
          title="Accounts"
          description={`${users.data?.total ?? 0} account(s)`}
          actions={
            <TextInput
              className="w-56"
              placeholder="Search name or email"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setPage(1);
              }}
            />
          }
        />

        {users.isLoading ? (
          <LoadingRows />
        ) : users.isError ? (
          <ErrorState error={users.error} onRetry={() => users.refetch()} />
        ) : users.data && users.data.items.length > 0 ? (
          <>
            <Table>
              <thead>
                <tr>
                  <Th>User</Th>
                  <Th>Roles</Th>
                  <Th>Status</Th>
                  <Th>Last sign-in</Th>
                  <Th align="right">Actions</Th>
                </tr>
              </thead>
              <tbody>
                {users.data.items.map((u) => (
                  <Tr key={u.id}>
                    <Td>
                      <p className="font-medium text-ink">{u.full_name}</p>
                      <p className="text-xs text-muted">{u.email}</p>
                      {u.department ? (
                        <p className="text-xs text-muted">{u.department}</p>
                      ) : null}
                    </Td>
                    <Td>
                      <div className="flex flex-wrap gap-1">
                        {u.roles.length > 0 ? (
                          u.roles.map((r) => (
                            <Badge
                              key={r}
                              className={
                                r === "super_admin"
                                  ? "bg-water-100 text-water-800"
                                  : r === "admin"
                                    ? "bg-water-50 text-water-700"
                                    : "bg-canvas text-muted"
                              }
                            >
                              {titleCase(r)}
                            </Badge>
                          ))
                        ) : (
                          <span className="text-xs text-muted">No role</span>
                        )}
                      </div>
                    </Td>
                    <Td>
                      <Badge className={u.is_active ? "bg-success-light text-success-dark" : "bg-canvas text-muted"}>
                        {u.is_active ? "Active" : "Inactive"}
                      </Badge>
                    </Td>
                    <Td>{formatDateTime(u.last_login_at)}</Td>
                    <Td align="right">
                      {canWrite ? (
                        <div className="flex flex-wrap justify-end gap-1">
                          <Button variant="secondary" size="sm" onClick={() => setEditing(u)}>
                            Edit
                          </Button>
                          <Button
                            variant="secondary"
                            size="sm"
                            loading={setActive.isPending}
                            onClick={async () => {
                              setBanner(null);
                              try {
                                await setActive.mutateAsync({ id: u.id, active: !u.is_active });
                                report("ok", `${u.email} ${u.is_active ? "deactivated" : "activated"}.`);
                              } catch (error) {
                                report(
                                  "error",
                                  error instanceof ApiError ? error.message : "Action failed.",
                                );
                              }
                            }}
                          >
                            {u.is_active ? "Deactivate" : "Activate"}
                          </Button>
                          <Button
                            variant="secondary"
                            size="sm"
                            title="Issue a one-time password reset token"
                            loading={issueReset.isPending}
                            onClick={async () => {
                              setBanner(null);
                              try {
                                const result = await issueReset.mutateAsync(u.id);
                                setResetResult(result);
                              } catch (error) {
                                report(
                                  "error",
                                  error instanceof ApiError ? error.message : "Action failed.",
                                );
                              }
                            }}
                          >
                            <KeyRound size={14} />
                          </Button>
                        </div>
                      ) : (
                        <span className="text-xs text-muted">Read only</span>
                      )}
                    </Td>
                  </Tr>
                ))}
              </tbody>
            </Table>
            <Pagination
              page={users.data.page}
              pages={users.data.pages}
              total={users.data.total}
              onChange={setPage}
            />
          </>
        ) : (
          <EmptyState
            title="No accounts match"
            description="Adjust the search, or create the first account."
          />
        )}
      </Card>
    </div>
  );
}

function CreateUserForm({
  roles,
  onDone,
  onError,
}: {
  roles: string[];
  onDone: (message: string) => void;
  onError: (message: string) => void;
}) {
  const create = useCreateUser();
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [selected, setSelected] = useState<string[]>(roles.includes("researcher") ? ["researcher"] : []);

  const toggle = (role: string) =>
    setSelected((prev) => (prev.includes(role) ? prev.filter((r) => r !== role) : [...prev, role]));

  return (
    <Card className="mb-5">
      <CardHeader title="New user" description="A password of at least 10 characters is required." />
      <form
        className="grid gap-4 px-5 py-4 sm:grid-cols-2"
        onSubmit={async (event) => {
          event.preventDefault();
          try {
            const created = await create.mutateAsync({
              email: email.trim(),
              full_name: fullName.trim(),
              password,
              roles: selected,
            });
            onDone(`Created ${created.email}.`);
          } catch (error) {
            onError(error instanceof ApiError ? error.message : "Could not create the user.");
          }
        }}
      >
        <Field label="Full name" htmlFor="new-name" required>
          <TextInput
            id="new-name"
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            required
          />
        </Field>
        <Field label="Email" htmlFor="new-email" required>
          <TextInput
            id="new-email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </Field>
        <Field label="Initial password" htmlFor="new-password" hint="Minimum 10 characters." required>
          <TextInput
            id="new-password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            minLength={10}
            required
          />
        </Field>
        <Field label="Roles" hint="Only roles you are permitted to grant are listed.">
          <div className="flex flex-wrap gap-4 pt-1.5">
            {roles.map((role) => (
              <Checkbox
                key={role}
                label={titleCase(role)}
                checked={selected.includes(role)}
                onChange={() => toggle(role)}
              />
            ))}
          </div>
        </Field>
        <div className="flex items-end gap-2 sm:col-span-2">
          <Button type="submit" loading={create.isPending}>
            Create user
          </Button>
        </div>
      </form>
    </Card>
  );
}

function EditUserForm({
  user,
  roles,
  onClose,
  onDone,
  onError,
}: {
  user: User;
  roles: string[];
  onClose: () => void;
  onDone: (message: string) => void;
  onError: (message: string) => void;
}) {
  const setRoles = useSetUserRoles();
  const [selected, setSelected] = useState<string[]>(user.roles);
  const [note, setNote] = useState("");

  const toggle = (role: string) =>
    setSelected((prev) => (prev.includes(role) ? prev.filter((r) => r !== role) : [...prev, role]));

  const options = Array.from(new Set([...roles, ...user.roles]));

  return (
    <Card className="mb-5">
      <CardHeader
        title={`Edit roles — ${user.full_name}`}
        description="Role changes are recorded in the audit log."
        actions={
          <Button variant="secondary" size="sm" onClick={onClose}>
            Cancel
          </Button>
        }
      />
      <div className="px-5 py-4">
        <div className="flex flex-wrap gap-4">
          {options.map((role) => (
            <Checkbox
              key={role}
              label={titleCase(role)}
              checked={selected.includes(role)}
              disabled={!roles.includes(role) && !user.roles.includes(role)}
              onChange={() => toggle(role)}
            />
          ))}
        </div>
        <Field label="Change note" htmlFor="role-note" className="mt-4 max-w-md">
          <TextInput
            id="role-note"
            value={note}
            placeholder="Why are these roles changing?"
            onChange={(e) => setNote(e.target.value)}
          />
        </Field>
        <Button
          className="mt-4"
          loading={setRoles.isPending}
          onClick={async () => {
            try {
              await setRoles.mutateAsync({ id: user.id, roles: selected });
              onDone(`Updated roles for ${user.email}.`);
            } catch (error) {
              onError(error instanceof ApiError ? error.message : "Could not update roles.");
            }
          }}
          disabled={selected.length === 0}
        >
          Save roles
        </Button>
        {selected.length === 0 ? (
          <p className="field-hint">Every account must hold at least one role.</p>
        ) : null}
      </div>
    </Card>
  );
}

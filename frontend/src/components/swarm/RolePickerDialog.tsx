import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, X } from "lucide-react";
import type { RoleGroup } from "@/lib/api";

interface RolePickerDialogProps {
  open: boolean;
  loading?: boolean;
  /** Full grouped catalog; only approved roles are selectable. */
  groups: RoleGroup[];
  onPick: (roleRef: string) => void;
  onClose: () => void;
}

/**
 * Canvas "add role" picker. Built-in roles are always selectable; custom
 * roles appear only after operator approval. Picking a role only seeds a
 * canvas node copy — it never modifies the role definition.
 */
export function RolePickerDialog({
  open,
  loading = false,
  groups,
  onPick,
  onClose,
}: RolePickerDialogProps) {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");

  const selectableGroups = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return groups
      .map((group) => ({
        ...group,
        roles: group.roles.filter(
          (role) =>
            role.approved &&
            (!needle ||
              role.name.toLowerCase().includes(needle) ||
              role.purpose.toLowerCase().includes(needle)),
        ),
      }))
      .filter((group) => group.roles.length > 0);
  }, [groups, query]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      data-testid="role-picker-dialog"
      role="presentation"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        className="flex max-h-[80vh] w-full max-w-2xl flex-col rounded-lg border border-border bg-card p-5 shadow-xl"
      >
        <div className="flex items-start justify-between">
          <h3 className="text-sm font-semibold text-foreground">
            {t("roleSquare.picker.title")}
          </h3>
          <button
            type="button"
            onClick={onClose}
            aria-label={t("roleSquare.picker.close")}
            className="rounded p-1 hover:bg-accent"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <p className="mt-1 text-xs text-muted-foreground">
          {t("roleSquare.picker.hint")}
        </p>

        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          data-testid="role-picker-search"
          placeholder={t("roleSquare.picker.searchPlaceholder")}
          className="mt-3 w-full rounded border border-border bg-background px-2 py-1.5 text-sm"
        />

        <div className="mt-3 flex-1 space-y-4 overflow-y-auto pr-1">
          {loading ? (
            <p className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              {t("roleSquare.picker.loading")}
            </p>
          ) : (
            selectableGroups.map((group) => (
              <section key={group.ref}>
                <h4 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                  {group.kind === "custom"
                    ? t("roleSquare.groups.custom")
                    : group.title || group.ref}
                </h4>
                <ul className="mt-1.5 space-y-1">
                  {group.roles.map((role) => (
                    <li key={role.ref}>
                      <button
                        type="button"
                        onClick={() => onPick(role.ref)}
                        data-testid={`role-pick-${role.ref}`}
                        className="flex w-full items-start justify-between gap-3 rounded border border-border bg-background px-3 py-2 text-left hover:bg-accent"
                      >
                        <span className="min-w-0">
                          <span className="block text-sm font-medium text-foreground">
                            {role.name}
                          </span>
                          <span className="mt-0.5 line-clamp-2 block text-[11px] text-muted-foreground">
                            {role.purpose || "—"}
                          </span>
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            ))
          )}
          {!loading && selectableGroups.length === 0 && (
            <p className="text-xs text-muted-foreground">
              {t("roleSquare.picker.empty")}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

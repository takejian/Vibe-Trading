import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { X } from "lucide-react";

interface SaveTeamDialogProps {
  open: boolean;
  /** "create" saves as a new team; "update" overwrites the loaded team. */
  mode: "create" | "update";
  initialName?: string;
  initialDescription?: string;
  saving?: boolean;
  error?: string;
  onSave: (name: string, description: string) => void;
  onClose: () => void;
}

export const TEAM_NAME_MAX = 80;
export const TEAM_DESCRIPTION_MAX = 400;

export function SaveTeamDialog({
  open,
  mode,
  initialName = "",
  initialDescription = "",
  saving = false,
  error = "",
  onSave,
  onClose,
}: SaveTeamDialogProps) {
  const { t } = useTranslation();
  const [name, setName] = useState(initialName);
  const [description, setDescription] = useState(initialDescription);

  useEffect(() => {
    if (open) {
      setName(initialName);
      setDescription(initialDescription);
    }
  }, [open, initialName, initialDescription]);

  if (!open) return null;

  const nameValid = name.trim().length > 0 && name.length <= TEAM_NAME_MAX;
  const descriptionValid = description.length <= TEAM_DESCRIPTION_MAX;
  const canSubmit = nameValid && descriptionValid && !saving;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      data-testid="save-team-dialog"
      role="presentation"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        className="w-full max-w-md rounded-lg border border-border bg-card p-5 shadow-xl"
      >
        <div className="flex items-start justify-between">
          <h3 className="text-sm font-semibold text-foreground">
            {mode === "create"
              ? t("swarmStudio.teams.saveTitle")
              : t("swarmStudio.teams.updateTitle")}
          </h3>
          <button
            type="button"
            onClick={onClose}
            aria-label={t("swarmStudio.teams.close")}
            className="rounded p-1 hover:bg-accent"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <p className="mt-1 text-xs text-muted-foreground">
          {t("swarmStudio.teams.saveHint")}
        </p>

        <label className="mt-4 block">
          <span className="text-xs font-medium text-foreground">
            {t("swarmStudio.teams.name")}
          </span>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={TEAM_NAME_MAX}
            data-testid="team-name-input"
            autoFocus
            className="mt-1 w-full rounded border border-border bg-background px-2 py-1.5 text-sm"
          />
          {!name.trim() && (
            <span className="mt-1 block text-xs text-red-600">
              {t("swarmStudio.teams.nameRequired")}
            </span>
          )}
        </label>

        <label className="mt-3 block">
          <span className="text-xs font-medium text-foreground">
            {t("swarmStudio.teams.description")}
          </span>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={3}
            maxLength={TEAM_DESCRIPTION_MAX}
            data-testid="team-description-input"
            className="mt-1 w-full rounded border border-border bg-background px-2 py-1.5 text-sm"
          />
          {!descriptionValid && (
            <span className="mt-1 block text-xs text-red-600">
              {t("swarmStudio.teams.descriptionTooLong", { number: TEAM_DESCRIPTION_MAX })}
            </span>
          )}
        </label>

        {error && (
          <p className="mt-3 text-xs text-destructive" data-testid="team-save-error">
            {error}
          </p>
        )}

        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded border border-border px-3 py-1.5 text-xs hover:bg-accent"
          >
            {t("swarmStudio.teams.cancel")}
          </button>
          <button
            type="button"
            disabled={!canSubmit}
            onClick={() => onSave(name.trim(), description.trim())}
            data-testid="team-save-confirm"
            className="rounded bg-foreground px-3 py-1.5 text-xs text-background disabled:opacity-40"
          >
            {saving
              ? t("swarmStudio.teams.saving")
              : mode === "create"
                ? t("swarmStudio.teams.save")
                : t("swarmStudio.teams.update")}
          </button>
        </div>
      </div>
    </div>
  );
}

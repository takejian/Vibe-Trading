import { useTranslation } from "react-i18next";
import { Users } from "lucide-react";
import type { SwarmPreset } from "@/lib/api";

interface PresetGalleryProps {
  presets: SwarmPreset[];
  loading: boolean;
  error: string;
  onSelect: (name: string) => void;
}

export function PresetGallery({ presets, loading, error, onSelect }: PresetGalleryProps) {
  const { t } = useTranslation();

  if (loading) {
    return (
      <div className="mt-8 text-sm text-muted-foreground" data-testid="preset-gallery-loading">
        {t("swarmStudio.gallery.loading")}
      </div>
    );
  }
  if (error) {
    return (
      <p className="mt-8 text-sm text-destructive" data-testid="preset-gallery-error">
        {error}
      </p>
    );
  }

  return (
    <div
      className="mt-6 grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3"
      data-testid="preset-gallery"
    >
      {presets.map((preset) => (
        <button
          key={preset.name}
          type="button"
          onClick={() => onSelect(preset.name)}
          data-testid={`preset-card-${preset.name}`}
          className="flex flex-col rounded-lg border border-border bg-card p-4 text-left transition-colors hover:border-foreground/50 hover:bg-accent/40"
        >
          <span className="flex items-center gap-2">
            <Users className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
            <span className="text-sm font-semibold text-foreground">
              {preset.title || preset.name}
            </span>
          </span>
          <span className="mt-2 line-clamp-3 flex-1 text-xs text-muted-foreground">
            {preset.description || t("swarmStudio.gallery.noDescription")}
          </span>
          <span className="mt-3 inline-flex w-fit rounded-full bg-foreground/10 px-2 py-0.5 text-[11px] text-foreground">
            {t("swarmStudio.gallery.roleCount", { number: preset.agent_count })}
          </span>
        </button>
      ))}
      {presets.length === 0 && (
        <p className="text-sm text-muted-foreground">{t("swarmStudio.gallery.empty")}</p>
      )}
    </div>
  );
}

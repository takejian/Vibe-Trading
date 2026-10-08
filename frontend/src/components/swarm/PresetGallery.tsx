import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Bookmark, Users } from "lucide-react";
import type { CustomTeamSummary, SwarmPreset } from "@/lib/api";

interface PresetGalleryProps {
  presets: SwarmPreset[];
  loading: boolean;
  error: string;
  /** Personal saved teams; empty when the feature loads nothing. */
  teams: CustomTeamSummary[];
  teamsLoading?: boolean;
  teamsError?: string;
  onSelect: (name: string) => void;
  onSelectTeam: (teamId: string) => void;
}

// Mirrors PRESET_CATEGORY_ORDER in src/swarm/presets.py — keeps category
// sections laid out in financial-research taxonomy order.
const CATEGORY_ORDER = [
  "technical",
  "fundamental",
  "macro",
  "quant",
  "sentiment",
  "event_driven",
  "allocation",
  "fixed_income_derivatives",
  "alternatives",
  "risk",
  "other",
] as const;

const ALL_CATEGORIES = "all";

function categoryRank(id: string): number {
  const index = CATEGORY_ORDER.indexOf(id as (typeof CATEGORY_ORDER)[number]);
  return index === -1 ? CATEGORY_ORDER.length : index;
}

export function PresetGallery({
  presets,
  loading,
  error,
  teams,
  teamsLoading = false,
  teamsError = "",
  onSelect,
  onSelectTeam,
}: PresetGalleryProps) {
  const { t } = useTranslation();
  const [activeCategory, setActiveCategory] = useState<string>(ALL_CATEGORIES);

  // Group the bundled roster by category, in canonical category order.
  const groupedPresets = useMemo(() => {
    const groups = new Map<string, SwarmPreset[]>();
    for (const preset of presets) {
      const category = preset.category || "other";
      const list = groups.get(category);
      if (list) {
        list.push(preset);
      } else {
        groups.set(category, [preset]);
      }
    }
    return [...groups.entries()].sort(([a], [b]) => categoryRank(a) - categoryRank(b));
  }, [presets]);

  const visibleGroups = groupedPresets.filter(
    ([category]) => activeCategory === ALL_CATEGORIES || category === activeCategory,
  );

  const renderPresetCard = (preset: SwarmPreset) => (
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
  );

  const builtIns = (
    <div className="space-y-5">
      {groupedPresets.length > 1 && (
        <div
          className="flex flex-wrap gap-2"
          role="group"
          aria-label={t("swarmStudio.gallery.categoryFilterLabel")}
          data-testid="preset-category-filter"
        >
          <button
            key={ALL_CATEGORIES}
            type="button"
            onClick={() => setActiveCategory(ALL_CATEGORIES)}
            aria-pressed={activeCategory === ALL_CATEGORIES}
            data-testid="preset-filter-all"
            className={`rounded-full border px-3 py-1 text-xs transition-colors ${
              activeCategory === ALL_CATEGORIES
                ? "border-foreground bg-foreground text-background"
                : "border-border bg-card text-muted-foreground hover:border-foreground/50"
            }`}
          >
            {t("swarmStudio.gallery.allCategories")}
          </button>
          {groupedPresets.map(([category, list]) => (
            <button
              key={category}
              type="button"
              onClick={() => setActiveCategory(category)}
              aria-pressed={activeCategory === category}
              data-testid={`preset-filter-${category}`}
              className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                activeCategory === category
                  ? "border-foreground bg-foreground text-background"
                  : "border-border bg-card text-muted-foreground hover:border-foreground/50"
              }`}
            >
              {t(`swarmStudio.category.${category}`, { defaultValue: category })}
              <span className="ml-1 opacity-70">{list.length}</span>
            </button>
          ))}
        </div>
      )}

      {visibleGroups.map(([category, list]) => (
        <section key={category} data-testid={`preset-group-${category}`}>
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {t(`swarmStudio.category.${category}`, { defaultValue: category })}
          </h4>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {list.map(renderPresetCard)}
          </div>
        </section>
      ))}

      {presets.length === 0 && (
        <p className="text-sm text-muted-foreground">{t("swarmStudio.gallery.empty")}</p>
      )}
    </div>
  );

  const myTeams = (
    <div
      className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3"
      data-testid="custom-team-gallery"
    >
      {teams.map((team) => (
        <button
          key={team.id}
          type="button"
          onClick={() => onSelectTeam(team.id)}
          data-testid={`custom-team-card-${team.id}`}
          className="flex flex-col rounded-lg border border-dashed border-border bg-card p-4 text-left transition-colors hover:border-foreground/50 hover:bg-accent/40"
        >
          <span className="flex items-center gap-2">
            <Bookmark className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
            <span className="text-sm font-semibold text-foreground">{team.name}</span>
          </span>
          <span className="mt-2 line-clamp-3 flex-1 text-xs text-muted-foreground">
            {team.description || t("swarmStudio.gallery.myTeamsNoDescription")}
          </span>
          <span className="mt-3 inline-flex w-fit rounded-full bg-foreground/10 px-2 py-0.5 text-[11px] text-foreground">
            {t("swarmStudio.gallery.roleCount", { number: team.role_count })}
          </span>
        </button>
      ))}
      {teams.length === 0 && !teamsLoading && !teamsError && (
        <p className="text-sm text-muted-foreground" data-testid="custom-team-empty">
          {t("swarmStudio.gallery.myTeamsEmpty")}
        </p>
      )}
      {teamsLoading && (
        <p className="text-sm text-muted-foreground">{t("swarmStudio.gallery.loading")}</p>
      )}
      {teamsError && <p className="text-sm text-destructive">{teamsError}</p>}
    </div>
  );

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
    <div className="mt-6 space-y-8">
      <section>
        <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          {t("swarmStudio.gallery.myTeamsSection")}
        </h3>
        {myTeams}
      </section>
      <section>
        <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          {t("swarmStudio.gallery.builtinSection")}
        </h3>
        {builtIns}
      </section>
    </div>
  );
}

import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, Lock, Pencil } from "lucide-react";
import { api, type MacroPrompt } from "@/lib/api";
import { MacroHistoryTimeline } from "@/components/macro/MacroHistoryTimeline";
import { MacroTeamTab } from "@/components/macro/MacroTeamTab";
import { MacroRoleTab } from "@/components/macro/MacroRoleTab";
import { MacroBoardTab } from "@/components/macro/MacroBoardTab";
import { OrchestrationReserved } from "@/components/macro/OrchestrationReserved";
import { PromptEditDialog } from "@/components/macro/PromptEditDialog";

const PROMPT_DESC_KEYS: Record<string, string> = {
  a: "macro.prompts.aDesc",
  b: "macro.prompts.bDesc",
  c: "macro.prompts.cDesc",
};
const PROMPT_NAME_KEYS: Record<string, string> = {
  a: "macro.prompts.aName",
  b: "macro.prompts.bName",
  c: "macro.prompts.cName",
};

type MacroTabId = "cycle" | "team" | "role" | "board";

export function Macro() {
  const { t } = useTranslation();
  const [prompts, setPrompts] = useState<MacroPrompt[]>([]);
  const [economies, setEconomies] = useState<string[]>([]);
  const [economy, setEconomy] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [editing, setEditing] = useState<MacroPrompt | null>(null);
  const [promptBodies, setPromptBodies] = useState<Record<string, string>>({});
  const [activeTab, setActiveTab] = useState<MacroTabId>("cycle");
  const [mountedTabs, setMountedTabs] = useState<MacroTabId[]>(["cycle"]);

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.listMacroPrompts(), api.listMacroEconomies()])
      .then(([promptRes, economyRes]) => {
        if (cancelled) return;
        setPrompts(promptRes.prompts);
        setEconomies(economyRes.economies);
        setEconomy(economyRes.economies[0] || "");
        setPromptBodies(
          Object.fromEntries(promptRes.prompts.map((p) => [p.code, p.prompt_text])),
        );
      })
      .catch(() => {
        if (!cancelled) setLoadError(t("macro.panel.dbUnavailable"));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [t]);

  const promptA = useMemo(() => prompts.find((p) => p.code === "a") || null, [prompts]);

  const activateTab = (tab: MacroTabId) => {
    setMountedTabs((prev) => (prev.includes(tab) ? prev : [...prev, tab]));
    setActiveTab(tab);
  };

  const tabButton = (id: MacroTabId, labelKey: string, testId: string) => (
    <button
      key={id}
      type="button"
      role="tab"
      aria-selected={activeTab === id}
      data-testid={testId}
      onClick={() => activateTab(id)}
      className={
        activeTab === id
          ? "inline-flex items-center rounded-lg bg-foreground px-4 py-1.5 text-sm font-medium text-background"
          : "inline-flex items-center rounded-lg border border-border/60 px-4 py-1.5 text-sm font-medium text-foreground transition-colors hover:bg-muted"
      }
    >
      {t(labelKey as never)}
    </button>
  );

  return (
    <div className="mx-auto w-full max-w-6xl px-4 py-8" data-testid="macro-page">
      <h1 className="font-serif text-2xl text-foreground">{t("macro.title")}</h1>
      <p className="mt-1 text-sm text-muted-foreground">{t("macro.subtitle")}</p>

      <nav className="mt-5 flex flex-wrap gap-2" role="tablist" aria-label={t("macro.tabs.ariaLabel")}>
        {tabButton("cycle", "macro.tabs.cycle", "macro-tab-cycle")}
        {tabButton("team", "macro.tabs.team", "macro-tab-team")}
        {tabButton("role", "macro.tabs.role", "macro-tab-role")}
        {tabButton("board", "macro.tabs.board", "macro-tab-board")}
      </nav>

      <div
        hidden={activeTab !== "cycle"}
        role="tabpanel"
        data-testid="macro-panel-cycle"
      >
        {loading && (
          <div className="mt-8 flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          </div>
        )}
        {loadError && <p className="mt-6 text-sm text-destructive">{loadError}</p>}

        {!loading && !loadError && (
          <>
            <section className="mt-6">
              <h2 className="text-sm font-semibold text-foreground">
                {t("macro.prompts.sectionTitle")}
              </h2>
              <div className="mt-3 grid gap-3">
                {prompts.map((prompt) => {
                  const isA = prompt.code === "a";
                  return (
                    <div
                      key={prompt.code}
                      data-testid={`macro-prompt-card-${prompt.code}`}
                      className={
                        isA
                          ? "rounded-xl border border-border/60 bg-card p-4"
                          : "rounded-xl border border-dashed border-border/60 bg-card/60 p-4 opacity-80"
                      }
                    >
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium text-foreground">
                            {t((PROMPT_NAME_KEYS[prompt.code] || "macro.prompts.reserved") as never)}
                          </span>
                          {!prompt.enabled && (
                            <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] text-muted-foreground">
                              {t("macro.prompts.reserved")}
                            </span>
                          )}
                        </div>
                        {isA && (
                          <button
                            type="button"
                            data-testid="macro-edit-prompt-a"
                            disabled={!prompt.can_edit}
                            title={prompt.can_edit ? t("macro.prompts.edit") : t("macro.prompts.editDenied")}
                            onClick={() => setEditing(prompt)}
                            className="inline-flex items-center gap-1.5 rounded-lg border border-border/60 px-2.5 py-1 text-xs font-medium text-foreground transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
                          >
                            {prompt.can_edit ? (
                              <Pencil className="h-3 w-3" aria-hidden="true" />
                            ) : (
                              <Lock className="h-3 w-3" aria-hidden="true" />
                            )}
                            {t("macro.prompts.edit")}
                          </button>
                        )}
                      </div>
                      <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                        {t((PROMPT_DESC_KEYS[prompt.code] || "macro.prompts.reserved") as never)}
                      </p>
                    </div>
                  );
                })}
              </div>
            </section>

            <section className="mt-8">
              <OrchestrationReserved />
            </section>

            {promptA && (
              <section className="mt-8 rounded-xl border border-border/60 bg-card p-4">
                <div className="flex flex-wrap items-end justify-between gap-3">
                  <h2 className="text-sm font-semibold text-foreground">
                    {t("macro.prompts.aName")} · {t("macro.history.title")}
                  </h2>
                  <label className="flex flex-col gap-1 text-xs text-muted-foreground">
                    {t("macro.panel.economy")}
                    <select
                      data-testid="macro-history-economy"
                      value={economy}
                      onChange={(event) => setEconomy(event.target.value)}
                      className="min-w-40 rounded-lg border border-border/60 bg-background px-3 py-1.5 text-sm text-foreground outline-none focus:ring-2 focus:ring-primary/40"
                    >
                      {economies.map((name) => (
                        <option key={name} value={name}>{name}</option>
                      ))}
                    </select>
                  </label>
                </div>
                <div className="mt-4">
                  {economy && <MacroHistoryTimeline economy={economy} />}
                </div>
              </section>
            )}
          </>
        )}
      </div>

      {mountedTabs.includes("team") && (
        <div
          hidden={activeTab !== "team"}
          role="tabpanel"
          data-testid="macro-panel-team"
          className="mt-6"
        >
          <MacroTeamTab />
        </div>
      )}

      {mountedTabs.includes("role") && (
        <div
          hidden={activeTab !== "role"}
          role="tabpanel"
          data-testid="macro-panel-role"
          className="mt-6"
        >
          <MacroRoleTab />
        </div>
      )}

      {mountedTabs.includes("board") && (
        <div
          hidden={activeTab !== "board"}
          role="tabpanel"
          data-testid="macro-panel-board"
          className="mt-6"
        >
          <MacroBoardTab />
        </div>
      )}

      {editing && (
        <PromptEditDialog
          open
          code={editing.code}
          initialText={promptBodies[editing.code] ?? editing.prompt_text}
          onClose={() => setEditing(null)}
          onSaved={(text) =>
            setPromptBodies((prev) => ({ ...prev, [editing.code]: text }))
          }
        />
      )}
    </div>
  );
}

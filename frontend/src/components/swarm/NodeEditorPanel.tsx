import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Trash2 } from "lucide-react";
import {
  MAX_TIMEOUT_SECONDS,
  MIN_TIMEOUT_SECONDS,
  type FlowEdge,
  type FlowNodeDraft,
} from "@/lib/swarmGraph";

interface NodeEditorPanelProps {
  node: FlowNodeDraft | null;
  nodes: FlowNodeDraft[];
  edges: FlowEdge[];
  toolCatalog: string[];
  onUpdateNode: (id: string, patch: Partial<FlowNodeDraft>) => void;
  onDeleteNode: (id: string) => void;
  onDeleteEdge: (edge: FlowEdge) => void;
  onAddEdge: (edge: FlowEdge) => void;
}

export function NodeEditorPanel({
  node,
  nodes,
  edges,
  toolCatalog,
  onUpdateNode,
  onDeleteNode,
  onDeleteEdge,
  onAddEdge,
}: NodeEditorPanelProps) {
  const { t } = useTranslation();
  const [upstream, setUpstream] = useState("");
  const [downstream, setDownstream] = useState("");

  const incident = useMemo(() => {
    if (!node) return { incoming: [] as FlowEdge[], outgoing: [] as FlowEdge[] };
    return {
      incoming: edges.filter((e) => e.downstream === node.id),
      outgoing: edges.filter((e) => e.upstream === node.id),
    };
  }, [edges, node]);

  if (!node) {
    return (
      <aside className="w-full rounded-lg border border-border bg-card p-4 text-sm text-muted-foreground lg:w-80">
        {t("swarmStudio.editor.empty")}
      </aside>
    );
  }

  const dutyInvalid = !node.duty.trim();
  const timeoutInvalid =
    !Number.isInteger(node.timeoutSeconds) ||
    node.timeoutSeconds < MIN_TIMEOUT_SECONDS ||
    node.timeoutSeconds > MAX_TIMEOUT_SECONDS;

  const toggleTool = (tool: string, checked: boolean) => {
    const next = checked
      ? [...new Set([...node.tools, tool])]
      : node.tools.filter((t) => t !== tool);
    onUpdateNode(node.id, { tools: next });
  };

  const edgeKey = (e: FlowEdge) => `${e.upstream}->${e.downstream}`;

  return (
    <aside
      className="w-full rounded-lg border border-border bg-card p-4 lg:w-80"
      data-testid="node-editor-panel"
    >
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-foreground">
          {t("swarmStudio.editor.title")}
        </h3>
        <button
          type="button"
          onClick={() => onDeleteNode(node.id)}
          data-testid="delete-node-btn"
          className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs text-red-600 hover:bg-red-50 dark:hover:bg-red-950/40"
        >
          <Trash2 className="h-3.5 w-3.5" />
          {t("swarmStudio.editor.deleteNode")}
        </button>
      </div>

      <div className="mt-3 space-y-3">
        <label className="block">
          <span className="text-xs font-medium text-foreground">
            {t("swarmStudio.editor.role")}
          </span>
          <input
            value={node.role}
            onChange={(e) => onUpdateNode(node.id, { role: e.target.value })}
            data-testid="node-role-input"
            className="mt-1 w-full rounded border border-border bg-background px-2 py-1.5 text-sm"
          />
          {!node.role.trim() && (
            <span className="mt-1 block text-xs text-red-600">
              {t("swarmStudio.validation.emptyRole")}
            </span>
          )}
        </label>

        <label className="block">
          <span className="text-xs font-medium text-foreground">
            {t("swarmStudio.editor.duty")}
          </span>
          <textarea
            value={node.duty}
            onChange={(e) => onUpdateNode(node.id, { duty: e.target.value })}
            rows={6}
            data-testid="node-duty-input"
            className={`mt-1 w-full rounded border bg-background px-2 py-1.5 text-sm ${
              dutyInvalid ? "border-red-400" : "border-border"
            }`}
          />
          {dutyInvalid && (
            <span className="mt-1 block text-xs text-red-600">
              {t("swarmStudio.validation.emptyDuty")}
            </span>
          )}
        </label>

        <fieldset>
          <legend className="text-xs font-medium text-foreground">
            {t("swarmStudio.editor.tools")}
          </legend>
          <div
            className="mt-1 grid max-h-44 grid-cols-1 gap-1 overflow-y-auto rounded border border-border bg-background p-2"
            data-testid="node-tools-list"
          >
            {toolCatalog.map((tool) => (
              <label key={tool} className="flex items-center gap-2 text-xs text-foreground">
                <input
                  type="checkbox"
                  checked={node.tools.includes(tool)}
                  onChange={(e) => toggleTool(tool, e.target.checked)}
                />
                <code className="truncate">{tool}</code>
              </label>
            ))}
          </div>
        </fieldset>

        <label className="block">
          <span className="text-xs font-medium text-foreground">
            {t("swarmStudio.editor.timeout")}
          </span>
          <div className="mt-1 flex items-center gap-2">
            <input
              type="number"
              min={MIN_TIMEOUT_SECONDS}
              max={MAX_TIMEOUT_SECONDS}
              value={Number.isNaN(node.timeoutSeconds) ? "" : node.timeoutSeconds}
              onChange={(e) =>
                onUpdateNode(node.id, {
                  timeoutSeconds: e.target.value === "" ? Number.NaN : Number(e.target.value),
                })
              }
              data-testid="node-timeout-input"
              className={`w-28 rounded border bg-background px-2 py-1.5 text-sm ${
                timeoutInvalid ? "border-red-400" : "border-border"
              }`}
            />
            <span className="text-xs text-muted-foreground">
              {t("swarmStudio.editor.seconds")}
            </span>
          </div>
          {timeoutInvalid && (
            <span className="mt-1 block text-xs text-red-600">
              {t("swarmStudio.validation.invalidTimeout", {
                min: MIN_TIMEOUT_SECONDS,
                max: MAX_TIMEOUT_SECONDS,
              })}
            </span>
          )}
        </label>

        <div>
          <h4 className="text-xs font-medium text-foreground">
            {t("swarmStudio.editor.edges")}
          </h4>
          <ul className="mt-1 space-y-1 text-xs" data-testid="node-edge-list">
            {[...incident.incoming, ...incident.outgoing].map((edge) => (
              <li
                key={edgeKey(edge)}
                className="flex items-center justify-between rounded bg-background px-2 py-1"
              >
                <span>
                  {edge.downstream === node.id ? "↑ " : "↓ "}
                  {edge.upstream} → {edge.downstream}
                </span>
                <button
                  type="button"
                  onClick={() => onDeleteEdge(edge)}
                  className="text-red-600 hover:underline"
                >
                  {t("swarmStudio.editor.removeEdge")}
                </button>
              </li>
            ))}
            {incident.incoming.length + incident.outgoing.length === 0 && (
              <li className="text-muted-foreground">
                {t("swarmStudio.editor.noEdges")}
              </li>
            )}
          </ul>

          <div className="mt-2 flex flex-wrap items-center gap-1">
            <select
              value={upstream}
              onChange={(e) => setUpstream(e.target.value)}
              data-testid="edge-upstream-select"
              className="max-w-[9rem] truncate rounded border border-border bg-background px-1 py-1 text-xs"
              aria-label={t("swarmStudio.editor.upstream")}
            >
              <option value="">{t("swarmStudio.editor.upstream")}</option>
              {nodes
                .filter((n) => n.id !== node.id || downstream !== node.id)
                .map((n) => (
                  <option key={n.id} value={n.id}>
                    {n.role}
                  </option>
                ))}
            </select>
            <span>→</span>
            <select
              value={downstream}
              onChange={(e) => setDownstream(e.target.value)}
              data-testid="edge-downstream-select"
              aria-label={t("swarmStudio.editor.downstream")}
              className="max-w-[9rem] truncate rounded border border-border bg-background px-1 py-1 text-xs"
            >
              <option value="">{t("swarmStudio.editor.downstream")}</option>
              {nodes.map((n) => (
                <option key={n.id} value={n.id}>
                  {n.role}
                </option>
              ))}
            </select>
            <button
              type="button"
              disabled={
                !upstream ||
                !downstream ||
                upstream === downstream ||
                edges.some(
                  (e) => e.upstream === upstream && e.downstream === downstream,
                )
              }
              onClick={() => {
                onAddEdge({ upstream, downstream });
                setUpstream("");
                setDownstream("");
              }}
              data-testid="add-edge-btn"
              className="rounded bg-foreground px-2 py-1 text-xs text-background disabled:opacity-40"
            >
              {t("swarmStudio.editor.addEdge")}
            </button>
          </div>
        </div>
      </div>
    </aside>
  );
}

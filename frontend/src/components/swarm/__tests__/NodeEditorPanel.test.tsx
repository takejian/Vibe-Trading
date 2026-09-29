import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { NodeEditorPanel } from "../NodeEditorPanel";
import type { FlowNodeDraft } from "@/lib/swarmGraph";
import type { SkillCatalogEntry } from "@/lib/api";

function makeNode(overrides: Partial<FlowNodeDraft> = {}): FlowNodeDraft {
  return {
    id: "analyst",
    role: "Analyst",
    duty: "research the target",
    tools: ["get_market_data"],
    skills: ["strategy-generate"],
    timeoutSeconds: 300,
    isNew: false,
    ...overrides,
  };
}

const PRESET_SKILLS = ["strategy-generate", "asset-allocation"];

const APPROVED: SkillCatalogEntry[] = [
  {
    name: "behavioral-finance",
    description: "Behavioral finance analysis",
    category: "analysis",
    source: "bundled",
    approved: true,
  },
  {
    // Preset skills must never appear in the "add" popover.
    name: "asset-allocation",
    description: "Allocation helper",
    category: "analysis",
    source: "bundled",
    approved: true,
  },
];

function renderPanel(node: FlowNodeDraft = makeNode()) {
  const onUpdateNode = vi.fn();
  render(
    <NodeEditorPanel
      node={node}
      nodes={[node]}
      edges={[]}
      toolCatalog={["get_market_data", "backtest"]}
      skillCatalog={PRESET_SKILLS}
      approvedSkills={APPROVED}
      onUpdateNode={onUpdateNode}
      onDeleteNode={vi.fn()}
      onDeleteEdge={vi.fn()}
      onAddEdge={vi.fn()}
    />,
  );
  return { onUpdateNode };
}

describe("NodeEditorPanel skill selection", () => {
  it("lists preset skills as checkboxes reflecting the node state", () => {
    renderPanel();

    const selected = screen.getByTestId("skill-checkbox-strategy-generate");
    const unselected = screen.getByTestId("skill-checkbox-asset-allocation");
    expect((selected as HTMLInputElement).checked).toBe(true);
    expect((unselected as HTMLInputElement).checked).toBe(false);
  });

  it("toggles a preset skill onto the node", async () => {
    const { onUpdateNode } = renderPanel();

    await userEvent.click(screen.getByTestId("skill-checkbox-asset-allocation"));
    expect(onUpdateNode).toHaveBeenCalledWith("analyst", {
      skills: ["strategy-generate", "asset-allocation"],
    });
  });

  it("marks non-preset skills carried by the node with the approved badge", () => {
    renderPanel(makeNode({ skills: ["legacy-skill"] }));
    expect(screen.getByTestId("skill-checkbox-legacy-skill")).toBeInTheDocument();
    expect(screen.getByText("approved")).toBeInTheDocument();
  });

  it("opens the add-skill picker, filters by search, and adds an approved skill", async () => {
    const { onUpdateNode } = renderPanel(makeNode({ skills: [] }));

    expect(screen.queryByTestId("skill-picker")).not.toBeInTheDocument();
    await userEvent.click(screen.getByTestId("add-skill-btn"));
    expect(screen.getByTestId("skill-picker")).toBeInTheDocument();

    // Only approved skills outside the preset union are offered.
    expect(screen.getByTestId("skill-picker-item-behavioral-finance")).toBeInTheDocument();
    expect(screen.queryByTestId("skill-picker-item-asset-allocation")).not.toBeInTheDocument();

    await userEvent.type(screen.getByTestId("skill-picker-search"), "zzz-no-match");
    expect(screen.queryByTestId("skill-picker-item-behavioral-finance")).not.toBeInTheDocument();

    await userEvent.clear(screen.getByTestId("skill-picker-search"));
    await userEvent.click(screen.getByTestId("skill-picker-item-behavioral-finance"));
    expect(onUpdateNode).toHaveBeenCalledWith("analyst", {
      skills: ["behavioral-finance"],
    });
  });
});

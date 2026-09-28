import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { FlowCanvas, type CanvasNode } from "../FlowCanvas";
import type { FlowEdge, GraphIssue } from "@/lib/swarmGraph";

function makeGraph() {
  const nodes: CanvasNode[] = [
    { id: "bull", role: "Bull" },
    { id: "bear", role: "Bear" },
    { id: "risk", role: "CRO" },
    { id: "pm", role: "PM", isFinal: true },
  ];
  const edges: FlowEdge[] = [
    { upstream: "bull", downstream: "risk" },
    { upstream: "bear", downstream: "risk" },
    { upstream: "risk", downstream: "pm" },
  ];
  return { nodes, edges };
}

describe("FlowCanvas", () => {
  it("renders every node, layer labels and the final-decision badge", () => {
    const { nodes, edges } = makeGraph();
    render(<FlowCanvas nodes={nodes} edges={edges} onSelectNode={vi.fn()} />);

    expect(screen.getByTestId("canvas-node-bull")).toBeInTheDocument();
    expect(screen.getByTestId("canvas-node-bear")).toBeInTheDocument();
    expect(screen.getByTestId("canvas-node-risk")).toBeInTheDocument();
    expect(screen.getByTestId("canvas-node-pm")).toBeInTheDocument();
    expect(screen.getAllByText(/Layer/)).toHaveLength(3);
    expect(screen.getByText("Final decision")).toBeInTheDocument();
  });

  it("highlights nodes and edges flagged by validation", () => {
    const { nodes, edges } = makeGraph();
    edges.push({ upstream: "risk", downstream: "bull" });
    const issues: GraphIssue[] = [
      { code: "cycle", nodeIds: ["bull", "risk"], edge: edges[edges.length - 1] },
    ];

    render(
      <FlowCanvas
        nodes={nodes}
        edges={edges}
        issues={issues}
        onSelectNode={vi.fn()}
      />,
    );

    const bull = screen.getByTestId("canvas-node-bull");
    const risk = screen.getByTestId("canvas-node-risk");
    expect(bull.className).toContain("ring-red-400");
    expect(risk.className).toContain("ring-red-400");
    expect(screen.getByTestId("edge-risk-bull")).toHaveAttribute(
      "stroke",
      "#ef4444",
    );
  });

  it("reflects runtime node statuses", () => {
    const { nodes, edges } = makeGraph();
    render(
      <FlowCanvas
        nodes={nodes}
        edges={edges}
        statusById={{ bull: "completed", risk: "running", pm: "blocked" }}
        onSelectNode={vi.fn()}
      />,
    );

    expect(screen.getByTestId("canvas-node-bull").className).toContain(
      "border-emerald-500",
    );
    expect(screen.getByTestId("canvas-node-risk").className).toContain(
      "border-blue-500",
    );
    expect(screen.getByTestId("canvas-node-pm").className).toContain(
      "border-amber-400",
    );
  });
});

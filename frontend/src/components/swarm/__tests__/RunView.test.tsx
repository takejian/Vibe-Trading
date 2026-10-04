import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { RunView } from "../RunView";

const getSwarmRun = vi.fn();

vi.mock("@/lib/api", () => ({
  api: {
    getSwarmRun: (...args: unknown[]) => getSwarmRun(...args),
  },
}));

// Replace the heavy SVG canvas with simple node buttons so selecting a node
// is a plain click; the MarkdownContent pipeline itself is NOT mocked.
vi.mock("../FlowCanvas", () => ({
  FlowCanvas: ({
    nodes,
    onSelectNode,
  }: {
    nodes: { id: string; role: string }[];
    onSelectNode?: (id: string) => void;
  }) => (
    <div data-testid="flow-canvas-mock">
      {nodes.map((node) => (
        <button
          key={node.id}
          type="button"
          data-testid={`canvas-node-${node.id}`}
          onClick={() => onSelectNode?.(node.id)}
        >
          {node.role}
        </button>
      ))}
    </div>
  ),
}));

const NODE_SUMMARY_MD = [
  "## 风险核验结论",
  "",
  "| 证据 | 状态 | 涨幅 |",
  "| :--- | :---: | ---: |",
  "| 创业板指 | 已验证 | 12% |",
  "",
  "- 论据**可靠**",
].join("\n");

const FINAL_REPORT_MD = [
  "# 最终决策",
  "",
  "| 方向 | 仓位 | 目标价 |",
  "| --- | ---: | ---: |",
  "| 做多 | 30% | 1850 |",
].join("\n");

function buildRun() {
  return {
    id: "swarm-777",
    preset_name: "investment_committee",
    status: "completed",
    user_vars: { target: "600519.SH" },
    research_target: "600519.SH",
    research_question: "做多还是做空？",
    created_at: "2026-09-30T10:00:00+00:00",
    completed_at: "2026-09-30T10:05:00+00:00",
    customized: false,
    final_report: FINAL_REPORT_MD,
    agents: [
      {
        id: "risk_officer",
        role: "首席风险官",
        tools: ["get_market_data"],
        timeout_seconds: 600,
      },
      {
        id: "portfolio_manager",
        role: "投资经理",
        tools: ["backtest"],
        timeout_seconds: 1800,
      },
    ],
    tasks: [
      {
        id: "task-risk",
        agent_id: "risk_officer",
        status: "completed",
        summary: NODE_SUMMARY_MD,
        error: null,
      },
      {
        id: "task-pm",
        agent_id: "portfolio_manager",
        status: "completed",
        summary: "综合各方结论，给出最终建议。",
        error: null,
      },
    ],
  };
}

describe("RunView layout and conclusion panel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getSwarmRun.mockResolvedValue(buildRun());
  });

  it("stacks canvas, conclusion panel and final decision in order, without a side aside", async () => {
    const { container } = render(<RunView runId="swarm-777" readOnly />);
    await screen.findByTestId("final-decision-panel");

    expect(container.querySelector("aside")).toBeNull();
    const panel = screen.getByTestId("node-detail-panel");
    const decision = screen.getByTestId("final-decision-panel");
    // The conclusion panel sits immediately above the final decision area.
    expect(panel.nextElementSibling).toBe(decision);
  });

  it("renders the final decision through the normalized Markdown pipeline", async () => {
    render(<RunView runId="swarm-777" readOnly />);
    const content = await screen.findByTestId("final-decision-content");
    expect(content.querySelector(".prose")).not.toBeNull();
    expect(content.querySelectorAll("thead th")).toHaveLength(3);
    expect(content.querySelector("table")?.parentElement).toHaveClass(
      "overflow-x-auto",
    );
  });

  it("shows the selected node's conclusion as a structured document", async () => {
    render(<RunView runId="swarm-777" readOnly />);
    await screen.findByTestId("final-decision-panel");

    await userEvent.click(screen.getByTestId("canvas-node-risk_officer"));

    const body = screen.getByTestId("node-panel-body");
    expect(
      screen.getByRole("heading", { name: /首席风险官/ }),
    ).toBeInTheDocument();
    expect(body.querySelector(".prose")).not.toBeNull();
    expect(body.querySelector("h2")?.textContent).toBe("风险核验结论");
    expect(body.querySelectorAll("thead th")).toHaveLength(3);
    expect(body.querySelector("strong")?.textContent).toBe("可靠");
  });

  it("collapses and expands manually, and auto-expands when a node is picked while collapsed", async () => {
    render(<RunView runId="swarm-777" readOnly />);
    await screen.findByTestId("final-decision-panel");
    await userEvent.click(screen.getByTestId("canvas-node-risk_officer"));
    expect(screen.getByTestId("node-panel-body")).toBeInTheDocument();

    const toggle = screen.getByTestId("node-panel-toggle");
    expect(toggle).toHaveAttribute("aria-expanded", "true");

    // Manual collapse: body unmounts, header keeps the role name.
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByTestId("node-panel-body")).not.toBeInTheDocument();

    // Selecting another node while collapsed reveals the panel again.
    await userEvent.click(screen.getByTestId("canvas-node-portfolio_manager"));
    await waitFor(() => {
      expect(screen.getByTestId("node-panel-toggle")).toHaveAttribute(
        "aria-expanded",
        "true",
      );
    });
    const body = screen.getByTestId("node-panel-body");
    expect(
      screen.getByRole("heading", { name: /投资经理/ }),
    ).toBeInTheDocument();
    expect(body.textContent).toContain("综合各方结论");
  });

  it("keeps the no-selection hint while expanded and nothing is selected", async () => {
    render(<RunView runId="swarm-777" readOnly />);
    const body = await screen.findByTestId("node-panel-body");
    expect(body.textContent).toContain("Click a role");
  });
});

describe("RunView failure reasons", () => {
  it("lists every failed task concrete error when the run failed", async () => {
    const run = buildRun();
    run.status = "failed";
    run.final_report = null;
    run.completed_at = "2026-09-30T10:05:00+00:00";
    run.tasks[0].status = "failed";
    run.tasks[0].error =
      "LLM call failed at iteration 1: provider_stream_error provider=glm model=glm-5.3-flash: OpenAITimeoutError: Request timed out.";
    getSwarmRun.mockResolvedValue(run);

    render(<RunView runId="swarm-777" readOnly />);
    const reasons = await screen.findByTestId("run-failure-reasons");
    expect(reasons.textContent).toContain("首席风险官");
    expect(reasons.textContent).toContain("OpenAITimeoutError");
  });
});

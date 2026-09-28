import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SwarmStudio } from "../SwarmStudio";

const PRESETS = [
  {
    name: "investment_committee",
    title: "Investment Committee",
    description: "Bull vs bear, CRO review, PM decision.",
    agent_count: 4,
    variables: [],
    source: "bundled",
  },
  {
    name: "factor_research_committee",
    title: "Factor Research Committee",
    description: "Factor team preset.",
    agent_count: 5,
    variables: [],
    source: "bundled",
  },
];

const IC_DETAIL = {
  name: "investment_committee",
  title: "Investment Committee",
  description: "Bull vs bear, CRO review, PM decision.",
  variables: [],
  agents: [
    {
      id: "bull_advocate",
      role: "Bull Advocate",
      system_prompt: "Build the bull case.",
      tools: ["get_market_data", "load_skill"],
      skills: [],
      max_iterations: 25,
      timeout_seconds: 300,
      model_name: null,
    },
    {
      id: "bear_advocate",
      role: "Bear Advocate",
      system_prompt: "Build the bear case.",
      tools: ["get_market_data", "load_skill"],
      skills: [],
      max_iterations: 25,
      timeout_seconds: 300,
      model_name: null,
    },
    {
      id: "risk_officer",
      role: "Chief Risk Officer",
      system_prompt: "Review risks.",
      tools: ["get_market_data", "load_skill"],
      skills: [],
      max_iterations: 25,
      timeout_seconds: 600,
      model_name: null,
    },
    {
      id: "portfolio_manager",
      role: "Portfolio Manager",
      system_prompt: "Make the final call.\n\n{upstream_context}",
      tools: ["backtest", "load_skill"],
      skills: ["strategy-generate"],
      max_iterations: 50,
      timeout_seconds: 1800,
      model_name: null,
    },
  ],
  tasks: [
    {
      id: "task-bull",
      agent_id: "bull_advocate",
      prompt_template: "Bull research on {target}.",
      depends_on: [],
      input_from: {},
    },
    {
      id: "task-bear",
      agent_id: "bear_advocate",
      prompt_template: "Bear research on {target}.",
      depends_on: [],
      input_from: {},
    },
    {
      id: "task-risk",
      agent_id: "risk_officer",
      prompt_template: "Risk review on {target}.",
      depends_on: ["task-bull", "task-bear"],
      input_from: { bull_report: "task-bull", bear_report: "task-bear" },
    },
    {
      id: "task-decision",
      agent_id: "portfolio_manager",
      prompt_template: "Final decision on {target}.",
      depends_on: ["task-risk"],
      input_from: { full_debate: "task-risk" },
    },
  ],
  tool_catalog: ["backtest", "bash", "get_market_data", "load_skill", "read_file", "write_file"],
  layers: [
    ["task-bull", "task-bear"],
    ["task-risk"],
    ["task-decision"],
  ],
};

const COMPLETED_RUN = {
  id: "swarm-123",
  preset_name: "investment_committee",
  status: "completed",
  user_vars: { target: "600519.SH" },
  agents: IC_DETAIL.agents,
  tasks: IC_DETAIL.tasks.map((t, i) => ({
    ...t,
    status: "completed",
    summary: `summary ${i}`,
    error: null,
  })),
  created_at: "2026-09-24T10:00:00+00:00",
  completed_at: "2026-09-24T10:05:00+00:00",
  final_report: "倾向做多，仓位 30%。",
  customized: true,
  research_target: "600519.SH",
  research_question: "做多还是做空",
};

const listSwarmPresets = vi.fn();
const getSwarmPresetDetail = vi.fn();
const createSwarmRun = vi.fn();
const listSwarmRuns = vi.fn();
const getSwarmRun = vi.fn();

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: {
      listSwarmPresets: (...args: unknown[]) => listSwarmPresets(...args),
      getSwarmPresetDetail: (...args: unknown[]) => getSwarmPresetDetail(...args),
      createSwarmRun: (...args: unknown[]) => createSwarmRun(...args),
      listSwarmRuns: (...args: unknown[]) => listSwarmRuns(...args),
      getSwarmRun: (...args: unknown[]) => getSwarmRun(...args),
      swarmSseUrl: vi.fn(async () => "http://test/events"),
      cancelSwarmRun: vi.fn(async () => ({ status: "cancelled" })),
    },
  };
});

beforeEach(() => {
  vi.clearAllMocks();
  listSwarmPresets.mockResolvedValue(PRESETS);
  getSwarmPresetDetail.mockResolvedValue(IC_DETAIL);
  createSwarmRun.mockResolvedValue({ id: "swarm-123", status: "pending" });
  listSwarmRuns.mockResolvedValue([]);
  getSwarmRun.mockResolvedValue(COMPLETED_RUN);
});

describe("SwarmStudio", () => {
  it("shows every built-in preset and opens the canvas with the preset graph", async () => {
    render(<SwarmStudio />);

    await waitFor(() =>
      expect(screen.getByTestId("preset-card-investment_committee")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("preset-card-factor_research_committee")).toBeInTheDocument();

    await userEvent.click(screen.getByTestId("preset-card-investment_committee"));

    await waitFor(() =>
      expect(screen.getByTestId("swarm-edit-view")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("canvas-node-bull_advocate")).toBeInTheDocument();
    expect(screen.getByTestId("canvas-node-portfolio_manager")).toBeInTheDocument();
    expect(screen.getByText("Final decision")).toBeInTheDocument();
  });

  it("blocks launch for invalid graphs or missing inputs, then launches with the custom payload", async () => {
    render(<SwarmStudio />);
    await waitFor(() =>
      expect(screen.getByTestId("preset-card-investment_committee")).toBeInTheDocument(),
    );
    await userEvent.click(screen.getByTestId("preset-card-investment_committee"));
    await screen.findByTestId("swarm-edit-view");

    const launchBtn = screen.getByTestId("launch-btn");
    expect(launchBtn).toBeDisabled();

    await userEvent.type(screen.getByTestId("target-input"), "600519.SH");
    await userEvent.type(screen.getByTestId("question-input"), "long or short");
    await waitFor(() => expect(screen.getByTestId("graph-valid")).toBeInTheDocument());
    expect(launchBtn).toBeEnabled();

    // Invalidate: clear the selected node's duty (first node selected by default)
    const dutyInput = screen.getByTestId("node-duty-input") as HTMLTextAreaElement;
    await userEvent.clear(dutyInput);
    expect(screen.getByTestId("issue-emptyDuty")).toBeInTheDocument();
    expect(launchBtn).toBeDisabled();
    await userEvent.type(dutyInput, "restored duty");
    await waitFor(() => expect(launchBtn).toBeEnabled());

    await userEvent.click(launchBtn);

    await waitFor(() => expect(createSwarmRun).toHaveBeenCalledTimes(1));
    const [presetName, userVars, custom] = createSwarmRun.mock.calls[0];
    expect(presetName).toBe("investment_committee");
    expect(userVars).toEqual({ target: "600519.SH" });
    expect(custom.target).toBe("600519.SH");
    expect(custom.question).toBe("long or short");
    expect(custom.nodes).toHaveLength(4);
    expect(custom.edges).toEqual(
      expect.arrayContaining([
        { upstream: "risk_officer", downstream: "portfolio_manager" },
      ]),
    );

    await waitFor(() => expect(screen.getByTestId("run-view")).toBeInTheDocument());
    expect(screen.getByTestId("final-decision-content")).toHaveTextContent(
      "倾向做多",
    );
  });
});

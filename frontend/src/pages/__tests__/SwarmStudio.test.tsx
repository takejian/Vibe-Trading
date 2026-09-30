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
  skill_catalog: ["strategy-generate", "asset-allocation"],
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
const listCustomTeams = vi.fn();
const getCustomTeam = vi.fn();
const createCustomTeam = vi.fn();
const updateCustomTeam = vi.fn();
const deleteCustomTeam = vi.fn();
const getSkillCatalog = vi.fn();
const getSkillCapabilities = vi.fn();
const createSkillTrial = vi.fn();
const listSkillTrials = vi.fn();
const listRoleGroups = vi.fn();
const getRoleDetail = vi.fn();

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
      listCustomTeams: (...args: unknown[]) => listCustomTeams(...args),
      getCustomTeam: (...args: unknown[]) => getCustomTeam(...args),
      createCustomTeam: (...args: unknown[]) => createCustomTeam(...args),
      updateCustomTeam: (...args: unknown[]) => updateCustomTeam(...args),
      deleteCustomTeam: (...args: unknown[]) => deleteCustomTeam(...args),
      getSkillCatalog: (...args: unknown[]) => getSkillCatalog(...args),
      getSkillCapabilities: (...args: unknown[]) => getSkillCapabilities(...args),
      createSkillTrial: (...args: unknown[]) => createSkillTrial(...args),
      listSkillTrials: (...args: unknown[]) => listSkillTrials(...args),
      listRoleGroups: (...args: unknown[]) => listRoleGroups(...args),
      getRoleDetail: (...args: unknown[]) => getRoleDetail(...args),
      importSkillPackage: vi.fn(),
      syncSkills: vi.fn(),
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
  listCustomTeams.mockResolvedValue([]);
  getSkillCatalog.mockResolvedValue({
    skills: [
      {
        name: "behavioral-finance",
        description: "Behavioral finance analysis",
        category: "analysis",
        source: "bundled",
        approved: true,
      },
      {
        name: "cookbook",
        description: "recipes",
        category: "other",
        source: "user",
        approved: false,
      },
    ],
  });
  getSkillCapabilities.mockResolvedValue({
    admin_enabled: false,
    sync_source_configured: false,
  });
  createSkillTrial.mockResolvedValue({
    id: "swarm-trial-1",
    status: "pending",
    kind: "skill_trial",
    trial_skill: "behavioral-finance",
  });
  listSkillTrials.mockResolvedValue([]);
  listRoleGroups.mockResolvedValue({ groups: [] });
  getRoleDetail.mockResolvedValue({
    kind: "builtin",
    ref: "investment_committee:bull_advocate",
    name: "Bull Advocate",
    purpose: "argues the bull case",
    system_prompt: "You are the bull advocate.",
    tools: ["get_market_data"],
    skills: [],
    max_iterations: 25,
    timeout_seconds: 300,
    approved: true,
  });
  createCustomTeam.mockResolvedValue({
    id: "team-abc123",
    name: "My Team",
    updated_at: "2026-09-25T00:00:00+00:00",
  });
  updateCustomTeam.mockResolvedValue({
    id: "team-abc123",
    name: "My Team",
    updated_at: "2026-09-25T00:00:00+00:00",
  });
  deleteCustomTeam.mockResolvedValue({ status: "deleted" });
  getCustomTeam.mockResolvedValue({
    id: "team-abc123",
    name: "My Team",
    description: "mine",
    source_preset: "investment_committee",
    nodes: [],
    edges: [],
    created_at: "2026-09-25T00:00:00+00:00",
    updated_at: "2026-09-25T00:00:00+00:00",
  });
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

  it("saves the canvas as a personal custom team", async () => {
    render(<SwarmStudio />);
    await waitFor(() =>
      expect(screen.getByTestId("preset-card-investment_committee")).toBeInTheDocument(),
    );
    await userEvent.click(screen.getByTestId("preset-card-investment_committee"));
    await screen.findByTestId("swarm-edit-view");

    await userEvent.click(screen.getByTestId("save-team-btn"));
    await screen.findByTestId("save-team-dialog");
    await userEvent.type(screen.getByTestId("team-name-input"), "我的宏观团队");
    await userEvent.type(screen.getByTestId("team-description-input"), "宏观场景");
    await userEvent.click(screen.getByTestId("team-save-confirm"));

    await waitFor(() => expect(createCustomTeam).toHaveBeenCalledTimes(1));
    const body = createCustomTeam.mock.calls[0][0];
    expect(body.name).toBe("我的宏观团队");
    expect(body.description).toBe("宏观场景");
    expect(body.source_preset).toBe("investment_committee");
    expect(body.nodes).toHaveLength(4);
    const pmNode = body.nodes.find((n: { id: string }) => n.id === "portfolio_manager");
    expect(pmNode.skills).toEqual(
      expect.arrayContaining(["strategy-generate"]),
    );
    await waitFor(() =>
      expect(screen.queryByTestId("save-team-dialog")).not.toBeInTheDocument(),
    );
  });

  it("renders the Skill Square and launches a standalone trial", async () => {
    render(<SwarmStudio />);
    await waitFor(() =>
      expect(screen.getByTestId("preset-card-investment_committee")).toBeInTheDocument(),
    );

    await userEvent.click(screen.getByTestId("tab-skills"));
    const square = await screen.findByTestId("skill-square");
    expect(square).toBeInTheDocument();
    expect(screen.getByTestId("skill-card-behavioral-finance")).toBeInTheDocument();
    // Admin zone must stay hidden while the feature flag is off.
    expect(screen.queryByTestId("skill-admin-zone")).not.toBeInTheDocument();

    await userEvent.click(screen.getByTestId("skill-trial-set-behavioral-finance"));
    await userEvent.type(screen.getByTestId("trial-target-input"), "600519.SH");
    await userEvent.type(screen.getByTestId("trial-question-input"), "适合做多吗");
    await userEvent.click(screen.getByTestId("trial-launch-btn"));

    await waitFor(() => expect(createSkillTrial).toHaveBeenCalledTimes(1));
    expect(createSkillTrial.mock.calls[0][0]).toEqual({
      skill_name: "behavioral-finance",
      target: "600519.SH",
      question: "适合做多吗",
    });
    await waitFor(() => expect(screen.getByTestId("run-view")).toBeInTheDocument());
  });

  it("loads a saved custom team from the gallery", async () => {
    listCustomTeams.mockResolvedValue([
      {
        id: "team-abc123",
        name: "我的团队",
        description: "简介",
        source_preset: "investment_committee",
        role_count: 4,
        created_at: "2026-09-25T00:00:00+00:00",
        updated_at: "2026-09-25T00:00:00+00:00",
      },
    ]);
    getCustomTeam.mockResolvedValue({
      id: "team-abc123",
      name: "我的团队",
      description: "简介",
      source_preset: "investment_committee",
      nodes: IC_DETAIL.agents.map((a) => ({
        id: a.id,
        role: a.role,
        duty: a.system_prompt,
        tools: a.tools,
        skills: a.skills,
        timeout_seconds: a.timeout_seconds,
        source_task_id: null,
        is_new: false,
      })),
      edges: [
        { upstream: "bull_advocate", downstream: "risk_officer" },
        { upstream: "bear_advocate", downstream: "risk_officer" },
        { upstream: "risk_officer", downstream: "portfolio_manager" },
      ],
      created_at: "2026-09-25T00:00:00+00:00",
      updated_at: "2026-09-25T00:00:00+00:00",
    });

    render(<SwarmStudio />);
    const card = await screen.findByTestId("custom-team-card-team-abc123");
    await userEvent.click(card);

    await waitFor(() => expect(getCustomTeam).toHaveBeenCalledWith("team-abc123"));
    await screen.findByTestId("swarm-edit-view");
    expect(screen.getByTestId("canvas-node-bull_advocate")).toBeInTheDocument();
    // Editing an existing team shows update/delete instead of a second save-as.
    expect(screen.getByTestId("update-team-btn")).toBeInTheDocument();
    expect(screen.getByTestId("delete-team-btn")).toBeInTheDocument();
  });
  it("introduces an approved role from the role picker as a new canvas node", async () => {
    listRoleGroups.mockResolvedValue({
      groups: [
        {
          kind: "builtin",
          ref: "investment_committee",
          title: "Investment Committee",
          description: "",
          roles: [
            {
              ref: "investment_committee:bull_advocate",
              name: "Bull Advocate",
              purpose: "argues the bull case",
              approved: true,
            },
          ],
        },
      ],
    });
    render(<SwarmStudio />);
    await waitFor(() =>
      expect(screen.getByTestId("preset-card-investment_committee")).toBeInTheDocument(),
    );
    await userEvent.click(screen.getByTestId("preset-card-investment_committee"));
    await screen.findByTestId("swarm-edit-view");

    await userEvent.click(screen.getByTestId("add-node-btn"));
    expect(screen.getByTestId("role-picker-dialog")).toBeInTheDocument();

    await userEvent.click(
      screen.getByTestId("role-pick-investment_committee:bull_advocate"),
    );
    await waitFor(() =>
      expect(screen.getByTestId("canvas-node-node_5")).toBeInTheDocument(),
    );
  });

});

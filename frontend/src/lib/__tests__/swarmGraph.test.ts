import { describe, expect, it } from "vitest";
import {
  computeLayers,
  draftFromCustomTeam,
  draftFromPresetDetail,
  edgesFromRunTasks,
  isLaunchable,
  nextNodeId,
  toCustomPayload,
  validateGraph,
  type FlowEdge,
  type FlowNodeDraft,
  type SwarmPresetDetail,
} from "@/lib/swarmGraph";

function node(id: string, overrides: Partial<FlowNodeDraft> = {}): FlowNodeDraft {
  return {
    id,
    role: id,
    duty: `duty of ${id}`,
    tools: ["get_market_data"],
    skills: [],
    timeoutSeconds: 300,
    isNew: false,
    ...overrides,
  };
}

const icNodes = (): FlowNodeDraft[] => [
  node("bull_advocate", { sourceTaskId: "task-bull" }),
  node("bear_advocate", { sourceTaskId: "task-bear" }),
  node("risk_officer", { sourceTaskId: "task-risk" }),
  node("portfolio_manager", { sourceTaskId: "task-decision", timeoutSeconds: 1800 }),
];

const icEdges = (): FlowEdge[] => [
  { upstream: "bull_advocate", downstream: "risk_officer" },
  { upstream: "bear_advocate", downstream: "risk_officer" },
  { upstream: "risk_officer", downstream: "portfolio_manager" },
];

describe("computeLayers", () => {
  it("places independent nodes in the same layer and sequences dependencies", () => {
    const { layers, cycleNodes } = computeLayers(icNodes(), icEdges());
    expect(cycleNodes).toEqual([]);
    expect(layers).toHaveLength(3);
    expect(layers[0].sort()).toEqual(["bear_advocate", "bull_advocate"]);
    expect(layers[1]).toEqual(["risk_officer"]);
    expect(layers[2]).toEqual(["portfolio_manager"]);
  });

  it("reports nodes trapped in a cycle", () => {
    const nodes = [node("a"), node("b")];
    const edges: FlowEdge[] = [
      { upstream: "a", downstream: "b" },
      { upstream: "b", downstream: "a" },
    ];
    const { layers, cycleNodes } = computeLayers(nodes, edges);
    expect(layers).toEqual([]);
    expect(cycleNodes.sort()).toEqual(["a", "b"]);
  });
});

describe("validateGraph", () => {
  it("accepts the investment-committee shaped graph", () => {
    const issues = validateGraph(icNodes(), icEdges());
    expect(issues).toEqual([]);
    expect(isLaunchable(issues)).toBe(true);
  });

  it("flags a cycle with the participating nodes", () => {
    const edges = [...icEdges(), { upstream: "risk_officer", downstream: "bull_advocate" }];
    const issues = validateGraph(icNodes(), edges);
    const cycle = issues.find((i) => i.code === "cycle");
    expect(cycle).toBeDefined();
    expect(new Set(cycle!.nodeIds)).toEqual(
      new Set(["bull_advocate", "risk_officer"]),
    );
    expect(isLaunchable(issues)).toBe(false);
  });

  it("flags orphan nodes that participate in no edge", () => {
    const issues = validateGraph(
      [...icNodes(), node("lonely", { isNew: true })],
      icEdges(),
    );
    expect(issues.some((i) => i.code === "orphan" && i.nodeIds.includes("lonely"))).toBe(true);
  });

  it("flags dangling edges", () => {
    const issues = validateGraph(icNodes(), [
      ...icEdges(),
      { upstream: "ghost", downstream: "risk_officer" },
    ]);
    expect(issues.some((i) => i.code === "danglingEdge")).toBe(true);
  });

  it("flags self loops", () => {
    const issues = validateGraph(icNodes(), [
      ...icEdges(),
      { upstream: "risk_officer", downstream: "risk_officer" },
    ]);
    expect(issues.some((i) => i.code === "selfLoop")).toBe(true);
  });

  it("flags missing role and duty", () => {
    const issues = validateGraph(
      [node("a", { role: "  ", duty: "" })],
      [],
    );
    expect(issues.map((i) => i.code).sort()).toEqual(["emptyDuty", "emptyRole"]);
  });

  it.each([0, -1, 1801, 2.5, NaN])("flags invalid timeout %s", (timeout) => {
    const issues = validateGraph([node("a", { timeoutSeconds: timeout })], []);
    expect(issues.some((i) => i.code === "invalidTimeout")).toBe(true);
  });

  it("flags invalid and duplicate node ids", () => {
    const badId = validateGraph([node("../x")], []);
    expect(badId.some((i) => i.code === "invalidNodeId")).toBe(true);
    const dup = validateGraph([node("a"), node("a")], []);
    expect(dup.some((i) => i.code === "duplicateNode")).toBe(true);
  });

  it("accepts a single-node graph without edges", () => {
    const issues = validateGraph([node("solo")], []);
    expect(issues).toEqual([]);
  });

  it("rejects an empty graph", () => {
    const issues = validateGraph([], []);
    expect(issues[0].code).toBe("emptyGraph");
    expect(isLaunchable(issues)).toBe(false);
  });
});

describe("toCustomPayload", () => {
  it("maps draft fields to the backend contract and dedupes edges", () => {
    const payload = toCustomPayload(
      icNodes(),
      [
        ...icEdges(),
        { upstream: "bull_advocate", downstream: "risk_officer" },
      ],
      " 600519.SH ",
      " long or short ",
    );
    expect(payload.target).toBe("600519.SH");
    expect(payload.question).toBe("long or short");
    expect(payload.nodes[3]).toMatchObject({
      id: "portfolio_manager",
      timeout_seconds: 1800,
      source_task_id: "task-decision",
      is_new: false,
    });
    expect(payload.edges).toHaveLength(3);
  });
});

describe("draftFromPresetDetail", () => {
  it("round-trips agents/tasks into editable nodes and agent-level edges", () => {
    const detail: SwarmPresetDetail = {
      name: "investment_committee",
      title: "Investment Committee",
      description: "",
      variables: [],
      agents: [
        {
          id: "bull_advocate",
          role: "Bull",
          system_prompt: "bull duty",
          tools: ["get_market_data"],
          skills: [],
          max_iterations: 25,
          timeout_seconds: 300,
        },
        {
          id: "risk_officer",
          role: "CRO",
          system_prompt: "risk duty",
          tools: [],
          skills: [],
          max_iterations: 25,
          timeout_seconds: 300,
        },
      ],
      tasks: [
        {
          id: "task-bull",
          agent_id: "bull_advocate",
          prompt_template: "bull template",
          depends_on: [],
          input_from: {},
        },
        {
          id: "task-risk",
          agent_id: "risk_officer",
          prompt_template: "risk template",
          depends_on: ["task-bull"],
          input_from: { bull_report: "task-bull" },
        },
      ],
      tool_catalog: ["get_market_data"],
      layers: [["task-bull"], ["task-risk"]],
    };

    const draft = draftFromPresetDetail(detail);
    expect(draft.nodes.map((n) => n.id)).toEqual(["bull_advocate", "risk_officer"]);
    expect(draft.nodes[0]).toMatchObject({
      duty: "bull duty",
      sourceTaskId: "task-bull",
      isNew: false,
    });
    expect(draft.edges).toEqual([
      { upstream: "bull_advocate", downstream: "risk_officer" },
    ]);
  });
});

describe("edgesFromRunTasks", () => {
  it("maps task dependencies to agent-level edges", () => {
    const edges = edgesFromRunTasks([
      { id: "t1", agent_id: "a", depends_on: [], status: "completed" },
      { id: "t2", agent_id: "b", depends_on: ["t1"], status: "pending" },
    ]);
    expect(edges).toEqual([{ upstream: "a", downstream: "b" }]);
  });
});

describe("nextNodeId", () => {
  it("returns the first free node_N id", () => {
    expect(nextNodeId([])).toBe("node_1");
    expect(nextNodeId([node("node_1")])).toBe("node_2");
  });
});

describe("skill whitelist validation", () => {
  it("does not check skills when no whitelist is provided", () => {
    const issues = validateGraph(
      [node("a", { skills: ["anything-goes"] })],
      [],
    );
    expect(issues).toEqual([]);
  });

  it("flags skills outside the preset ∪ approved whitelist", () => {
    const issues = validateGraph(
      [node("a", { skills: ["known-skill", "mystery-skill"] })],
      [],
      ["known-skill"],
    );
    const unknown = issues.find((i) => i.code === "unknownSkill");
    expect(unknown).toBeDefined();
    expect(unknown!.nodeIds).toEqual(["a"]);
    expect(isLaunchable(issues)).toBe(false);
  });

  it("accepts whitelisted skills (including iterables other than arrays)", () => {
    const issues = validateGraph(
      [node("a", { skills: ["s1", "s2"] })],
      [],
      new Set(["s1", "s2", "s3"]),
    );
    expect(issues).toEqual([]);
  });
});

describe("skills in payloads and drafts", () => {
  it("serializes node skills sorted into the custom payload", () => {
    const payload = toCustomPayload(
      [node("a", { skills: ["zeta-skill", "alpha-skill"] })],
      [],
      "t",
      "q",
    );
    expect(payload.nodes[0].skills).toEqual(["alpha-skill", "zeta-skill"]);
  });

  it("rebuilds a draft from a saved custom team, defaulting missing skills", () => {
    const draft = draftFromCustomTeam({
      source_preset: "investment_committee",
      nodes: [
        {
          id: "a",
          role: "Analyst",
          duty: "duty",
          tools: ["get_market_data"],
          timeout_seconds: 300,
          source_task_id: "task-a",
          is_new: false,
        },
        {
          id: "b",
          role: "Manager",
          duty: "decide",
          tools: [],
          skills: ["strategy-generate"],
          timeout_seconds: 600,
          source_task_id: null,
          is_new: true,
        },
      ],
      edges: [
        { upstream: "a", downstream: "b" },
        { upstream: "a", downstream: "b" },
      ],
    });
    expect(draft.nodes.map((n) => n.skills)).toEqual([[], ["strategy-generate"]]);
    expect(draft.nodes[1].isNew).toBe(true);
    expect(draft.edges).toHaveLength(1);
  });

  it("carries preset agent skills into the draft", () => {
    const detail: SwarmPresetDetail = {
      name: "p",
      title: "P",
      description: "",
      variables: [],
      agents: [
        {
          id: "a",
          role: "Analyst",
          system_prompt: "duty",
          tools: [],
          skills: ["behavioral-finance", "asset-allocation"],
          max_iterations: 25,
          timeout_seconds: 300,
        },
      ],
      tasks: [
        {
          id: "task-a",
          agent_id: "a",
          prompt_template: "go",
          depends_on: [],
          input_from: {},
        },
      ],
      tool_catalog: [],
      skill_catalog: ["behavioral-finance", "asset-allocation"],
      layers: [["task-a"]],
    };
    const draft = draftFromPresetDetail(detail);
    expect(draft.nodes[0].skills).toEqual(["behavioral-finance", "asset-allocation"]);
  });
});

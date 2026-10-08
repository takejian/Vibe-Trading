import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { RoleSquare } from "../RoleSquare";

const ROLE_REF = "role-conv123";

const PROFILE = {
  kind: "custom" as const,
  ref: ROLE_REF,
  name: "可转债狙击手",
  purpose: "埋伏下修博弈",
  system_prompt: "You hunt convertible bonds for reset odds.",
  tools: ["get_market_data"],
  skills: [],
  max_iterations: 20,
  timeout_seconds: 240,
  approved: false,
};

const listRoleGroups = vi.fn();
const getRoleDetail = vi.fn();
const getSkillCatalog = vi.fn();
const getSkillCapabilities = vi.fn();
const createCustomRole = vi.fn();
const updateCustomRole = vi.fn();
const deleteCustomRole = vi.fn();
const approveRole = vi.fn();
const unapproveRole = vi.fn();
const createRoleRun = vi.fn();
const listRoleRuns = vi.fn();
const listSwarmRuns = vi.fn();
const getSwarmRun = vi.fn();
const createSession = vi.fn();
const sendMessage = vi.fn();
const navigate = vi.fn();

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: {
      listRoleGroups: (...args: unknown[]) => listRoleGroups(...args),
      getRoleDetail: (...args: unknown[]) => getRoleDetail(...args),
      getSkillCatalog: (...args: unknown[]) => getSkillCatalog(...args),
      getSkillCapabilities: (...args: unknown[]) => getSkillCapabilities(...args),
      createCustomRole: (...args: unknown[]) => createCustomRole(...args),
      updateCustomRole: (...args: unknown[]) => updateCustomRole(...args),
      deleteCustomRole: (...args: unknown[]) => deleteCustomRole(...args),
      approveRole: (...args: unknown[]) => approveRole(...args),
      unapproveRole: (...args: unknown[]) => unapproveRole(...args),
      createRoleRun: (...args: unknown[]) => createRoleRun(...args),
      listRoleRuns: (...args: unknown[]) => listRoleRuns(...args),
      listSwarmRuns: (...args: unknown[]) => listSwarmRuns(...args),
      getSwarmRun: (...args: unknown[]) => getSwarmRun(...args),
      createSession: (...args: unknown[]) => createSession(...args),
      sendMessage: (...args: unknown[]) => sendMessage(...args),
      swarmSseUrl: vi.fn(async () => "http://test/events"),
      cancelSwarmRun: vi.fn(async () => ({ status: "cancelled" })),
    },
  };
});

vi.mock("react-router", async () => {
  const actual = await vi.importActual<typeof import("react-router")>(
    "react-router",
  );
  return { ...actual, useNavigate: () => navigate };
});

import { resetMacroEvalCache } from "@/components/macro/macroEvalRecords";

const GROUPS = {
  groups: [
    {
      kind: "builtin" as const,
      ref: "investment_committee",
      title: "Investment Committee",
      description: "Bull vs bear team",
      roles: [
        {
          ref: "investment_committee:bull_advocate",
          name: "多头代理人",
          purpose: "论证多头逻辑",
          approved: true,
        },
      ],
    },
    {
      kind: "custom" as const,
      ref: "custom",
      title: "自建角色",
      description: "",
      roles: [
        {
          ref: ROLE_REF,
          name: "可转债狙击手",
          purpose: "埋伏下修博弈",
          approved: false,
        },
      ],
    },
  ],
  tool_catalog: ["get_market_data"],
};

const COMPLETED_RUN = {
  id: "role-run-1",
  preset_name: `role:${ROLE_REF}`,
  status: "completed",
  user_vars: { target: "113001.SH" },
  agents: [],
  tasks: [],
  created_at: "2026-09-24T10:00:00+00:00",
  completed_at: "2026-09-24T10:05:00+00:00",
  final_report: "下修概率高",
  kind: "role_run",
  trial_role: ROLE_REF,
};

beforeEach(() => {
  vi.clearAllMocks();
  listRoleGroups.mockResolvedValue(GROUPS);
  getRoleDetail.mockResolvedValue(PROFILE);
  getSkillCatalog.mockResolvedValue({ skills: [] });
  getSkillCapabilities.mockResolvedValue({
    admin_enabled: false,
    sync_source_configured: false,
  });
  createCustomRole.mockResolvedValue({
    id: ROLE_REF,
    name: PROFILE.name,
    approved: false,
    updated_at: "2026-09-24T10:00:00+00:00",
  });
  updateCustomRole.mockResolvedValue({
    id: ROLE_REF,
    name: PROFILE.name,
    approved: false,
    updated_at: "2026-09-24T10:01:00+00:00",
  });
  deleteCustomRole.mockResolvedValue({ status: "deleted" });
  approveRole.mockResolvedValue({
    id: ROLE_REF,
    approved: true,
    approved_at: "2026-09-24T10:02:00+00:00",
  });
  unapproveRole.mockResolvedValue({ id: ROLE_REF, approved: false });
  createRoleRun.mockResolvedValue({
    id: "role-run-1",
    status: "pending",
    kind: "role_run",
    trial_role: ROLE_REF,
  });
  listRoleRuns.mockResolvedValue([]);
  listSwarmRuns.mockResolvedValue([]);
  createSession.mockResolvedValue({ session_id: "sess-my" });
  sendMessage.mockResolvedValue({ message_id: "msg-my" });
  getSwarmRun.mockResolvedValue(COMPLETED_RUN);
  resetMacroEvalCache();
});

async function openCustomRole() {
  await waitFor(() =>
    expect(screen.getByTestId(`role-card-${ROLE_REF}`)).toBeInTheDocument(),
  );
  await userEvent.click(screen.getByTestId(`role-card-${ROLE_REF}`));
  await waitFor(() =>
    expect(screen.getByTestId("role-profile-view")).toBeInTheDocument(),
  );
}

describe("RoleSquare list", () => {
  it("renders grouped roles (builtin + custom)", async () => {
    render(<RoleSquare />);
    await waitFor(() =>
      expect(screen.getByTestId("role-groups")).toBeInTheDocument(),
    );
    expect(screen.getByText("Investment Committee")).toBeInTheDocument();
    expect(screen.getByTestId(`role-card-${ROLE_REF}`)).toBeInTheDocument();
    expect(screen.getByTestId("group-search-custom")).toBeInTheDocument();
  });

  it("filters roles within a group via its own search box", async () => {
    render(<RoleSquare />);
    await screen.findByTestId("role-groups");
    await userEvent.type(screen.getByTestId("group-search-custom"), "不存在的名字");
    expect(screen.queryByTestId(`role-card-${ROLE_REF}`)).not.toBeInTheDocument();
    expect(screen.getByText("No matching role in this group")).toBeInTheDocument();
  });

  it("shows the underlying error and retries successfully", async () => {
    listRoleGroups.mockRejectedValue(new Error("Server unreachable"));
    render(<RoleSquare />);
    await waitFor(() =>
      expect(screen.getByText("Server unreachable")).toBeInTheDocument(),
    );
    listRoleGroups.mockResolvedValue(GROUPS);
    await userEvent.click(screen.getByTestId("role-list-retry-btn"));
    await waitFor(() =>
      expect(screen.getByTestId(`role-card-${ROLE_REF}`)).toBeInTheDocument(),
    );
  });

  it("opens the role detail profile tab", async () => {
    render(<RoleSquare />);
    await openCustomRole();
    expect(screen.getByText("可转债狙击手")).toBeInTheDocument();
    expect(screen.getByText("埋伏下修博弈")).toBeInTheDocument();
    expect(screen.getByTestId("role-edit-btn")).toBeInTheDocument();
    expect(screen.getByTestId("role-delete-btn")).toBeInTheDocument();
    expect(screen.queryByTestId("role-approve-btn")).not.toBeInTheDocument();
  });
});

describe("RoleSquare create", () => {
  it("creates a custom role from a blank form", async () => {
    render(<RoleSquare />);
    await screen.findByTestId("role-groups");
    await userEvent.click(screen.getByTestId("create-role-btn"));
    expect(screen.getByTestId("role-form")).toBeInTheDocument();

    await userEvent.type(screen.getByTestId("role-form-name"), "红利低波侦察兵");
    await userEvent.type(
      screen.getByTestId("role-form-prompt"),
      "You screen dividend low-volatility stocks.",
    );
    await userEvent.click(screen.getByTestId("role-form-submit"));

    await waitFor(() => expect(createCustomRole).toHaveBeenCalledTimes(1));
    const body = createCustomRole.mock.calls[0][0];
    expect(body).toMatchObject({
      name: "红利低波侦察兵",
      timeout_seconds: 300,
    });
    await waitFor(() =>
      expect(screen.getByTestId("role-profile-view")).toBeInTheDocument(),
    );
  });

  it("derives a new role from an approved template", async () => {
    const template = {
      kind: "builtin" as const,
      ref: "investment_committee:bull_advocate",
      name: "多头代理人",
      purpose: "论证多头逻辑",
      system_prompt: "You argue the bull case with evidence.",
      tools: ["get_market_data"],
      skills: [],
      max_iterations: 30,
      timeout_seconds: 420,
      approved: true,
    };
    getRoleDetail.mockResolvedValue(template);

    render(<RoleSquare />);
    await screen.findByTestId("role-groups");
    await userEvent.click(screen.getByTestId("create-role-btn"));

    const picker = screen.getByTestId("role-form-template") as HTMLSelectElement;
    const optionValues = Array.from(picker.options).map((option) => option.value);
    expect(optionValues).toContain("investment_committee:bull_advocate");
    // Unapproved custom roles are not usable as templates.
    expect(optionValues).not.toContain(ROLE_REF);

    await userEvent.selectOptions(
      picker,
      "investment_committee:bull_advocate",
    );

    await waitFor(() =>
      expect(screen.getByTestId("role-form-prompt")).toHaveValue(
        template.system_prompt,
      ),
    );
    // The name is never carried over; it must be entered anew.
    expect(screen.getByTestId("role-form-name")).toHaveValue("");
    expect(screen.getByTestId("role-form-iterations")).toHaveValue(30);
    expect(screen.getByTestId("role-form-timeout")).toHaveValue(420);

    await userEvent.type(screen.getByTestId("role-form-name"), "多头代理人二代");
    await userEvent.click(screen.getByTestId("role-form-submit"));

    await waitFor(() => expect(createCustomRole).toHaveBeenCalledTimes(1));
    expect(createCustomRole.mock.calls[0][0]).toMatchObject({
      name: "多头代理人二代",
      template_ref: "investment_committee:bull_advocate",
      timeout_seconds: 420,
    });
  });
});

describe("RoleSquare standalone run", () => {
  it("launches a role run and opens the run view", async () => {
    render(<RoleSquare />);
    await openCustomRole();

    await userEvent.click(screen.getByTestId("role-tab-run"));
    await screen.findByTestId("role-run-panel");
    await userEvent.type(screen.getByTestId("role-run-target"), "113001.SH");
    await userEvent.type(
      screen.getByTestId("role-run-question"),
      "下修概率多大？",
    );
    await userEvent.click(screen.getByTestId("role-run-launch"));

    await waitFor(() => expect(createRoleRun).toHaveBeenCalledTimes(1));
    expect(createRoleRun.mock.calls[0][0]).toEqual({
      role_ref: ROLE_REF,
      target: "113001.SH",
      question: "下修概率多大？",
    });
    await waitFor(() =>
      expect(screen.getByTestId("run-view")).toBeInTheDocument(),
    );
  });
});

describe("RoleSquare history", () => {
  it("loads role-run history filtered by role ref", async () => {
    render(<RoleSquare />);
    await openCustomRole();

    await userEvent.click(screen.getByTestId("role-tab-history"));
    await waitFor(() => expect(listRoleRuns).toHaveBeenCalledTimes(2));
    expect(listRoleRuns.mock.calls[1][0]).toMatchObject({
      roleRef: ROLE_REF,
      limit: 100,
    });
  });
});

describe("RoleSquare operator actions", () => {
  it("approves then unapproves a role when admin is enabled", async () => {
    getSkillCapabilities.mockResolvedValue({
      admin_enabled: true,
      sync_source_configured: false,
    });
    render(<RoleSquare />);
    await openCustomRole();

    expect(screen.getByTestId("role-approve-btn")).toBeInTheDocument();
    getRoleDetail.mockResolvedValue({ ...PROFILE, approved: true });
    await userEvent.click(screen.getByTestId("role-approve-btn"));
    await waitFor(() => expect(approveRole).toHaveBeenCalledWith(ROLE_REF));

    await waitFor(() =>
      expect(screen.getByTestId("role-unapprove-btn")).toBeInTheDocument(),
    );
    await userEvent.click(screen.getByTestId("role-unapprove-btn"));
    await waitFor(() => expect(unapproveRole).toHaveBeenCalledWith(ROLE_REF));
  });

  it("deletes a role after confirmation and returns to the list", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<RoleSquare />);
    await openCustomRole();

    await userEvent.click(screen.getByTestId("role-delete-btn"));
    expect(confirmSpy).toHaveBeenCalled();
    await waitFor(() => expect(deleteCustomRole).toHaveBeenCalledWith(ROLE_REF));
    await waitFor(() =>
      expect(screen.getByTestId("role-groups")).toBeInTheDocument(),
    );
    confirmSpy.mockRestore();
  });

  it("keeps the role when deletion is not confirmed", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<RoleSquare />);
    await openCustomRole();
    await userEvent.click(screen.getByTestId("role-delete-btn"));
    expect(deleteCustomRole).not.toHaveBeenCalled();
  });
});

const MY_RUN_SUMMARY = {
  id: "role-run-7",
  preset_name: `role:${ROLE_REF}`,
  status: "completed" as const,
  created_at: "2026-09-28T08:00:00+00:00",
  completed_at: "2026-09-28T08:03:00+00:00",
  research_target: "113001.SH",
  research_question: "下修概率多大？",
  final_report_excerpt: "下修概率较高",
  kind: "role_run" as const,
  trial_role: ROLE_REF,
};

describe("RoleSquare my evaluations", () => {
  it("lists all standalone role runs with the macro role-record layout", async () => {
    listRoleRuns.mockResolvedValue([MY_RUN_SUMMARY]);
    render(<RoleSquare />);
    await waitFor(() =>
      expect(screen.getByTestId("role-groups")).toBeInTheDocument(),
    );

    await userEvent.click(screen.getByTestId("my-evaluations-btn"));
    const panel = await screen.findByTestId("my-evaluations-history");
    expect(
      await within(panel).findByTestId(
        "my-evaluations-history-row-role-run-7",
      ),
    ).toBeInTheDocument();
    expect(panel).toHaveTextContent("可转债狙击手");
    expect(panel).toHaveTextContent("113001.SH");
    expect(panel).toHaveTextContent("下修概率较高");

    await userEvent.click(screen.getByTestId("my-evals-back"));
    await screen.findByTestId("role-groups");
  });

  it("compares two checked role runs in a new AI session", async () => {
    const secondSummary = {
      ...MY_RUN_SUMMARY,
      id: "role-run-8",
      research_target: "128039.SH",
      final_report_excerpt: "博弈价值充足",
    };
    listRoleRuns.mockResolvedValue([MY_RUN_SUMMARY, secondSummary]);
    render(<RoleSquare />);
    await screen.findByTestId("role-groups");

    await userEvent.click(screen.getByTestId("my-evaluations-btn"));
    const panel = await screen.findByTestId("my-evaluations-history");
    await within(panel).findByTestId(
      "my-evaluations-history-row-role-run-7",
    );

    for (const id of ["role-run-7", "role-run-8"]) {
      await userEvent.click(
        within(panel).getByTestId(
          `my-evaluations-history-checkbox-${id}`,
        ),
      );
    }
    await userEvent.click(
      within(panel).getByTestId("my-evaluations-history-compare"),
    );

    await waitFor(() => expect(createSession).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(sendMessage).toHaveBeenCalledTimes(1));
    const prompt = sendMessage.mock.calls[0][1] as string;
    expect(prompt).toContain("可转债狙击手");
    expect(prompt).toContain("下修概率较高");
    expect(prompt).toContain("博弈价值充足");
  });
});

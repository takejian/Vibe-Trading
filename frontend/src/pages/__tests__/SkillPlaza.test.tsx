import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SkillPlaza } from "../SkillPlaza";

const CUSTOM_ID = "cskill-abc123def456";
const CUSTOM_NAME = "期权波动率曲面";
const ASSEMBLED_NAME = "缠论分析";

const ASSEMBLED_PROFILE = {
  kind: "assembled" as const,
  ref: `assembled:${ASSEMBLED_NAME}`,
  name: ASSEMBLED_NAME,
  purpose: "走势中枢、背驰与买卖点",
  methodology: "# 缠论分析\n按分型、笔、中枢逐级分析。",
  inputs: "",
  outputs: "",
  category: "analysis",
  approved: true,
  derived_from: null,
};

const CUSTOM_PROFILE = {
  kind: "custom" as const,
  ref: CUSTOM_ID,
  name: CUSTOM_NAME,
  purpose: "曲面建模、历史分位与套利机会提示",
  methodology: "采集隐含波动率曲面→历史分位→偏斜形态识别。",
  inputs: "标的代码/期权链行情",
  outputs: "波动率分位结论 + 关注价位表",
  category: "custom",
  approved: false,
  derived_from: null,
  created_at: "2026-09-20T00:00:00+00:00",
  updated_at: "2026-09-20T00:00:00+00:00",
};

const getSkillCatalog = vi.fn();
const getSkillCapabilities = vi.fn();
const getSkillDetail = vi.fn();
const createCustomSkill = vi.fn();
const updateCustomSkill = vi.fn();
const deleteCustomSkill = vi.fn();
const approveCustomSkill = vi.fn();
const unapproveCustomSkill = vi.fn();
const importPersonalSkillPackage = vi.fn();
const importSkillPackage = vi.fn();
const syncSkills = vi.fn();
const createSkillTrial = vi.fn();
const listSkillTrials = vi.fn();
const getSwarmRun = vi.fn();

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: {
      getSkillCatalog: (...args: unknown[]) => getSkillCatalog(...args),
      getSkillCapabilities: (...args: unknown[]) => getSkillCapabilities(...args),
      getSkillDetail: (...args: unknown[]) => getSkillDetail(...args),
      createCustomSkill: (...args: unknown[]) => createCustomSkill(...args),
      updateCustomSkill: (...args: unknown[]) => updateCustomSkill(...args),
      deleteCustomSkill: (...args: unknown[]) => deleteCustomSkill(...args),
      approveCustomSkill: (...args: unknown[]) => approveCustomSkill(...args),
      unapproveCustomSkill: (...args: unknown[]) => unapproveCustomSkill(...args),
      importPersonalSkillPackage: (...args: unknown[]) =>
        importPersonalSkillPackage(...args),
      importSkillPackage: (...args: unknown[]) => importSkillPackage(...args),
      syncSkills: (...args: unknown[]) => syncSkills(...args),
      createSkillTrial: (...args: unknown[]) => createSkillTrial(...args),
      listSkillTrials: (...args: unknown[]) => listSkillTrials(...args),
      getSwarmRun: (...args: unknown[]) => getSwarmRun(...args),
      swarmSseUrl: vi.fn(async () => "http://test/events"),
      cancelSwarmRun: vi.fn(async () => ({ status: "cancelled" })),
    },
  };
});

const CATALOG = {
  skills: [
    {
      name: ASSEMBLED_NAME,
      description: "走势中枢、背驰与买卖点",
      category: "analysis",
      source: "bundled" as const,
      kind: "bundled" as const,
      ref: `assembled:${ASSEMBLED_NAME}`,
      approved: true,
      derived_from: null,
    },
    {
      name: "艾略特波浪",
      description: "浪型计数与斐波那契",
      category: "analysis",
      source: "bundled" as const,
      kind: "bundled" as const,
      ref: "assembled:艾略特波浪",
      approved: false,
      derived_from: null,
    },
    {
      name: CUSTOM_NAME,
      description: "曲面建模、历史分位与套利机会提示",
      category: "custom",
      source: "user" as const,
      kind: "custom" as const,
      ref: CUSTOM_ID,
      approved: false,
      derived_from: null,
    },
  ],
};

const COMPLETED_RUN = {
  id: "swarm-trial-1",
  preset_name: `skill:${CUSTOM_NAME}`,
  status: "completed",
  user_vars: { target: "600519.SH" },
  agents: [],
  tasks: [],
  created_at: "2026-09-28T10:20:00+00:00",
  completed_at: "2026-09-28T10:25:00+00:00",
  final_report: "波动率处于历史 80% 分位。",
  kind: "skill_trial",
  trial_skill: CUSTOM_NAME,
};

beforeEach(() => {
  vi.clearAllMocks();
  getSkillCatalog.mockResolvedValue(CATALOG);
  getSkillCapabilities.mockResolvedValue({
    admin_enabled: false,
    sync_source_configured: false,
  });
  getSkillDetail.mockImplementation((ref: string) =>
    Promise.resolve(ref === CUSTOM_ID ? CUSTOM_PROFILE : ASSEMBLED_PROFILE),
  );
  createCustomSkill.mockResolvedValue({
    id: CUSTOM_ID,
    name: CUSTOM_NAME,
    approved: false,
    derived_from: null,
    updated_at: "2026-09-20T00:00:00+00:00",
  });
  updateCustomSkill.mockResolvedValue({
    id: CUSTOM_ID,
    name: CUSTOM_NAME,
    approved: false,
    updated_at: "2026-09-21T00:00:00+00:00",
  });
  deleteCustomSkill.mockResolvedValue({ status: "deleted" });
  approveCustomSkill.mockResolvedValue({
    id: CUSTOM_ID,
    approved: true,
    approved_at: "2026-09-29T00:00:00+00:00",
  });
  unapproveCustomSkill.mockResolvedValue({ id: CUSTOM_ID, approved: false });
  importPersonalSkillPackage.mockResolvedValue({
    installed: [{ id: "cskill-new0000000001", name: "龙虎榜游资跟踪" }],
  });
  importSkillPackage.mockResolvedValue({ installed: [] });
  syncSkills.mockResolvedValue({
    added: [],
    updated: [],
    removed: [],
    rejected: [],
  });
  createSkillTrial.mockResolvedValue({
    id: "swarm-trial-1",
    status: "pending",
    kind: "skill_trial",
    trial_skill: CUSTOM_NAME,
  });
  listSkillTrials.mockResolvedValue([]);
  getSwarmRun.mockResolvedValue(COMPLETED_RUN);
});

async function openSkill(cardTestId: string) {
  await waitFor(() =>
    expect(screen.getByTestId("skill-groups")).toBeInTheDocument(),
  );
  await userEvent.click(screen.getByTestId(cardTestId));
  await waitFor(() =>
    expect(screen.getByTestId("skill-profile-view")).toBeInTheDocument(),
  );
}

describe("SkillPlaza list", () => {
  it("renders two groups with within-group search and unapproved badge", async () => {
    render(<SkillPlaza />);
    await screen.findByTestId("skill-groups");
    expect(screen.getByTestId("skill-group-builtin")).toBeInTheDocument();
    expect(screen.getByTestId("skill-group-custom")).toBeInTheDocument();
    expect(screen.getByTestId(`skill-card-${ASSEMBLED_NAME}`)).toBeInTheDocument();
    expect(
      screen.getByTestId(`unapproved-badge-${CUSTOM_NAME}`),
    ).toBeInTheDocument();

    await userEvent.type(screen.getByTestId("group-search-builtin"), "波浪");
    expect(
      screen.queryByTestId(`skill-card-${ASSEMBLED_NAME}`),
    ).not.toBeInTheDocument();
    expect(screen.getByTestId("skill-card-艾略特波浪")).toBeInTheDocument();
  });

  it("hides the admin zone for non-admins", async () => {
    render(<SkillPlaza />);
    await screen.findByTestId("skill-groups");
    expect(screen.queryByTestId("skill-admin-zone")).not.toBeInTheDocument();
  });

  it("shows the admin zone when the capability is enabled", async () => {
    getSkillCapabilities.mockResolvedValue({
      admin_enabled: true,
      sync_source_configured: false,
    });
    render(<SkillPlaza />);
    await screen.findByTestId("skill-admin-zone");
    expect(screen.getByTestId("skill-import-btn")).toBeInTheDocument();
    expect(screen.getByTestId("skill-sync-btn")).toBeInTheDocument();
  });

  it("uploads a personal zip as an unapproved custom skill", async () => {
    render(<SkillPlaza />);
    await screen.findByTestId("skill-groups");
    const file = new File(["zipbytes"], "my-skill.zip", { type: "application/zip" });
    await userEvent.upload(screen.getByTestId("personal-import-file"), file);
    await waitFor(() => expect(importPersonalSkillPackage).toHaveBeenCalledTimes(1));
    expect(importPersonalSkillPackage.mock.calls[0][0]).toBe(file);
    await screen.findByTestId("personal-import-result");
  });
});

describe("SkillPlaza detail profile", () => {
  it("shows assembled skills read-only with a derive action", async () => {
    render(<SkillPlaza />);
    await openSkill(`skill-card-${ASSEMBLED_NAME}`);
    expect(screen.getByText(ASSEMBLED_NAME)).toBeInTheDocument();
    expect(screen.queryByTestId("skill-edit-btn")).not.toBeInTheDocument();
    expect(screen.queryByTestId("skill-delete-btn")).not.toBeInTheDocument();
    expect(screen.getByTestId("skill-derive-btn")).toBeInTheDocument();
  });

  it("shows custom skills with edit/delete and no approve button for non-admins", async () => {
    render(<SkillPlaza />);
    await openSkill(`skill-card-${CUSTOM_NAME}`);
    expect(screen.getByTestId("skill-edit-btn")).toBeInTheDocument();
    expect(screen.getByTestId("skill-delete-btn")).toBeInTheDocument();
    expect(screen.queryByTestId("skill-approve-btn")).not.toBeInTheDocument();
    expect(screen.queryByTestId("skill-unapprove-btn")).not.toBeInTheDocument();
  });

  it("disables the approve button without a qualified trial", async () => {
    getSkillCapabilities.mockResolvedValue({
      admin_enabled: true,
      sync_source_configured: false,
    });
    render(<SkillPlaza />);
    await openSkill(`skill-card-${CUSTOM_NAME}`);
    const button = screen.getByTestId("skill-approve-btn") as HTMLButtonElement;
    expect(button).toBeInTheDocument();
    expect(button.disabled).toBe(true);
    expect(screen.getByTestId("skill-approve-hint")).toBeInTheDocument();
    expect(approveCustomSkill).not.toHaveBeenCalled();
  });

  it("enables approve after a qualified trial and supports unapprove", async () => {
    getSkillCapabilities.mockResolvedValue({
      admin_enabled: true,
      sync_source_configured: false,
    });
    listSkillTrials.mockResolvedValue([
      {
        id: "swarm-trial-ok",
        preset_name: `skill:${CUSTOM_NAME}`,
        status: "completed",
        created_at: "2026-09-28T10:20:00+00:00",
        final_report_excerpt: "结论完整",
        kind: "skill_trial",
        trial_skill: CUSTOM_NAME,
        research_target: "600519.SH",
        research_question: "分位如何",
      },
    ]);
    render(<SkillPlaza />);
    await openSkill(`skill-card-${CUSTOM_NAME}`);
    const button = screen.getByTestId("skill-approve-btn") as HTMLButtonElement;
    expect(button.disabled).toBe(false);
    getSkillDetail.mockResolvedValue({ ...CUSTOM_PROFILE, approved: true });
    await userEvent.click(button);
    await waitFor(() =>
      expect(approveCustomSkill).toHaveBeenCalledWith(CUSTOM_ID),
    );
    await screen.findByTestId("skill-unapprove-btn");
  });
});

describe("SkillPlaza create and derive", () => {
  it("creates a skill from a blank form, blocking when methodology is empty", async () => {
    render(<SkillPlaza />);
    await screen.findByTestId("skill-groups");
    await userEvent.click(screen.getByTestId("create-skill-btn"));
    expect(screen.getByTestId("skill-form")).toBeInTheDocument();

    await userEvent.type(screen.getByTestId("skill-form-name"), "资金流背离雷达");
    expect(screen.getByTestId("skill-form-submit")).toBeDisabled();
    await userEvent.type(
      screen.getByTestId("skill-form-methodology"),
      "汇总资金净流入并识别价量背离。",
    );
    expect(screen.getByTestId("skill-form-submit")).not.toBeDisabled();
    await userEvent.click(screen.getByTestId("skill-form-submit"));

    await waitFor(() => expect(createCustomSkill).toHaveBeenCalledTimes(1));
    expect(createCustomSkill.mock.calls[0][0]).toMatchObject({
      name: "资金流背离雷达",
      methodology: "汇总资金净流入并识别价量背离。",
    });
  });

  it("derives a new skill from an approved template, never copying the name", async () => {
    render(<SkillPlaza />);
    await openSkill(`skill-card-${ASSEMBLED_NAME}`);
    await userEvent.click(screen.getByTestId("skill-derive-btn"));

    const picker = screen.getByTestId("skill-form-template") as HTMLSelectElement;
    // Only approved skills are template-eligible.
    const optionValues = Array.from(picker.options).map((o) => o.value);
    expect(optionValues).toContain(`assembled:${ASSEMBLED_NAME}`);
    expect(optionValues).not.toContain(CUSTOM_ID);

    // Derive entry pre-selects the current skill as template.
    await waitFor(() =>
      expect(screen.getByTestId("skill-form-methodology")).toHaveValue(
        ASSEMBLED_PROFILE.methodology,
      ),
    );
    expect(screen.getByTestId("skill-form-name")).toHaveValue("");

    await userEvent.type(screen.getByTestId("skill-form-name"), "缠论分析·A股增强版");
    await userEvent.click(screen.getByTestId("skill-form-submit"));
    await waitFor(() => expect(createCustomSkill).toHaveBeenCalledTimes(1));
    expect(createCustomSkill.mock.calls[0][0]).toMatchObject({
      name: "缠论分析·A股增强版",
      template_ref: `assembled:${ASSEMBLED_NAME}`,
    });
  });

  it("edits a custom skill and keeps the profile open after save", async () => {
    render(<SkillPlaza />);
    await openSkill(`skill-card-${CUSTOM_NAME}`);
    await userEvent.click(screen.getByTestId("skill-edit-btn"));
    await userEvent.clear(screen.getByTestId("skill-form-purpose"));
    await userEvent.type(
      screen.getByTestId("skill-form-purpose"),
      "更新后的用途简介",
    );
    await userEvent.click(screen.getByTestId("skill-form-submit"));
    await waitFor(() => expect(updateCustomSkill).toHaveBeenCalledTimes(1));
    expect(updateCustomSkill.mock.calls[0][0]).toBe(CUSTOM_ID);
    expect(updateCustomSkill.mock.calls[0][1]).toMatchObject({
      purpose: "更新后的用途简介",
    });
  });

  it("deletes a custom skill after confirmation", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<SkillPlaza />);
    await openSkill(`skill-card-${CUSTOM_NAME}`);
    await userEvent.click(screen.getByTestId("skill-delete-btn"));
    expect(confirmSpy).toHaveBeenCalled();
    await waitFor(() => expect(deleteCustomSkill).toHaveBeenCalledWith(CUSTOM_ID));
    await screen.findByTestId("skill-groups");
    confirmSpy.mockRestore();
  });
});

describe("SkillPlaza trial run and history", () => {
  it("launches a standalone trial and opens the run view", async () => {
    render(<SkillPlaza />);
    await openSkill(`skill-card-${CUSTOM_NAME}`);
    await userEvent.click(screen.getByTestId("skill-tab-run"));
    await screen.findByTestId("skill-run-panel");
    expect(screen.getByTestId("skill-run-launch")).toBeDisabled();
    await userEvent.type(screen.getByTestId("skill-run-target"), "600519.SH");
    await userEvent.type(
      screen.getByTestId("skill-run-question"),
      "波动率处于什么分位？",
    );
    await userEvent.click(screen.getByTestId("skill-run-launch"));
    await waitFor(() => expect(createSkillTrial).toHaveBeenCalledTimes(1));
    expect(createSkillTrial.mock.calls[0][0]).toEqual({
      skill_name: CUSTOM_NAME,
      target: "600519.SH",
      question: "波动率处于什么分位？",
    });
    await waitFor(() =>
      expect(screen.getByTestId("run-view")).toBeInTheDocument(),
    );
  });

  it("loads per-skill history filtered by skill name", async () => {
    render(<SkillPlaza />);
    await openSkill(`skill-card-${CUSTOM_NAME}`);
    await userEvent.click(screen.getByTestId("skill-tab-history"));
    await waitFor(() => expect(listSkillTrials).toHaveBeenCalled());
    expect(
      listSkillTrials.mock.calls.some(
        (call) => call[0]?.skillName === CUSTOM_NAME,
      ),
    ).toBe(true);
    // Non-admins never get the all-people scope toggle.
    expect(screen.queryByTestId("skill-history-scope-all")).not.toBeInTheDocument();
  });
});

describe("SkillPlaza my evaluations", () => {
  it("loads cross-skill trials and filters by skill/target/date", async () => {
    listSkillTrials.mockResolvedValue([
      {
        id: "trial-1",
        preset_name: `skill:${ASSEMBLED_NAME}`,
        status: "completed",
        created_at: "2026-09-28T10:20:00+00:00",
        final_report_excerpt: "中枢上移",
        kind: "skill_trial",
        trial_skill: ASSEMBLED_NAME,
        research_target: "600519.SH",
        research_question: "中枢与买卖点",
      },
      {
        id: "trial-2",
        preset_name: `skill:${CUSTOM_NAME}`,
        status: "failed",
        created_at: "2026-09-26T15:02:00+00:00",
        final_report_excerpt: "",
        kind: "skill_trial",
        trial_skill: CUSTOM_NAME,
        research_target: "000001.SZ",
        research_question: "曲面偏斜",
      },
    ]);
    render(<SkillPlaza />);
    await screen.findByTestId("skill-groups");
    await userEvent.click(screen.getByTestId("plaza-tab-evaluations"));
    await screen.findByTestId("my-evaluations");
    expect(screen.getByTestId("open-eval-trial-1")).toBeInTheDocument();
    expect(screen.getByTestId("open-eval-trial-2")).toBeInTheDocument();

    await userEvent.type(screen.getByTestId("eval-filter-skill"), "缠论");
    expect(screen.queryByTestId("open-eval-trial-2")).not.toBeInTheDocument();
    expect(screen.getByTestId("open-eval-trial-1")).toBeInTheDocument();

    await userEvent.clear(screen.getByTestId("eval-filter-skill"));
    await userEvent.type(screen.getByTestId("eval-filter-target"), "000001");
    expect(screen.queryByTestId("open-eval-trial-1")).not.toBeInTheDocument();
    expect(screen.getByTestId("open-eval-trial-2")).toBeInTheDocument();

    await userEvent.click(screen.getByTestId("eval-clear"));
    expect(screen.getByTestId("open-eval-trial-1")).toBeInTheDocument();
    expect(screen.getByTestId("open-eval-trial-2")).toBeInTheDocument();
  });

  it("returns from a run view back to the evaluations list (no blank page)", async () => {
    listSkillTrials.mockResolvedValue([
      {
        id: "trial-1",
        preset_name: `skill:${ASSEMBLED_NAME}`,
        status: "completed",
        created_at: "2026-09-28T10:20:00+00:00",
        final_report_excerpt: "中枢上移",
        kind: "skill_trial",
        trial_skill: ASSEMBLED_NAME,
        research_target: "600519.SH",
        research_question: "中枢与买卖点",
      },
      {
        id: "trial-2",
        preset_name: `skill:${CUSTOM_NAME}`,
        status: "failed",
        created_at: "2026-09-26T15:02:00+00:00",
        final_report_excerpt: "",
        kind: "skill_trial",
        trial_skill: CUSTOM_NAME,
        research_target: "000001.SZ",
        research_question: "曲面偏斜",
      },
    ]);
    render(<SkillPlaza />);
    await screen.findByTestId("skill-groups");
    await userEvent.click(screen.getByTestId("plaza-tab-evaluations"));
    await screen.findByTestId("my-evaluations");

    await userEvent.click(screen.getByTestId("open-eval-trial-1"));
    await screen.findByTestId("run-view");

    await userEvent.click(screen.getByTestId("run-back-btn"));
    await screen.findByTestId("my-evaluations");
    // List rows are rendered again rather than an empty detail shell.
    expect(screen.getByTestId("open-eval-trial-1")).toBeInTheDocument();
    expect(screen.getByTestId("open-eval-trial-2")).toBeInTheDocument();
  });
});

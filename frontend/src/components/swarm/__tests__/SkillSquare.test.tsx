import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SkillSquare } from "../SkillSquare";

const getSkillCatalog = vi.fn();
const getSkillCapabilities = vi.fn();
const listSkillTrials = vi.fn();
const createSkillTrial = vi.fn();
const importSkillPackage = vi.fn();
const syncSkills = vi.fn();

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: {
      getSkillCatalog: (...args: unknown[]) => getSkillCatalog(...args),
      getSkillCapabilities: (...args: unknown[]) => getSkillCapabilities(...args),
      listSkillTrials: (...args: unknown[]) => listSkillTrials(...args),
      createSkillTrial: (...args: unknown[]) => createSkillTrial(...args),
      importSkillPackage: (...args: unknown[]) => importSkillPackage(...args),
      syncSkills: (...args: unknown[]) => syncSkills(...args),
    },
  };
});

beforeEach(() => {
  vi.clearAllMocks();
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
        description: "community recipes",
        category: "other",
        source: "user",
        approved: false,
      },
    ],
  });
  listSkillTrials.mockResolvedValue([]);
  createSkillTrial.mockResolvedValue({
    id: "run-trial-9",
    status: "pending",
    kind: "skill_trial",
    trial_skill: "behavioral-finance",
  });
});

describe("SkillSquare", () => {
  it("renders the assembled catalog with approval/source badges", async () => {
    getSkillCapabilities.mockResolvedValue({
      admin_enabled: false,
      sync_source_configured: false,
    });
    render(<SkillSquare onOpenRun={vi.fn()} />);

    await screen.findByTestId("skill-card-behavioral-finance");
    expect(screen.getByTestId("skill-card-cookbook")).toBeInTheDocument();
    expect(screen.getAllByText("Approved").length).toBeGreaterThan(0);
    expect(screen.getByText("imported")).toBeInTheDocument();
    expect(screen.queryByTestId("skill-admin-zone")).not.toBeInTheDocument();
  });

  it("launches a single-skill trial and opens the run", async () => {
    const onOpenRun = vi.fn();
    getSkillCapabilities.mockResolvedValue({
      admin_enabled: false,
      sync_source_configured: false,
    });
    render(<SkillSquare onOpenRun={onOpenRun} />);

    await screen.findByTestId("skill-card-behavioral-finance");
    await userEvent.click(screen.getByTestId("skill-trial-set-cookbook"));
    await userEvent.type(screen.getByTestId("trial-target-input"), "600519.SH");
    await userEvent.type(screen.getByTestId("trial-question-input"), "适合做多吗");
    await userEvent.click(screen.getByTestId("trial-launch-btn"));

    await waitFor(() => expect(createSkillTrial).toHaveBeenCalledTimes(1));
    expect(createSkillTrial.mock.calls[0][0]).toEqual({
      skill_name: "cookbook",
      target: "600519.SH",
      question: "适合做多吗",
    });
    await waitFor(() => expect(onOpenRun).toHaveBeenCalledWith("run-trial-9"));
  });

  it("exposes import and one-click sync only when admin is enabled", async () => {
    getSkillCapabilities.mockResolvedValue({
      admin_enabled: true,
      sync_source_configured: true,
    });
    importSkillPackage.mockResolvedValue({
      installed: [{ name: "macro-pack", slug: "macro-pack" }],
      rejected: [],
    });
    syncSkills.mockResolvedValue({
      added: ["macro-pack"],
      updated: [],
      removed: ["retired-pack"],
      rejected: [{ package: "bad-pack", reasons: ["not finance related"] }],
    });

    render(<SkillSquare onOpenRun={vi.fn()} />);
    const zone = await screen.findByTestId("skill-admin-zone");

    const file = new File(["PK\u0003\u0004"], "macro-pack.zip", {
      type: "application/zip",
    });
    await userEvent.upload(screen.getByTestId("skill-import-file"), file);
    await userEvent.click(screen.getByTestId("skill-import-btn"));
    await waitFor(() => expect(importSkillPackage).toHaveBeenCalledTimes(1));
    expect(screen.getByTestId("skill-admin-message")).toHaveTextContent("1");

    await userEvent.click(screen.getByTestId("skill-sync-btn"));
    await waitFor(() => expect(syncSkills).toHaveBeenCalledTimes(1));
    expect(zone).toHaveTextContent("Added: 1");
    expect(zone).toHaveTextContent("Removed: 1");
    expect(zone).toHaveTextContent("Rejected: 1");
  });
});

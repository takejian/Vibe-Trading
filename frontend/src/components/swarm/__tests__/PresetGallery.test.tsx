import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { PresetGallery } from "../PresetGallery";

const PRESETS = [
  {
    name: "investment_committee",
    title: "Investment Committee",
    description: "Bull vs bear.",
    agent_count: 4,
    variables: [],
    source: "bundled" as const,
  },
];

describe("PresetGallery", () => {
  it("shows the empty state for personal teams before any team is saved", () => {
    render(
      <PresetGallery
        presets={PRESETS}
        loading={false}
        error=""
        teams={[]}
        onSelect={vi.fn()}
        onSelectTeam={vi.fn()}
      />,
    );

    expect(screen.getByTestId("custom-team-gallery")).toBeInTheDocument();
    expect(screen.getByTestId("custom-team-empty")).toBeInTheDocument();
    expect(screen.getByTestId("preset-card-investment_committee")).toBeInTheDocument();
  });

  it("renders saved teams in a separate section and opens a team on click", async () => {
    const onSelectTeam = vi.fn();
    render(
      <PresetGallery
        presets={PRESETS}
        loading={false}
        error=""
        teams={[
          {
            id: "team-1",
            name: "My Macro Team",
            description: "macro scenarios",
            source_preset: "investment_committee",
            role_count: 3,
            created_at: "2026-09-25T00:00:00+00:00",
            updated_at: "2026-09-25T00:00:00+00:00",
          },
        ]}
        onSelect={vi.fn()}
        onSelectTeam={onSelectTeam}
      />,
    );

    const card = screen.getByTestId("custom-team-card-team-1");
    expect(card).toBeInTheDocument();
    expect(screen.queryByTestId("custom-team-empty")).not.toBeInTheDocument();
    expect(screen.getByText("3 roles")).toBeInTheDocument();

    await userEvent.click(card);
    expect(onSelectTeam).toHaveBeenCalledWith("team-1");
  });

  it("still opens built-in presets through the preset callback", async () => {
    const onSelect = vi.fn();
    render(
      <PresetGallery
        presets={PRESETS}
        loading={false}
        error=""
        teams={[]}
        onSelect={onSelect}
        onSelectTeam={vi.fn()}
      />,
    );

    await userEvent.click(screen.getByTestId("preset-card-investment_committee"));
    expect(onSelect).toHaveBeenCalledWith("investment_committee");
  });
});

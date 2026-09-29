import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { SaveTeamDialog, TEAM_DESCRIPTION_MAX } from "../SaveTeamDialog";

function renderDialog(overrides: Record<string, unknown> = {}) {
  const onSave = vi.fn();
  const onClose = vi.fn();
  render(
    <SaveTeamDialog
      open
      mode="create"
      onSave={onSave}
      onClose={onClose}
      saving={false}
      error=""
      {...overrides}
    />,
  );
  return { onSave, onClose };
}

describe("SaveTeamDialog", () => {
  it("renders nothing while closed", () => {
    render(
      <SaveTeamDialog open={false} mode="create" onSave={vi.fn()} onClose={vi.fn()} />,
    );
    expect(screen.queryByTestId("save-team-dialog")).not.toBeInTheDocument();
  });

  it("blocks submit for an empty team name and trims on save", async () => {
    const { onSave } = renderDialog();
    const confirm = screen.getByTestId("team-save-confirm");
    expect(confirm).toBeDisabled();

    await userEvent.type(screen.getByTestId("team-name-input"), "  Macro Team  ");
    expect(confirm).toBeEnabled();
    await userEvent.click(confirm);
    expect(onSave).toHaveBeenCalledWith("Macro Team", "");
  });

  it("shows update-mode labels and surfaces backend save errors", () => {
    renderDialog({ mode: "update", error: "Team name already exists" });
    expect(screen.getByText("Update my team")).toBeInTheDocument();
    expect(screen.getByTestId("team-save-confirm")).toHaveTextContent("Update in place");
    expect(screen.getByTestId("team-save-error")).toHaveTextContent(
      "Team name already exists",
    );
  });

  it("blocks descriptions longer than the limit", async () => {
    renderDialog();
    await userEvent.type(screen.getByTestId("team-name-input"), "T");
    const description = screen.getByTestId("team-description-input");
    // Bypass the browser maxLength guard to drive the prop-level validation.
    (description as HTMLTextAreaElement).removeAttribute("maxlength");
    await userEvent.type(description, "x".repeat(TEAM_DESCRIPTION_MAX + 1));
    expect(screen.getByTestId("team-save-confirm")).toBeDisabled();
    expect(
      screen.getByText(`Description must be at most ${TEAM_DESCRIPTION_MAX} characters`),
    ).toBeInTheDocument();
  });

  it("closes via the overlay and cancel button", async () => {
    const { onClose } = renderDialog();
    await userEvent.click(screen.getByText("Cancel"));
    expect(onClose).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByTestId("save-team-dialog"));
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MacroAllocationPlan } from "../MacroAllocationPlan";
import type { SynthesisAllocationDetail } from "@/lib/api";

function detail(over: Partial<SynthesisAllocationDetail>): SynthesisAllocationDetail {
  return {
    category: "cash",
    asset_group: "cash",
    rating: 0,
    raw_score: 0,
    weight_mid: 0.1,
    weight_low: 0.07,
    weight_high: 0.13,
    vehicle: "货币基金",
    rationale: "",
    trigger: "",
    ...over,
  };
}

describe("MacroAllocationPlan", () => {
  it("按分组渲染评级、权重区间、触发条件与工具", () => {
    const details = [
      detail({
        category: "precious_metal",
        asset_group: "commodity",
        rating: 1,
        weight_mid: 0.06,
        weight_low: 0.04,
        weight_high: 0.08,
        rationale: "央行购金",
        trigger: "实际利率转正转中性",
        vehicle: "518880 黄金ETF",
      }),
      detail(),
    ];
    render(
      <MacroAllocationPlan details={details} posture="balanced" riskBudget={0.56} />,
    );
    expect(screen.getByTestId("macro-syn-allocation-plan")).toBeInTheDocument();
    expect(screen.getByTestId("macro-syn-asset-precious_metal")).toHaveTextContent(
      "518880 黄金ETF",
    );
    expect(screen.getByText("4.0%~8.0%")).toBeInTheDocument();
    expect(screen.getByText(/央行购金/)).toBeInTheDocument();
    expect(screen.getByText(/实际利率转正转中性/)).toBeInTheDocument();
    expect(screen.getByTestId("macro-syn-posture")).toHaveTextContent(
      /平衡|Balanced/,
    );
  });

  it("空数据不渲染", () => {
    const { container } = render(
      <MacroAllocationPlan details={[]} posture={null} riskBudget={null} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});

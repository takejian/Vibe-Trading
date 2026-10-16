import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { JapanMirrorTab } from "../JapanMirrorTab";
import { MIRROR_PHASES } from "../japanMirrorData";

const setOption = vi.fn();
const resize = vi.fn();
const dispose = vi.fn();

vi.mock("@/lib/echarts", () => ({
  echarts: {
    init: () => ({ setOption, resize, dispose }),
  },
}));

describe("JapanMirrorTab", () => {
  it("渲染导语、框架与七个阶段", () => {
    render(<JapanMirrorTab />);
    expect(screen.getByTestId("japan-mirror-tab")).toBeInTheDocument();
    expect(screen.getByTestId("japan-mirror-charts")).toBeInTheDocument();
    expect(screen.getByText(/1991 ↔ 2021/)).toBeInTheDocument();
    expect(screen.getAllByText(/野口悠纪雄/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/辜朝明/).length).toBeGreaterThan(0);
    for (const phase of MIRROR_PHASES) {
      expect(screen.getByTestId(`japan-phase-${phase.id}`)).toBeInTheDocument();
    }
  });

  it("详写阶段包含逐年双轨要点，且对齐 1991↔2021", () => {
    render(<JapanMirrorTab />);
    expect(screen.getByTestId("japan-year-1991")).toBeInTheDocument();
    expect(screen.getByTestId("china-year-2021")).toBeInTheDocument();
    expect(screen.getAllByText(/三道红线/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/恒大财富爆雷/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/总量管制/).length).toBeGreaterThan(0);
  });

  it("中国 2026 年以后内容标注情景推演", () => {
    render(<JapanMirrorTab />);
    expect(screen.getAllByText("情景推演").length).toBeGreaterThan(0);
  });

  it("渲染十条镜鉴清单", () => {
    render(<JapanMirrorTab />);
    for (let i = 0; i < 10; i += 1) {
      expect(screen.getByTestId(`mirror-lesson-${i}`)).toBeInTheDocument();
    }
  });
});

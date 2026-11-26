import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { hours, month, percent } from "./format";
import { KpiTile } from "./kpi-tile";

describe("report formats", () => {
  it("shows hours, then days past two days, shares and months", () => {
    expect([hours(27.94), hours(50), hours(null)]).toEqual(["27.9 h", "2.1 d", "—"]);
    expect([percent(0.955), percent(null)]).toEqual(["96%", "—"]);
    expect([month("2026-11"), month("2025-12", true)]).toEqual(["Nov 26", "December 2025"]);
  });
});

describe("KpiTile", () => {
  const delta = (sign: number) => ({ text: sign > 0 ? "+1.5 h" : "−1.5 h", sign, versus: "same days last month" });

  it("marks a change that is bad for the KPI in the 'bad' colour, with an arrow and words", () => {
    render(<KpiTile label="Mean time to resolve" value="27.8 h" delta={delta(1)} goodWhen="down" />);
    const change = screen.getByText("+1.5 h", { exact: false });
    expect(change).toHaveClass("text-[var(--viz-bad)]");
    expect(change).toHaveTextContent("vs same days last month");
  });

  it("marks a change that is good for the KPI in the 'good' colour", () => {
    render(<KpiTile label="Mean time to resolve" value="27.8 h" delta={delta(-1)} goodWhen="down" />);
    expect(screen.getByText("−1.5 h", { exact: false })).toHaveClass("text-[var(--viz-good)]");
  });

  it("leaves a change neutral when neither direction is better", () => {
    render(<KpiTile label="Opened" value="135" delta={{ text: "−21%", sign: -1, versus: "last month" }} />);
    expect(screen.getByText("−21%", { exact: false })).toHaveClass("text-muted-foreground");
    expect(screen.getByText("135")).toBeInTheDocument();
  });
});

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Column, ReportTable } from "./report-table";

type Row = { application: string; opened: number; sla_met: number | null; hours: number | null };
const columns: Column<Row>[] = [
  { key: "application", label: "Application" },
  { key: "opened", label: "Opened" },
  { key: "sla_met", label: "SLA met", format: "percent" },
  { key: "hours", label: "Mean time to resolve", format: "hours" },
];
const rows: Row[] = [
  { application: "PayrollPro", opened: 1200, sla_met: 0.875, hours: 6.2 },
  { application: 'Order "Hub", EU', opened: 3, sla_met: null, hours: null },
];
const table = (data: Row[] = rows) =>
  render(<ReportTable title="Tickets by application" description="d" columns={columns} rows={data} file="tickets" empty="No tickets." />);

describe("ReportTable", () => {
  it("formats shares, hours and missing values", () => {
    table();
    const [payroll, order] = screen.getAllByRole("row").slice(1);
    expect(within(payroll).getAllByRole("cell").map((c) => c.textContent)).toEqual(["PayrollPro", (1200).toLocaleString(), "88%", "6.2 h"]);
    expect(within(order).getAllByRole("cell").map((c) => c.textContent)).toEqual(['Order "Hub", EU', "3", "—", "—"]);
  });

  it("shows the empty message and cannot download with no rows", () => {
    table([]);
    expect(screen.getByText("No tickets.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download CSV" })).toBeDisabled();
  });

  it("downloads the raw values as CSV, quoting commas and quotes", async () => {
    let blob: Blob | undefined;
    URL.createObjectURL = vi.fn((b: Blob) => ((blob = b), "blob:report"));
    URL.revokeObjectURL = vi.fn();
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      expect(this.download).toBe("tickets.csv");
    });
    table();
    await userEvent.click(screen.getByRole("button", { name: "Download CSV" }));
    expect(click).toHaveBeenCalledOnce();
    const text = await new Promise<string>((done) => {
      const reader = new FileReader(); // jsdom's Blob has no text()
      reader.onload = () => done(String(reader.result));
      reader.readAsText(blob!);
    });
    expect(text.split("\n")).toEqual([
      "Application,Opened,SLA met,Mean time to resolve",
      "PayrollPro,1200,0.875,6.2",
      '"Order ""Hub"", EU",3,,',
    ]);
  });
});

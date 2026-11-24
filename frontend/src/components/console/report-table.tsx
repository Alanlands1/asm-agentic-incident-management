"use client";

import { Download } from "lucide-react";
import { SectionHead } from "@/components/console/sync-parts";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

type Value = string | number | null;
export type Column<T> = {
  key: keyof T & string;
  label: string;
  /** How the value shows on screen; the CSV keeps the raw value. */
  format?: "percent" | "hours" | "number";
};

const show = (v: Value, format?: Column<never>["format"]) => {
  if (v === null || v === undefined) return "—";
  if (typeof v !== "number") return v;
  if (format === "percent") return `${Math.round(v * 100)}%`;
  if (format === "hours") return `${v.toLocaleString()} h`;
  return v.toLocaleString();
};

const cell = (v: Value) => (v === null || v === undefined ? "" : /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v));

/** A report table with a CSV download of exactly the rows shown. */
export function ReportTable<T extends object>({
  title,
  description,
  columns,
  rows,
  file,
  empty,
}: {
  title: string;
  description: string;
  columns: Column<T>[];
  rows: T[];
  file: string;
  empty: string;
}) {
  const download = () => {
    const csv = [columns.map((c) => cell(c.label)), ...rows.map((r) => columns.map((c) => cell(r[c.key] as Value)))].map((l) => l.join(",")).join("\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const a = Object.assign(document.createElement("a"), { href: url, download: `${file}.csv` });
    a.click();
    URL.revokeObjectURL(url);
  };
  return (
    <Card className="gap-0 py-0">
      <SectionHead title={title}>
        <Button size="sm" variant="secondary" disabled={rows.length === 0} onClick={download}>
          <Download />
          Download CSV
        </Button>
      </SectionHead>
      <p className="border-b border-border px-4 py-2 text-xs text-muted-foreground">{description}</p>
      {rows.length === 0 ? (
        <p className="px-4 py-6 text-[13px] text-muted-foreground">{empty}</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              {columns.map((c, i) => (
                <TableHead key={c.key} className={i === 0 ? "pl-4" : "text-right"}>
                  {c.label}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={String(r[columns[0].key])}>
                {columns.map((c, i) => (
                  <TableCell key={c.key} className={i === 0 ? "pl-4 font-medium" : "text-right tabular-nums"}>
                    {show(r[c.key] as Value, c.format)}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </Card>
  );
}

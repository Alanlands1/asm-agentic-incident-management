"use client";

import { useState } from "react";
import { BarChart3, Download, Table2 } from "lucide-react";
import { SectionHead } from "@/components/console/sync-parts";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Cell, downloadCsv } from "./format";

export interface ChartTable {
  columns: string[];
  rows: Cell[][];
  /** How a value shows in the table view; the CSV keeps the raw value. */
  format?: (value: Cell, column: number) => string;
}

/** A chart with its title, a one-line reading guide, a table view of the same numbers and a CSV of them. */
export function ChartCard({
  title,
  description,
  table,
  file,
  legend,
  children,
  className,
}: {
  title: string;
  description: string;
  table: ChartTable;
  file: string;
  legend?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  const [asTable, setAsTable] = useState(false);
  const show = (v: Cell, i: number) => (table.format ? table.format(v, i) : v === null ? "—" : String(v));
  return (
    <Card className={`gap-0 py-0 ${className ?? ""}`}>
      <SectionHead title={title}>
        <div className="flex items-center gap-1">
          <Button size="xs" variant="ghost" aria-pressed={asTable} onClick={() => setAsTable(!asTable)}>
            {asTable ? <BarChart3 /> : <Table2 />}
            {asTable ? "View as chart" : "View as table"}
          </Button>
          <Button size="xs" variant="ghost" disabled={table.rows.length === 0} onClick={() => downloadCsv(file, table.columns, table.rows)}>
            <Download />
            CSV
          </Button>
        </div>
      </SectionHead>
      <p className="px-4 pt-2 text-xs text-muted-foreground">{description}</p>
      {legend && !asTable && <div className="flex flex-wrap gap-x-4 gap-y-1 px-4 pt-2 text-xs text-muted-foreground">{legend}</div>}
      {asTable ? (
        <div className="max-h-80 overflow-auto px-2 py-2">
          <Table>
            <TableHeader>
              <TableRow>
                {table.columns.map((c, i) => (
                  <TableHead key={c} className={i === 0 ? "pl-2" : "text-right"}>
                    {c}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {table.rows.map((r) => (
                <TableRow key={String(r[0])}>
                  {r.map((v, i) => (
                    <TableCell key={table.columns[i]} className={i === 0 ? "pl-2 font-medium" : "text-right tabular-nums"}>
                      {show(v, i)}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      ) : (
        <div className="px-2 pt-2 pb-3">{children}</div>
      )}
    </Card>
  );
}

/** A legend entry: a short stroke for a line series, a square for a bar series; the name in text ink. */
export function LegendKey({ color, label, line, dashed }: { color: string; label: string; line?: boolean; dashed?: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        aria-hidden="true"
        className={line ? "h-0.5 w-4 rounded-full" : "size-2.5 rounded-[3px]"}
        style={dashed ? { borderTop: `2px dashed ${color}` } : { background: color }}
      />
      {label}
    </span>
  );
}

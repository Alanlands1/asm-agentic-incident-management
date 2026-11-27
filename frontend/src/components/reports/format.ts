/** Number and date formats shared by the service-performance tiles, charts, tables and CSVs. */

export type Cell = string | number | null;

/** 27.9 h; days past 48 h (3.4 d), where hours stop being easy to compare. */
export const hours = (h: number | null) => (h === null ? "—" : h >= 48 ? `${(h / 24).toFixed(1)} d` : `${h.toFixed(1)} h`);
export const percent = (share: number | null) => (share === null ? "—" : `${Math.round(share * 100)}%`);
export const count = (n: number | null) => (n === null ? "—" : n.toLocaleString());

/** "2026-11" -> "Nov 26" (short) or "November 2026" (long). */
export function month(key: string, long = false): string {
  const [y, m] = key.split("-").map(Number);
  const at = new Date(Date.UTC(y, m - 1, 1));
  return at.toLocaleDateString("en-GB", long ? { month: "long", year: "numeric", timeZone: "UTC" } : { month: "short", year: "2-digit", timeZone: "UTC" });
}

const csvCell = (v: Cell) => (v === null ? "" : /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v));

/** Saves the rows as a CSV file in the browser; raw values, not the formatted ones. */
export function downloadCsv(file: string, columns: string[], rows: Cell[][]) {
  const csv = [columns, ...rows].map((r) => r.map(csvCell).join(",")).join("\n");
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  Object.assign(document.createElement("a"), { href: url, download: `${file}.csv` }).click();
  URL.revokeObjectURL(url);
}

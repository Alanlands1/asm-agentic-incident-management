import { Storm } from "@/types/incident";

/** One row of a ticket list: a single ticket, or the tickets of one storm shown through one of them. */
export interface StormGroup<T> {
  item: T;
  /** The storm the ticket belongs to, if any. */
  storm: Storm | null;
  /** The storm's other tickets in the list, in the list's order. Empty for a single ticket. */
  others: T[];
}

/**
 * Tickets of one storm become one row, placed where the storm's first ticket was. It shows the main ticket when that
 * is in the list, else the first of them. Call it after filtering and sorting. With no storms the list is unchanged.
 */
export function stormGroups<T>(items: T[], idOf: (item: T) => string, storms: Storm[]): StormGroup<T>[] {
  const stormOf = new Map<string, Storm>();
  for (const s of storms) for (const id of s.ticket_ids) stormOf.set(id, s);
  const groups: StormGroup<T>[] = [];
  const byStorm = new Map<number, StormGroup<T>>();
  for (const item of items) {
    const storm = stormOf.get(idOf(item)) ?? null;
    const group = storm && byStorm.get(storm.id);
    if (group) {
      group.others.push(item);
      continue;
    }
    const first = { item, storm, others: [] };
    if (storm) byStorm.set(storm.id, first);
    groups.push(first);
  }
  for (const group of byStorm.values()) {
    const main = group.others.find((o) => idOf(o) === group.storm?.main_ticket_id);
    if (!main) continue;
    group.others = [group.item, ...group.others].filter((o) => o !== main);
    group.item = main;
  }
  return groups;
}

/** One table row: `storm` is set on the row that stands for two or more tickets; `child` is one of an opened storm's other tickets. */
export interface StormRow<T> {
  item: T;
  storm: Storm | null;
  /** How many tickets of the list the row stands for (1 for a single ticket). */
  tickets: number;
  child: boolean;
}

/** The groups as rows: one per group, and under a storm whose id is in `open`, its other tickets. */
export function stormRows<T>(groups: StormGroup<T>[], open: number[]): StormRow<T>[] {
  return groups.flatMap((g) => [
    { item: g.item, storm: g.others.length ? g.storm : null, tickets: g.others.length + 1, child: false },
    ...(g.storm && open.includes(g.storm.id) ? g.others.map((item) => ({ item, storm: null, tickets: 1, child: true })) : []),
  ]);
}

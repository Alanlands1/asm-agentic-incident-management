import { describe, expect, it } from "vitest";
import { stormGroups } from "@/lib/storm-rows";
import { Storm } from "@/types/incident";

const storm = (id: number, main: string, ids: string[]) => ({ id, main_ticket_id: main, ticket_ids: ids, ticket_count: ids.length }) as Storm;
const same = (id: string) => id;
const shape = (ids: string[], storms: Storm[]) => stormGroups(ids, same, storms).map((g) => [g.item, ...g.others].join("+"));

describe("stormGroups", () => {
  it("leaves the list as it was when there are no storms", () => {
    expect(shape(["A", "B", "C"], [])).toEqual(["A", "B", "C"]);
  });

  it("collapses a storm onto its main ticket, where the storm's first ticket was", () => {
    expect(shape(["A", "B", "C", "D", "E"], [storm(1, "D", ["B", "D", "E"])])).toEqual(["A", "D+B+E", "C"]);
  });

  it("uses the first ticket when the main ticket is not in the list", () => {
    expect(shape(["A", "B", "C"], [storm(1, "Z", ["B", "C", "Z"])])).toEqual(["A", "B+C"]);
  });

  it("keeps a storm's only listed ticket as a single row that still knows its storm", () => {
    const [a, b] = stormGroups(["A", "B"], same, [storm(7, "B", ["B", "Z"])]);
    expect([a.storm, b.storm?.id, b.others]).toEqual([null, 7, []]);
  });
});

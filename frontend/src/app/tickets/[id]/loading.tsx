/** The ticket id is only known at request time, so the page streams in behind this. */
export default function Loading() {
  return <p className="px-4 py-6 text-[13px] text-muted-foreground">Loading the ticket…</p>;
}

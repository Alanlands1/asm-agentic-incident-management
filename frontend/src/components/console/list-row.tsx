import { cn } from "cn";

interface ListRowProps {
  /** Leading cell: a number, priority chip or icon. */
  lead?: React.ReactNode;
  /** Mono key shown before the title (ticket id, rule id). */
  itemKey?: React.ReactNode;
  title: React.ReactNode;
  /** Line 2: 12px muted meta. */
  meta?: React.ReactNode;
  /** Fixed narrow column (status, time). Joins line 2 below 960px. */
  trailing?: React.ReactNode;
  actions?: React.ReactNode;
  className?: string;
}

/** Two-line list row that wraps and never scrolls sideways. Render inside <ul role="list">. */
export function ListRow({ lead, itemKey, title, meta, trailing, actions, className }: ListRowProps) {
  return (
    <li
      className={cn(
        "flex min-h-11 flex-col gap-2 border-b border-border px-4 py-2.5 last:border-b-0 sm:flex-row sm:items-center sm:gap-3",
        className
      )}
    >
      {lead && <div className="flex shrink-0 items-center">{lead}</div>}
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <div className="break-words text-[13px] font-medium text-foreground">
          {itemKey && <span className="mr-2 font-mono text-xs text-muted-foreground">{itemKey}</span>}
          {title}
        </div>
        {(meta || trailing) && (
          <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
            {meta}
            {trailing && <span className="min-[960px]:hidden">{trailing}</span>}
          </div>
        )}
      </div>
      {trailing && <div className="hidden shrink-0 text-right text-[13px] text-muted-foreground min-[960px]:block">{trailing}</div>}
      {actions && (
        <div className="flex shrink-0 flex-col gap-2 max-sm:[&>*]:h-11 max-sm:[&>*]:w-full sm:flex-row sm:items-center">{actions}</div>
      )}
    </li>
  );
}

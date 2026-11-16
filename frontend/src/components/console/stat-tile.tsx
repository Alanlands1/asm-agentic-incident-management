import Link from "next/link";
import { cn } from "cn";
import { CountUp } from "@/components/console/count-up";
import { Card } from "@/components/ui/card";

interface StatTileProps {
  label: React.ReactNode;
  value: React.ReactNode;
  /** Window or comparison, e.g. "last 7 days". Omit when the data has none. */
  window?: React.ReactNode;
  variant?: "primary" | "secondary";
  /** Small icon at the top right. */
  icon?: React.ComponentType<{ className?: string }>;
  /** Makes the whole tile a link. */
  href?: string;
  className?: string;
}

export function StatTile({ label, value, window, variant = "secondary", icon: Icon, href, className }: StatTileProps) {
  const tile = (
    <Card
      size="sm"
      className={cn(
        "min-h-32 gap-2.5 p-[18px] transition-[transform,box-shadow] duration-200 hover:-translate-y-0.5 hover:shadow-[0_10px_24px_rgba(25,29,56,0.14)]",
        variant === "primary" && "border-primary bg-primary text-primary-foreground",
        className
      )}
    >
      <span className={cn("flex items-center justify-between gap-2 font-mono text-[10.5px] font-medium uppercase tracking-[0.08em]", variant === "primary" ? "text-primary-foreground" : "text-muted-foreground")}>
        {label}
        {Icon && <Icon className="size-4 shrink-0" />}
      </span>
      <span
        className={cn(
          "font-bold tabular-nums leading-none",
          variant === "primary" ? "text-primary-foreground" : "text-foreground",
          "text-[40px]"
        )}
      >
        {typeof value === "number" ? <CountUp value={value} /> : value}
      </span>
      {window && <span className={cn("mt-auto text-xs", variant === "primary" ? "text-primary-foreground/80" : "text-muted-foreground")}>{window}</span>}
    </Card>
  );
  if (!href) return tile;
  return (
    <Link
      href={href}
      className="rounded-[20px] outline-none transition-colors duration-[80ms] focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background [&>*]:h-full"
    >
      {tile}
    </Link>
  );
}

import { cn } from "cn"

// A span, so it can sit inside a <p> or a table cell as well as a <div>.
function Skeleton({ className, ...props }: React.ComponentProps<"span">) {
  return (
    <span
      data-slot="skeleton"
      aria-hidden="true"
      className={cn("block rounded-md bg-selected motion-safe:animate-pulse", className)}
      {...props}
    />
  )
}

export { Skeleton }

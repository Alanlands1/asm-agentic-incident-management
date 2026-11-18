import { mergeProps } from "@base-ui/react/merge-props"
import { useRender } from "@base-ui/react/use-render"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "cn"

const badgeVariants = cva(
  "group/badge inline-flex h-[22px] w-fit shrink-0 items-center justify-center gap-1 overflow-hidden rounded-full border border-transparent px-2 text-xs font-medium whitespace-nowrap transition-colors duration-[80ms] focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background has-data-[icon=inline-end]:pr-1.5 has-data-[icon=inline-start]:pl-1.5 aria-invalid:border-destructive [&>svg]:pointer-events-none [&>svg]:size-3!",
  {
    variants: {
      variant: {
        default: "border-border-strong text-foreground [a]:hover:bg-accent",
        secondary: "bg-muted text-foreground [a]:hover:bg-selected",
        destructive: "border-critical/50 text-critical [a]:hover:bg-accent",
        outline: "border-border-strong text-foreground [a]:hover:bg-accent",
        ghost: "text-muted-foreground hover:bg-accent",
        link: "text-critical underline-offset-4 hover:underline",
        p1: "min-w-11 h-[26px] px-2 font-sans font-semibold tabular-nums border-primary bg-primary text-primary-foreground",
        p2: "min-w-11 h-[26px] px-2 font-sans font-semibold tabular-nums border-p2 bg-p2 text-p2-foreground",
        p3: "min-w-11 h-[26px] px-2 font-sans font-semibold tabular-nums border-p3 bg-p3 text-white",
        p4: "min-w-11 h-[26px] px-2 font-sans font-semibold tabular-nums border-p3 bg-p3 text-white",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

function Badge({
  className,
  variant = "default",
  render,
  ...props
}: useRender.ComponentProps<"span"> & VariantProps<typeof badgeVariants>) {
  return useRender({
    defaultTagName: "span",
    props: mergeProps<"span">(
      {
        className: cn(badgeVariants({ variant }), className),
      },
      props
    ),
    render,
    state: {
      slot: "badge",
      variant,
    },
  })
}

export { Badge, badgeVariants }

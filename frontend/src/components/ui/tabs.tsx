"use client"

import { Tabs as TabsPrimitive } from "@base-ui/react/tabs"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "cn"

function Tabs({
  className,
  orientation = "horizontal",
  ...props
}: TabsPrimitive.Root.Props) {
  return (
    <TabsPrimitive.Root
      data-slot="tabs"
      data-orientation={orientation}
      className={cn("group/tabs flex gap-4 data-horizontal:flex-col", className)}
      {...props}
    />
  )
}

const tabsListVariants = cva(
  "group/tabs-list relative inline-flex max-w-full items-center text-muted-foreground",
  {
    variants: {
      variant: {
        // Page sections: an underline that slides to the active tab (see TabsIndicator).
        line: "w-full flex-wrap gap-1 border-b border-border",
        // A small view switch inside a card.
        pill: "h-8 w-fit gap-0.5 rounded-lg bg-muted p-[3px]",
      },
    },
    defaultVariants: {
      variant: "line",
    },
  }
)

function TabsList({
  className,
  variant = "line",
  ...props
}: TabsPrimitive.List.Props & VariantProps<typeof tabsListVariants>) {
  return (
    <TabsPrimitive.List
      data-slot="tabs-list"
      data-variant={variant}
      className={cn(tabsListVariants({ variant }), className)}
      {...props}
    />
  )
}

function TabsTrigger({ className, ...props }: TabsPrimitive.Tab.Props) {
  return (
    <TabsPrimitive.Tab
      data-slot="tabs-trigger"
      className={cn(
        "relative z-10 inline-flex items-center gap-1.5 rounded-md border border-transparent text-[13px] font-medium whitespace-nowrap text-muted-foreground transition-colors duration-[80ms] outline-none select-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:pointer-events-none disabled:opacity-50 data-active:text-foreground [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
        "group-data-[variant=line]/tabs-list:h-9 group-data-[variant=line]/tabs-list:px-2.5 group-data-[variant=line]/tabs-list:hover:bg-accent",
        "group-data-[variant=pill]/tabs-list:h-full group-data-[variant=pill]/tabs-list:px-2.5 group-data-[variant=pill]/tabs-list:text-xs",
        className
      )}
      {...props}
    />
  )
}

/** The moving highlight: an accent underline for `line`, the raised chip for `pill`. Place it last inside TabsList. */
function TabsIndicator({ className, ...props }: TabsPrimitive.Indicator.Props) {
  return (
    <TabsPrimitive.Indicator
      data-slot="tabs-indicator"
      renderBeforeHydration
      className={cn(
        "absolute left-(--active-tab-left) w-(--active-tab-width) transition-[left,width,top] duration-200 ease-out motion-reduce:transition-none",
        "group-data-[variant=line]/tabs-list:bottom-[calc(var(--active-tab-bottom)-1px)] group-data-[variant=line]/tabs-list:h-0.5 group-data-[variant=line]/tabs-list:rounded-full group-data-[variant=line]/tabs-list:bg-primary",
        "group-data-[variant=pill]/tabs-list:top-(--active-tab-top) group-data-[variant=pill]/tabs-list:h-(--active-tab-height) group-data-[variant=pill]/tabs-list:rounded-md group-data-[variant=pill]/tabs-list:border group-data-[variant=pill]/tabs-list:border-border-strong group-data-[variant=pill]/tabs-list:bg-background",
        className
      )}
      {...props}
    />
  )
}

function TabsContent({ className, ...props }: TabsPrimitive.Panel.Props) {
  return (
    <TabsPrimitive.Panel
      data-slot="tabs-content"
      className={cn("flex flex-col gap-4 outline-none", className)}
      {...props}
    />
  )
}

export { Tabs, TabsList, TabsTrigger, TabsIndicator, TabsContent, tabsListVariants }

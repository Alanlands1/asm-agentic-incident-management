# Frontend Development Guidelines (for Agents & Developers)

## Overview
This is the Next.js frontend application for the AMS Agentic Incident Management system. It provides the UI for viewing ingested tickets, agent runs (Data Quality, Triage, Resolution), KB search, and incident analytics.

## Tech Stack
- **Framework**: Next.js 16+ (App Router)
- **Language**: TypeScript (strict mode)
- **Styling**: Tailwind CSS v4
- **Component Library**: [shadcn/ui](https://ui.shadcn.com/) (`src/components/ui/`)
- **Package Manager**: `npm`
- **Path Aliases**: `@/*` mapped to `src/*`

## Key Architecture & Conventions

### 1. UI Components (`shadcn/ui`)
- **DO NOT handwrite raw CSS or repetitive Tailwind classnames** for common UI elements (buttons, inputs, cards, dialogs, badges, tables, etc.).
- Always prefer and reuse existing components in [`src/components/ui/`](./src/components/ui/).
- Pre-installed primitives available:
  - `Button` (`@/components/ui/button`)
  - `Card`, `CardHeader`, `CardTitle`, `CardDescription`, `CardContent`, `CardFooter` (`@/components/ui/card`)
  - `Badge` (`@/components/ui/badge`)
  - `Table`, `TableHeader`, `TableBody`, `TableRow`, `TableHead`, `TableCell` (`@/components/ui/table`)
  - `Dialog`, `DialogTrigger`, `DialogContent`, etc. (`@/components/ui/dialog`)
  - `Input` (`@/components/ui/input`)
  - `Alert`, `AlertTitle`, `AlertDescription` (`@/components/ui/alert`)
- To add a new component, run inside `frontend/`:
  ```bash
  npx shadcn@latest add <component-name>
  ```
- Use `cn()` from `@/lib/utils` when conditionally merging Tailwind classes.

### 2. Directory Structure
```text
frontend/
├── src/
│   ├── app/                 # Next.js App Router (pages, layouts, route handlers)
│   │   ├── layout.tsx       # Root layout
│   │   ├── page.tsx         # Dashboard landing page
│   │   └── globals.css      # Global styles and Tailwind theme variables
│   ├── components/
│   │   ├── ui/              # shadcn/ui primitives (do not modify unless necessary)
│   │   └── ...              # Domain-specific feature components (e.g. TicketTable, AgentPipelineStatus)
│   └── lib/
│       ├── utils.ts         # Utility functions (cn helper)
│       └── api.ts           # Client for FastAPI backend endpoints (base: http://localhost:8000)
├── components.json          # shadcn configuration
├── package.json
└── tsconfig.json
```

### 3. Backend Integration
- Backend runs on FastAPI (default: `http://localhost:8000` or via Docker Compose).
- All API calls to the backend should be centralized under [`src/lib/api.ts`](./src/lib/api.ts) or dedicated hook wrappers.
- Use Next.js Server Components where appropriate for data fetching, or standard client-side fetching (`fetch`/React query) for real-time ticket stream and agent verdicts.

### 4. Code Quality & Verification
- Before finishing any frontend feature or task, always run verification:
  ```bash
  npm run build
  ```
  and ensure there are 0 TypeScript and lint errors.

---

## Related References
- For quick reference rules and component conventions, see [`frontend-guidelines.md`](./frontend-guidelines.md).

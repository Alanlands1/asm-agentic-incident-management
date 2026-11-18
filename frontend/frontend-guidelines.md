# Frontend Development Rules

When developing or modifying the Next.js application in `frontend/`:

## 1. UI Primitives & Styling
- **Do not manually recreate common UI elements with raw Tailwind classes**.
- Always use pre-configured **shadcn/ui** components located in `frontend/src/components/ui/` (`Button`, `Card`, `Badge`, `Table`, `Dialog`, `Input`, `Alert`, etc.).
- If an agent needs another shadcn component, install it via:
  ```bash
  cd frontend && npx shadcn@latest add <component-name>
  ```
- Use `cn()` from `@/lib/utils` when conditional classes are needed.

## 2. Structure & Conventions
- Maintain Next.js App Router conventions inside `frontend/src/app/`.
- Domain/feature components belong in `frontend/src/components/<feature>/`.
- API integration with the FastAPI backend (`http://localhost:8000`) should be structured in `frontend/src/lib/api.ts`.
- Use TypeScript with strict typing.

## 3. Verification
- Always verify frontend changes by running `npm run build` inside `frontend/` before concluding.

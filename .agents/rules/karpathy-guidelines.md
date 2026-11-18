---
trigger: always_on
description: Behavioral guidelines to reduce common LLM coding mistakes.
---

# Karpathy Guidelines

## 1. Think Before Coding
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First
- Minimum code that solves the problem. Nothing speculative.
- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.

## 3. Surgical Changes
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- Every changed line should trace directly to the request.

## 4. Goal-Driven Execution
- Define success criteria before running edits.
- For multi-step tasks, state a brief plan with verification steps.

## 5. Security & Sensitive Files
- Never read, inspect, display, or log `.env` files, production credentials, secrets, or private keys. Always consult `.env.example` or schemas/documentation instead.


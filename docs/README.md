# PKOS Project Documentation

Source-of-truth docs for PKOS (Personal Knowledge Operating System). Written on 2026-10-23 from a full read of the code, so they reflect what's actually built, not just what's planned.

| # | Document | Read it when you need… |
|---|---|---|
| 01 | [PRD](01_PRD.md) | the problem, users, goals, MVP scope, success metrics, risks |
| 02 | [SRS](02_SRS.md) | exact, testable requirements, roles, validations, errors, edge cases, DB schema |
| 03 | [Architecture](03_ARCHITECTURE.md) | stack, repo map, API table, data flows, config, deployment, tech debt |
| 04 | [UI/UX](04_UI_UX.md) | screens, states, components, accessibility, design tokens, copy |
| 05 | [Development Plan](05_DEVELOPMENT_PLAN.md) | milestones M0–M8, task IDs, dependencies, Definition of Done |
| 06 | [Desktop App Plan](06_DESKTOP_APP_PLAN.md) | the Windows app: bundled database and Ollama, packaging, PDF engine, audio/image notes |
| 07 | [Memory Plan](07_MEMORY_PLAN.md) | saved chats, short-term memory (history, follow-up rewriting, running summary), long-term memory (memories, past chats, suggestions) |
| 08 | [Phone Access Plan](08_PHONE_ACCESS_PLAN.md) | use PKOS from a phone through the laptop (hotspot or Wi-Fi), pairing, https, phone layout |
| - | [Using PKOS from your phone](PHONE_ACCESS.md) | user guide: hotspot, pairing, the certificate warning, troubleshooting, first-try checklist |

Status markers used throughout: ✅ implemented · 🟡 partial · ❌ not implemented.

**Keep them current:** when a task from the plan lands, flip the matching marker in the SRS and update the Architecture API/config tables if they changed.

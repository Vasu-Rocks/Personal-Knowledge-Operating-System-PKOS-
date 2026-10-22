# PKOS — UI/UX Specification

| Field | Value |
|---|---|
| Document | 04 — UI/UX |
| Version | 1.0 (current UI audited from `frontend/src`, 2026-10-23) |
| Related | [01_PRD](01_PRD.md) · [02_SRS](02_SRS.md) · [03_Architecture](03_ARCHITECTURE.md) · [05_Dev_Plan](05_DEVELOPMENT_PLAN.md) |

Each section describes **Current** (what the code does) and **Target** (what to build). Status: ✅ · 🟡 · ❌.

---

## 1. Design principles

1. **Evidence first.** Every answer is one click away from its sources. Citations are first-class UI, not footnotes.
2. **Calm, dark workspace.** A focused, low-glare "OS-like" shell; colour is reserved for meaning (blue = interactive/graph, green = source chunks, red = destructive/error).
3. **Honest status.** Never say "Synced" unless it is. Show progress, failures and limits plainly.
4. **Plain language over jargon.** The current copy leans on sci-fi terms ("Decrypting…", "Hashing Vectors", "Indexed Matrices"). Keep the aesthetic, but labels must say what is happening (see §11 copy table).
5. **Private by default, explicit when not.** Anything that sends data off-device is visually marked.
6. **Keyboard-complete.** Everything reachable and operable without a mouse.

## 2. Information architecture & navigation

PKOS is a single-page app with no router. Two top-level states and one modal:

```
App
├─ AuthView            (not authenticated)
│   ├─ Login mode
│   └─ Register mode
└─ Dashboard           (authenticated) — 3-pane shell
    ├─ Left:   Knowledge Vault  (VaultView)
    ├─ Center: Chat             ("Generative Inference Core")
    ├─ Right:  RAG X-Ray Inspector
    └─ Modal:  Inference Settings (SettingsView), opened from the Vault footer gear
```

Target additions (post-MVP): a "Graph" view toggle in the right pane (full-graph explorer), and a chat-history list. Keep the 3-pane shell; do not add a router until a second full-page view exists.

## 3. User journeys

### J1 — First run
1. Open `localhost:3000` → Login card.
2. Click "Initialize System" → Register mode (email, full name, username, password).
3. Submit → token stored → Dashboard opens with an empty vault and a system greeting.
4. **Target:** empty-state guidance in the chat ("Upload a document on the left to start asking questions") and in the vault.

### J2 — Add knowledge
1. Drag a file onto the upload zone or click to browse.
2. Spinner + "Hashing Vectors…" while the request runs (can take minutes for large PDFs).
3. On success the list refreshes. On failure: **nothing visible today** ❌.
4. **Target:** row appears immediately with status `Indexing… → Building graph… → Ready` (or `Graph failed` / `Upload failed` with reason).

### J3 — Ask and verify
1. Type a question → Enter.
2. User bubble appears right; an empty AI message appears and is auto-selected; "Synthesizing matrices…" indicator shows.
3. X-Ray fills with source cards and the entity map *before* tokens arrive; answer streams in.
4. Hover a `[Chunk N]` badge → card N highlights; click → scrolls to it. Hover/click a `[Graph Entity: X]` badge → node X highlights/zooms.
5. Click an older AI message → X-Ray shows its sources (✅) and **its graph** (🟡 today shows the latest graph).

### J4 — Remove knowledge
Hover a document → trash icon → immediate removal (optimistic). **Target:** confirm step (inline "Delete? Yes / No" or undo toast), since deletion is irreversible.

### J5 — Change model/provider
Gear in vault footer → modal → choose Local Ollama (model name) or Cloud (API key) → Save → closes after 1 s. **Target:** add Anthropic, show privacy warning for cloud, Escape/overlay click to close.

## 4. Screens

### 4.1 Auth screen ✅
- Full-viewport centred `glass-panel` card, 380 px wide, 40 px padding, radial blue glow background.
- Header: 64 px circular icon (Lock for login, KeyRound for register), title ("Welcome Back" / "Initialize Vault"), subtitle.
- Error banner (red tint, AlertCircle icon) above the form when `error` set.
- Fields (login): Identify (email or username), Passkey. Fields (register): Email, Full Name, Username, Passkey.
- Primary button full width; disabled with 0.7 opacity while loading.
- Mode toggle link below. Switching mode clears all fields and the error.

**Target fixes:** associate `<label htmlFor>` with inputs; make mode toggle a `<button>`; show password rules on register (≥ 8 chars, ≤ 71 bytes); `autoComplete` attributes (`username`, `current-password`, `new-password`, `email`, `name`).

### 4.2 Dashboard shell ✅
Flex row: `Vault (250 px default) | 4 px handle | Chat (flex, min 300 px) | 4 px handle | X-Ray (350 px default)`. Handles highlight blue on hover; drag clamps left 150–500, right 200–600.

### 4.3 Knowledge Vault (left pane)
| Region | Current | Target |
|---|---|---|
| Header | Database icon, "Knowledge Vault", one-line description | Keep; simplify description |
| Upload zone | Dashed box; drag-over turns blue; click opens picker (`.pdf,.txt,.md,.py,.js`); spinner while uploading; only first dropped file used | Text "Drop a file or click to browse · PDF, TXT, MD, PY, JS · max 50 MB"; support multiple files queued sequentially; client-side type/size pre-check |
| Roster | "Indexed Matrices (n)"; rows with file icon, name (ellipsis), green "Synced"; trash on hover | Real status badge per row (§6); trash always focusable (visible on hover **or** focus); `title` tooltip with full name and upload date |
| Footer | User name, @username, gear button; "Secure Disconnect" logout | Keep; add `aria-label`s |

### 4.4 Chat (center pane)
- Header bar 60 px: Terminal icon + title.
- Message list: 32 px padding, 24 px gap, max bubble width 85%.
  - **User:** right-aligned, blue background, white text, 12×16 padding, squared bottom-right corner.
  - **AI:** left-aligned, 32 px Bot avatar, transparent background, Markdown (GFM) with citation badges.
  - **System:** Terminal avatar, monospace muted text.
  - Non-selected AI/system messages at 0.7 opacity; selected at 1.0; click selects.
- Typing indicator: spinning Sparkles + italic "Synthesizing matrices…".
- Input dock: rounded pill form, chevron prompt glyph, autofocused input, Send button (disabled + 0.5 opacity when empty or busy). Enter submits.
- Auto-scroll to bottom on new content.

**Target:** Stop-generation button while streaming; copy-answer button on AI messages; "Retry" on error system messages; keep input enabled while streaming but block send.

### 4.5 RAG X-Ray Inspector (right pane)
- Header 60 px: green Activity icon, "RAG X-Ray Inspector".
- "Active Math Selection" box with `MSG_<id>` (developer-oriented; target: show the question text instead).
- **Interactive Entity Map** — 300 px tall `ForceGraph2D`; nodes auto-coloured by category; primary seed pinned at centre, prefixed "⭐", size 5 (others 1); curved directed links with arrows; hover a node → focus node blue, neighbours light blue, others dimmed; click → centre + zoom ×8; link tooltip `PREDICATE: description`. Empty state text when no links.
- **Extracted Vectors (n)** — source cards: header (filename, "PG n"), scrollable text (max 200 px), footer "HNSW Distance: 0.xxxx". Highlighted green when its citation is hovered.

**Target:** per-message graph; render seed-only graphs (nodes without links); show "Relevance" as `1 − distance` with a small bar in addition to raw distance; legend for node categories; button "Expand graph" (post-MVP).

### 4.6 Inference Settings modal 🟡
Fixed overlay (black 60% + 8 px blur), 450 px card: header with close X; segmented control (Local Ollama | Cloud LLM); Ollama → model text input; Cloud → OpenAI key (password input) + note "Stored exclusively on your device…"; footer Save button → "Saved" ✓ → auto-close after 1 s.

**Target:** three options (Ollama, OpenAI, Anthropic); amber warning panel when a cloud option is active: *"Your question and the matching passages from your documents will be sent to {provider}."*; Escape closes; focus trapped; "Test connection" button (calls `/health`-style check) post-MVP.

## 5. Components inventory

| Component | Where | Props / state | Notes |
|---|---|---|---|
| `AuthProvider` / `useAuth` | context | `token, user, isAuthenticated, login, register, logout, authFetch` | Target: `apiFetch` with base URL + 401 handling centralised |
| `AuthView` | screen | local form state, `isLogin`, `error`, `isLoading` | |
| `Dashboard` | screen | `messages, inputVal, isTyping, selectedMsgId, graphData, activeFocus, leftWidth, rightWidth` | Target: move `graphData` into each message; extract `ChatPane`, `XRayPane`, `useSSEQuery` hook |
| `VaultView` | pane | `documents, isHovering, isUploading, hoveredIndex, showSettings` | Target: `DocumentRow`, `UploadZone`, `StatusBadge` |
| `SettingsView` | modal | `provider, ollamaModel, openaiKey, anthropicKey, saved` | |
| `CitationBadge` | inline in Dashboard `MarkdownComponents.a` | type `chunk`\|`entity`, id | Rendered from `citation://chunk/N` / `citation://entity/Name` links created by `processCitations` regex |
| `SourceCard` | inline | `src, idx, highlighted` | DOM id `source-card-{n}` |
| Resize handle | `.resize-handle` | mouse only | Target: keyboard arrows when focused |

## 6. States

| Element | Loading | Empty | Error | Success |
|---|---|---|---|---|
| Auth submit | Button "Decrypting…" disabled | – | Red banner with server `detail` | Dashboard |
| Vault list | (none) → **Target:** 3 skeleton rows | "No documents yet — upload one above" ❌ | Inline banner "Couldn't load documents. Retry" ❌ | Rows |
| Upload | Spinner + label | – | **Target:** red row/toast with message (type, size, server) | Row with status |
| Document status (target) | `Indexing…` (spinner, grey) → `Building graph…` (spinner, blue) | – | `Graph failed` (amber, tooltip "Answers still use text search") / `Upload failed` (red) | `Ready` (green ✓) |
| Chat | Sparkles indicator; streaming text | System greeting; **Target:** add suggestion text | System message "[ERROR] …" ; stream `System Error:` tokens shown inline | Markdown answer |
| X-Ray graph | – | "No direct graph connections found…" | – | Force graph |
| X-Ray sources | – | "No relational vectors connected…" → **Target:** "No passages matched this question." | – | Source cards |
| Settings | – | – | – | "Saved ✓" |

## 7. Forms

| Form | Fields | Validation (client) | Validation (server) | Submit |
|---|---|---|---|---|
| Login | identifier (text), password | required | 401 generic | Enter / button |
| Register | email (`type=email`), name, username, password | required; **target:** username pattern, password ≥ 8 | see SRS FR-AUTH-03…09 | Enter / button |
| Upload | file | `accept` list; **target:** ≤ 50 MB pre-check | ext, size | on select / drop |
| Chat | query | non-empty; **target:** max 1,000 chars with counter at > 900 | 1–1,000 | Enter |
| Settings | provider, model / key | none | – | Save |

Errors appear next to the form (banner) and are announced via `role="alert"`.

## 8. Interactions & motion
- Buttons: lift −1 px on hover, +1 px on press (`transform`), 150 ms ease (`--transition-fast`).
- Citation badge: scale 1.05 + stronger tint on hover; 200 ms.
- Source card highlight: 300 ms background/border transition.
- Graph: click node → `centerAt(…, 1000 ms)` + `zoom(8, 2000 ms)`.
- Spinner: 1 s linear rotation (`.loader`).
- **Target:** honour `prefers-reduced-motion` (disable lift/scale, instant scroll, no zoom animation).

## 9. Responsive behaviour
Current: desktop-only; `body` has `overflow:hidden` and fixed 100vw/100vh; below ~850 px the panes overflow.

Target breakpoints:
| Width | Layout |
|---|---|
| ≥ 1200 px | 3 panes as today |
| 900–1199 px | Vault 220 px; X-Ray collapses to a toggleable overlay drawer (button in chat header "Evidence") |
| < 900 px | Single column: chat full width; Vault and X-Ray become slide-over drawers from left/right; upload via button in chat header |

Minimum supported: 360 px wide. Auth card becomes `width: min(380px, 100% - 32px)`.

## 10. Accessibility (target WCAG 2.1 AA)

| Issue found in code | Fix |
|---|---|
| Global `outline: none` on inputs/buttons removes focus indicators | Add `:focus-visible { outline: 2px solid var(--accent-blue); outline-offset: 2px; }` |
| Labels not linked to inputs | `htmlFor` / `id` pairs |
| Mode toggle and resize handles are `span`/`div` with mouse handlers | Use `<button>`; handles get `role="separator"`, `aria-orientation="vertical"`, `tabIndex=0`, arrow-key resizing |
| Icon-only buttons (gear, trash, close, send) without names | `aria-label` ("Settings", "Delete {filename}", "Close", "Send") |
| Delete only visible on mouse hover | Show on `:focus-within` too |
| Streaming answer not announced | Wrap AI message list in `aria-live="polite"` (announce on completion, not per token) |
| Modal lacks dialog semantics | `role="dialog" aria-modal="true" aria-labelledby`, focus trap, Escape to close, return focus to gear |
| Citation badges are `span` with onClick | Render as `<button>` |
| Colour-only status | Pair every status colour with icon + text |
| Contrast of `--text-muted` (hsl 215 15% 50%) on `--bg-core` is borderline for 11–12 px text | Verify ≥ 4.5:1; raise lightness to ~60% if it fails |
| Graph is canvas-only | Provide a text list of entities/relations under the graph (collapsible) |

## 11. Visual design system (from `src/index.css`)

### 11.1 Colour tokens
| Token | Value | Use |
|---|---|---|
| `--bg-core` | `hsl(222 47% 9%)` | App background |
| `--bg-surface` | `hsl(220 42% 14%)` | Hovered rows, raised surfaces |
| `--bg-surface-hover` | `hsl(220 42% 18%)` | Hover on surfaces |
| `--glass-bg` | `rgba(23,27,44,.6)` + 16 px blur | Cards, modal |
| `--glass-border` | `rgba(255,255,255,.08)` | Card borders |
| `--pane-border` | `1px solid rgba(255,255,255,.05)` | Pane dividers |
| `--accent-blue` | `hsl(217 91% 60%)` | Primary actions, links, entity citations |
| `--accent-glow` | `hsla(217 91% 60% / .15)` | Accent backgrounds |
| `--text-primary` | `hsl(0 0% 98%)` | Body text |
| `--text-secondary` | `hsl(215 20% 65%)` | Secondary text |
| `--text-muted` | `hsl(215 15% 50%)` | Hints, metadata |
| Semantic (inline today) | green `#10b981`, red `#ef4444`, light blue `#93c5fd` | Chunk citations/success, errors/delete, graph neighbours |

**Target:** promote semantic colours to tokens: `--success #10b981`, `--danger #ef4444`, `--warning #f59e0b` (for cloud warning, graph failed), `--accent-soft #93c5fd`. Theme is dark-only; a light theme is out of scope for MVP.

### 11.2 Typography
- Family: **Inter** (400/500/600/700 via Google Fonts), fallback system UI. Monospace: Consolas.
- Scale in use: 11 px (labels, metadata, uppercase + 1 px tracking), 12 px, 13 px (secondary UI), 14 px (body/inputs), 14.5 px (AI markdown), 15 px (chat input), 16 px (pane titles), 24 px (auth title). Line-height 1.4–1.6.
- **Target:** consolidate to tokens `--fs-xs 11`, `--fs-sm 13`, `--fs-md 14`, `--fs-lg 16`, `--fs-xl 24`.

> Note: loading Inter from Google Fonts is a network call from the browser; for strict local-first, self-host the font files.

### 11.3 Spacing, radius, elevation
- Spacing in use follows a 4 px grid: 4, 8, 12, 16, 20, 24, 32, 40. Target tokens `--sp-1…--sp-10` = 4…40.
- Radius: `--radius-sm 6px` (inputs, buttons), `--radius-md 12px` (cards), `--radius-lg 16px` (auth card, modal, chat input).
- Elevation: `--glass-shadow 0 8px 32px rgba(0,0,0,.37)`; modal `0 25px 50px -12px rgba(0,0,0,.5)`.
- Motion: `--transition-fast 150ms cubic-bezier(.4,0,.2,1)`, `--transition-smooth 250ms cubic-bezier(.16,1,.3,1)`.

### 11.4 Iconography
lucide-react, 14–20 px in UI, 28 px in hero spots, stroke default.

## 12. Copy guidelines

| Current | Target |
|---|---|
| "Decrypting…" (login loading) | "Signing in…" |
| "Create Keys" / "Access System" | "Create account" / "Sign in" |
| "Passkey" | "Password" (avoid confusion with WebAuthn passkeys) |
| "Hashing Vectors…" | "Indexing…" |
| "Indexed Matrices (n)" | "Documents (n)" |
| "Synced" (always) | Real status (§6) |
| "Synthesizing matrices…" | "Thinking…" |
| "Query the unified database…" | "Ask about your documents…" |
| "Extracted Vectors (n)" | "Sources (n)" |
| "HNSW Distance" | "Relevance" (+ distance in tooltip) |
| "Secure Disconnect" | "Log out" |
| "[ERROR] Downstream inference engine stream connection failed." | "Couldn't reach the server. Check that the backend is running, then try again." |

Tone: short, plain, no blame. The "OS" flavour can live in titles and visuals, not in instructions or errors.

## 13. Implementation notes
- Styles are mostly inline objects. When touching a component, move repeated styles into classes in `index.css` using the tokens above; don't introduce a CSS framework for MVP.
- Keep `react-markdown` without `rehype-raw` (prevents HTML injection from model output).
- Citation parsing relies on the regex in `processCitations`; if the prompt's citation format changes, update both together.
- Set `<title>` in `index.html` to "PKOS".

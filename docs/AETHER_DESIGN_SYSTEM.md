# Aether Design System Proposal

**Status:** Implemented in the chat workspace. The empty chat view now uses a
centered greeting, compact prompt shortcuts, and a wide integrated composer;
the agent execution rail appears when a conversation is active. Memory and
authentication views retain their established structure.

## Product direction

**Dark Intelligent Workspace** — a conversation-first, data-aware workspace
where agent execution is visible as real operational state. The chat is the
primary work surface; a compact execution rail explains the run and its
orchestrator-to-worker routing. Retain the established dark charcoal, muted
teal, and system sans-serif language.

The reference synthesis combines **Darkmoon's orchestrator-to-specialist
explanation** with **Bluejack's summary-to-detail dashboard hierarchy** and
**SmithySoft's explicit navigation and category grouping**. Darkmoon guides the
agent mental model; it does not prescribe Aether's page layout, exact colors, or
marketing imagery. Bluejack and SmithySoft inform information organization, not
their unrelated business content or palettes.

## Foundations

### Color

| Token | Current value | Usage |
|---|---:|---|
| `canvas` | `#08090d` | Chat workspace background |
| `sidebar` | `#0a0c11` | Navigation rail |
| `surface-1` | `#0b0f14` | Memory editor and saved entries |
| `surface-2` | `#0d1117` | Composer and model selector |
| `surface-selected` | `#0d1414` | Routed worker row |
| `text-primary` | `#e7eaf0` | Primary content |
| `text-secondary` | `#9aa5b5` | Supporting labels |
| `text-muted` | `#687586` | Nonessential metadata |
| `accent` | `#72dfbf` | Aether identity and primary action |
| `state-warning` | `#d3a64e` | Thinking / waiting states |
| `state-error` | `#ec6c72` | Explicit failures |

These are existing page values, not extracted Awwwards tokens. Keep state color
paired with text or icon labels so color is not the only signal. Do not use
warning/error colors for decoration.

### Typography

- Existing body stack: Inter when available, followed by system UI fonts.
- Keep body copy readable and conversational; reserve letter-spaced,
  monospace micro-labels for run, routing, and section metadata.
- Use a compact hierarchy: page title, section title, content, metadata. Avoid
  oversized marketing-style hero typography inside the working chat surface.
- Preserve tabular alignment for counts and timestamps when displaying
  operational data.

### Spacing and geometry

Proposed base spacing scale: `4, 8, 12, 16, 24, 32, 48` px. Use these as a
consistent design scale rather than one-off values.

- Use 8–12 px gaps for related controls and 16–24 px between logical groups.
- Keep work surfaces aligned to a common content width.
- Prefer square or 3–5 px corners for operational surfaces and controls; use
  larger radii only where existing authentication components need them.
- Use thin, low-contrast borders to distinguish sections instead of stacked
  cards, shadows, or blurred glass.

### Surfaces and layout

- Keep the existing left navigation / main work-area composition.
- The conversation transcript and composer form the primary content column.
- The empty state uses a centered greeting, concise prompt shortcuts, and a
  wide composer with model and voice controls grouped in its toolbar. The
  activity rail stays out of the empty state and appears for active
  conversations, where it can show real run events without competing with the
  initial prompt.
- Agent activity is a compact right rail on desktop and a stacked section on
  narrow screens. Organize it as: current run summary → Aether Core routing
  event → selected worker state → ordered event details. The connector denotes
  this actual routing relationship; it is not an animated or speculative flow.
- Memory is a dedicated view with a creation form and searchable memory list.
- Keep pending approvals close to the work/navigation context, with explicit
  action labels.
- At mobile widths, reflow navigation and agent activity before shrinking
  controls or text to unreadable sizes.

## Component-state rules

### Agent activity

- Supported live agents: Aether Core and the workers provided by the backend
  agents endpoint.
- Derive states from persisted run/event data. Distinguish idle, thinking,
  working, waiting-for-approval, completed, and error only when supported by
  current events.
- Make the relationship between orchestrator and worker explicit in labels and
  grouping. A compact connector may indicate the recorded routing relationship;
  never draw unobserved execution paths.
- Present technical details such as agent name, event type, and timestamp as
  compact supporting metadata; retain plain-language summaries for the primary
  status.
- On a new conversation or when event history is absent, show “Waiting for
  activity” or an explicit idle state; never imply an agent is working.
- “Memory Agent” is not currently a backend agent and must remain absent until
  a real execution path and state events are added.

### Memory center

- Present category, content, importance, active/archived status, and
  created/updated metadata only when returned by the API.
- Search should filter the loaded records and report an empty result clearly.
- Create, archive/reactivate, and delete actions must use the existing memory
  API and display request errors.

### Model selector

- Show the configured model role and the model's real configured name/provider.
- The existing backend has no availability check. Do not show “Online” or
  “Available” as a live state until an API supports it.

### Chat

- Keep role, author, message body, and pending-request state visually distinct.
- Current backend responses are not streamed. Use a truthful in-flight state
  until the request resolves, and preserve errors/retry context.
- Keep suggested prompts as working composer shortcuts, not simulated
  conversations.

## Motion and accessibility

- Awwwards MCP returned no Motion DNA or measured easing/duration for the
  selected sites. No reference-specific motion timings are claimed.
- Use motion only to communicate state or acknowledge input; do not add
  decorative background motion or heavy animation dependencies.
- Respect `prefers-reduced-motion` for all transitions and future motion.
- Maintain keyboard-operable controls, visible focus, semantic labels, and
  readable contrast.
- Test compact and expanded layouts at desktop and mobile widths before
  implementation is considered complete.

## Evidence boundary

Reference-derived observations and screenshot links are documented in
[Aether Design Brief](./AETHER_DESIGN_BRIEF.md). Awwwards MCP formally returned
no design DNA fields for the nominee shortlist; this proposal's numeric tokens
come from the existing Aether code, and its layout principles are clearly
identified as design recommendations rather than Awwwards measurements.

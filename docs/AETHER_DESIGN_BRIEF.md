# Aether Design Brief — Dark Intelligent Workspace

**Status:** Research and direction only. No UI implementation is included in this phase.

## Project goal

Design a premium, dark, multi-agent AI workspace for Aether. Create a distinctive
product interface that combines the clarity of professional developer tools with
the intelligence and functionality of a multi-agent assistant.

## Research method and limits

Research used the connected Awwwards MCP server. Searches covered dark AI SaaS
dashboards, AI agent workspaces, futuristic software dashboards, developer
tools, productivity applications, data visualization, generative AI interfaces,
and minimal futuristic products. Search results were expanded with broad AI,
dashboard, software, minimal, data-visualization, and interactive-interface
queries to find comparable products.

The candidate pool included AI Vector, Dubbing AI, Cyera AI Guardian,
Imogen: Agentic AI, REVERT AI, Patch Ai, Wafer.ai, The Bluejack Group Dashboard,
Darkmoon, AI Pentest Platform, Gonski Data Lab, Tickerspark.ai, and SmithySoft.

The MCP's `compare_sites` and `create_design_brief` calls returned no formal
palette, technology, award-score, shared-pattern, or motion signals. The
shortlisted pages are Awwwards nominees, for which those structured fields are
not published. Optional live-page capture and structure analysis could not run:
the connected MCP installation has no optional Playwright dependency.

The observations below are therefore limited to visible Awwwards submission
screenshots and element captures. They are visual inspection notes, not
machine-verified site tokens or motion measurements. No palette or motion value
is attributed to Awwwards metadata.

## Shortlist

### 1. The Bluejack Group Dashboard

- [Live site](https://me.thebluejackgroup.com)
- [Awwwards entry](https://www.awwwards.com/sites/the-bluejack-group-dashboard)
- [Submission screenshot](https://assets.awwwards.com/awards/submissions/2026/09/6aaebbb55d1eb062619248.jpg)
- [Dashboard element captures](https://www.awwwards.com/sites/the-bluejack-group-dashboard)

**Observed evidence:** A compact top navigation groups Summary, Email Health,
Website, Heatmaps, Recordings, and AI Presence. The summary places a short
plain-language overview above a baseline/update line and a row of large metrics.
Other element captures show a line chart, ranked horizontal bars, and an AI
concierge layered into the dashboard. The submission shows a narrow-screen
version of the same information.

**Use for Aether:** Pair Darkmoon's agent/run hierarchy with Bluejack's
summary-to-detail structure: a short readable conversation/work summary first,
then current agent state and the ordered execution events that substantiate it.
Keep agent events and memory metadata concise and scannable.

**Do not copy:** The light dashboard palette, political-marketing domain,
specific charts/metrics, or floating concierge treatment. These are not a fit
for Aether's established dark workspace.

### 2. Darkmoon — AI Pentest Platform

- [Live site](https://dark-moon.org/)
- [Awwwards entry](https://www.awwwards.com/sites/darkmoon-ai-pentest-platform)
- [Submission screenshot](https://assets.awwwards.com/awards/submissions/2026/10/6adbc939c3faa234475261.jpg)
- [Awwwards element captures](https://www.awwwards.com/sites/darkmoon-ai-pentest-platform)

**Observed evidence:** The submission uses a near-black field, high-contrast
typography, compact technical labels, restrained blue illumination, and a clear
division between large headline content and supporting detail. Element captures
show a multi-agent statement paired with an orchestrator explanation, plus a
mobile composition and a separate menu state.

**Use for Aether:** This is the primary reference for communicating Aether Core
and specialist agents as one orchestrated system. Distinguish the Core's routing
decision from the worker's actual execution, and use concise technical labels
for the run, agent, and current event. Combine its dark, high-contrast hierarchy
with Aether's existing muted-teal identity rather than adopting Darkmoon's blue
lighting.

**Do not copy:** The moon/space imagery, WebGL presentation, security-product
language, liquid-glass treatment, or scroll-driven 3D. The available screenshots
are primarily a product-marketing site, not proof of its live command-center
interface.

### 3. SmithySoft — Software House

- [Live site](https://www.smithysoft.com/)
- [Awwwards entry](https://www.awwwards.com/sites/smithysoft-software-house)
- [Submission screenshot](https://assets.awwwards.com/awards/submissions/2025/11/6915a909874c0502140226.png)
- [Element captures](https://www.awwwards.com/sites/smithysoft-software-house)

**Observed evidence:** Element captures show a persistent navigation, distinct
content sections, filter-like category controls, service groupings, and a
narrow-screen content treatment. The visuals use large, direct section labels
and a limited set of strong surface/color blocks.

**Use for Aether:** Keep navigation categories explicit and make the Memory
Center and Chat destinations easy to distinguish. Use section labels and
category filters to clarify purpose rather than relying on decorative cards.

**Do not copy:** The agency/marketing content, contact CTA, warm orange highlights,
or broad full-width service panels.

## Design DNA comparison

| Dimension | Bluejack Dashboard | Darkmoon | SmithySoft |
|---|---|---|---|
| Product evidence | Actual dashboard submission with summary, metrics, charts, tabs, and concierge captures | AI-agent product narrative and orchestration/agent element captures; command-center implementation not verified | Software-services marketing site with navigation, sections, and category controls |
| Information hierarchy | Summary text → change context → large metric row → detailed visualizations | Orchestrator → specialist agents → concise technical labels and supporting detail | Section title → category/navigation → grouped content |
| Visible visual character | Predominantly light UI, dark type, red chart accents, green change indicators (visual screenshot observation only) | Near-black surfaces, white type, restrained blue imagery (visual screenshot observation only) | White sections, dark teal/green panels, orange accents (visual screenshot observation only) |
| Typography | Large metric numerals and readable editorial summary | High-contrast headline hierarchy with compact technical labels | Bold sans-serif section titles with supporting prose |
| Responsive evidence | Desktop and narrow/mobile dashboard shown in element captures | Desktop and narrow composition/menu shown in element captures | Mobile article/service content shown in element captures |
| Motion evidence | No structured Motion DNA returned | No structured Motion DNA returned; marketing screenshot describes a shader-built moon, but no timing/easing was measured | Motion clips are listed by MCP, but no motion census or timing values were returned |
| Aether relevance | Primary reference for workspace hierarchy and responsive information density | Primary reference for communicating orchestrator and worker relationships in a dark UI | Supporting reference for navigation/content grouping |

These are screenshot-based observations. `compare_sites` returned empty palette,
technology, awards, and score fields for all three nominees; those missing fields
are intentionally not inferred.

## Combined direction: Dark Intelligent Workspace

Use the existing Aether shell and dark/teal identity as the foundation. Combine
Darkmoon's explicit orchestrator-to-agent narrative with Bluejack's summary,
section, and detail hierarchy, and SmithySoft's clear navigation/category
grouping. The result should read as a working tool, not as a copy of any
reference landing page or a grid of decorative analytics cards.

1. **Conversation remains the primary work surface.** Give the chat transcript,
   current conversation, and responsive composer the strongest spatial
   priority.
2. **Agent activity explains orchestration, not theater.** Borrow Darkmoon's
   clear system-level explanation, but translate it into live Aether evidence:
   show Aether Core's routing event separately from the selected worker's
   execution state. Borrow Bluejack's summary-to-detail order so the user sees
   the current run at a glance and can inspect concise, time-ordered events.
   Show only agents and states supported by backend configuration/events.
3. **Memory is a library with controls.** Make saved content searchable and
   categorized, and expose its active/archived state and existing CRUD actions.
4. **Navigation communicates workspace modes.** Keep conversation history
   accessible while giving Chat and Memory distinct destinations.
5. **Use hierarchy before decoration.** Prefer clear labels, typographic scale,
   alignment, spacing, and restrained surface changes over gradients, glow,
   glass, or ornamental charts.
6. **Carry visual cues, not source layouts.** Translate Darkmoon's
   orchestrator/agent distinction, Bluejack's information hierarchy, and
   SmithySoft's explicit grouping into Aether's own domain, data, API contracts,
   and identity.

### Backend-backed interface constraints

- The backend currently exposes assistant, researcher, developer, productivity,
  and document agents. It does **not** expose a separate Memory Agent. Do not
  render a Memory Agent status until one is implemented and emits real state.
- Agent activity is persisted/replayed by run and event sequence. The UI should
  derive status from those events and must not invent a status when there is no
  event.
- Memory CRUD/listing exists; filtering can operate on loaded memory results.
- The current UI selects general/coding models, but there is no model
  availability/health endpoint. Do not display a live availability indicator
  without adding a real backend source in a separately approved implementation.
- Chat responses are request/response, not token-streaming. A loading indicator
  may communicate an in-flight request, but must not claim text is streaming.

## MCP-generated brief result

`create_design_brief` was run with the three selected slugs and the required
project goal. Its returned `sharedPatterns`, `palette`, `technologySignals`,
`elementSignals`, `motion`, and interaction lists were empty because the selected
nominees have no matching structured metadata/motion records in the MCP cache.
The brief above is the transparent evidence-based synthesis of the returned
screenshots and element captures; it does not pretend the MCP generated signals
that it did not return.

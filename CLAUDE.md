# DB Diagram Visualizer

A dbdiagram.io-like tool for analyzing database tables and their relationships.

## Project Overview
- **Backend**: Python (Flask/FastAPI) — handles CSV parsing, key detection, relationship analysis
- **Frontend**: Vanilla JS with HTML5 Canvas/SVG — interactive diagram canvas
- **Input**: CSV files with column names and data
- **Output**: Visual canvas showing tables, columns, keys, and connections

## Key Principles
1. **Lines always redraw** — connection lines recalculate on every state change (move, filter, add, remove, sort)
2. **Modular architecture** — each JS module has a single responsibility, communicates via event bus
3. **State-driven UI** — central state store is the single source of truth
4. **Python does data, JS does UI** — clean backend/frontend separation
5. **DDL safety first** — all generated SQL uses quoted identifiers, topological FK ordering, transaction wrapping

## Two Pages

### Page 1: Diagram Visualizer (existing)
CSV upload → automatic schema detection → interactive canvas with tables, connections, search, trace, filters.

### Page 2: PostgreSQL Schema Builder (new)
Design PostgreSQL schemas visually → generate production-ready DDL. Three input modes: build from scratch, import from CSV (diagram page), or import from existing `.sql` files (pg_dump, hand-written DDL). Supports all PG data types, constraints (PK, FK, UNIQUE, CHECK, NOT NULL, DEFAULT), table types (permanent, temp, unlogged), indexes (B-tree, GIN, GiST), enums, and relationships (1:1, 1:N, M:N, self-ref). When modifying an imported schema, generates ALTER-based migration DDL (not full CREATE). Exports `.sql` files with correct FK ordering and transaction wrapping.

### Backend Modules — Builder
- `schema_builder.py` — Core schema definition data structures, validation, manipulation
- `ddl_generator.py` — Generates PostgreSQL DDL (CREATE TABLE, ALTER TABLE, CREATE INDEX, CREATE TYPE)
- `ddl_parser.py` — Parses .sql files into builder schema format (statement tokenizer, pg_dump compatible)
- `schema_differ.py` — Compares original vs modified schema, generates minimal ALTER DDL migrations
- `type_mapper.py` — Maps source column types (from CSV) → proper PostgreSQL types with size/precision
- `migration_generator.py` — Generates data migration SQL (INSERT INTO...SELECT with type casts)
- `pg_validator.py` — Validates schema correctness: naming, constraints, FK targets, circular refs, reserved words
- `builder_routes.py` — Flask Blueprint for /api/builder/* routes

### Frontend Modules — Builder (`static/js/builder/`)
- `builder-app.js` — Main orchestrator for builder page (reuses existing `events.js`)
- `builder-state.js` — State store for target schema being built
- `builder-panels.js` — Source panel (loaded CSV tables) + target panel (PG schema)
- `builder-editors.js` — Table editor + column editor (types, constraints, defaults)
- `builder-pickers.js` — PostgreSQL type selector + constraint picker with categories
- `builder-output.js` — Live DDL preview + export controls (.sql, clipboard, JSON)
- `builder-relationships.js` — FK relationship wiring between target tables
- `builder-constants.js` — PG type catalog, constraint options, builder colors

### API Endpoints — Builder
- `POST /api/builder/validate` — Validate schema, return errors
- `POST /api/builder/generate-ddl` — Generate PostgreSQL DDL from schema
- `POST /api/builder/generate-migration` — Generate migration SQL (ALTER-based if original exists, INSERT if source mapped)
- `POST /api/builder/import-sql` — Parse uploaded .sql file into builder schema format
- `POST /api/builder/type-suggest` — Suggest PG type from source column metadata
- `POST /api/builder/preview-table` — Preview DDL for a single table

## Skills

### Diagram Skills
- `.claude/skills/db-diagram-designer.md` — Full design lifecycle: CSV to visual diagram, layout algorithms, import/export
- `.claude/skills/db-canvas-engine.md` — Rendering pipeline, redraw system, coordinate math, performance
- `.claude/skills/db-canvas-ui.md` — Table block design, interaction patterns, visual states, theming
- `.claude/skills/connection-line-manager.md` — Line rendering, anchor calculation, bezier curves, cardinality notation
- `.claude/skills/db-search-system.md` — Cross-table value search, data flow tracing, result visualization
- `.claude/skills/frontend-design.md` — UI design guidance for the diagram canvas
- `.claude/skills/frontend-patterns.md` — Module structure and development patterns
- `.claude/skills/interactive-filtering.md` — Filter UI and connection highlighting

### Builder Skills
- `.claude/skills/pg-ddl-engine.md` — PG data types, constraints, table types, DDL generation, identifier safety, type mapping
- `.claude/skills/pg-builder-ui.md` — Builder page layout, table/column editors, type pickers, live DDL preview
- `.claude/skills/pg-validation.md` — Naming rules, constraint conflicts, FK validation, circular refs, reserved words, injection prevention
- `.claude/skills/pg-migration.md` — DDL export ordering, transaction wrapping, INSERT INTO...SELECT, data type conversion
- `.claude/skills/pg-sql-import.md` — SQL file parsing, statement tokenizer, CREATE/ALTER/INDEX extraction, pg_dump compatibility
- `.claude/skills/pg-schema-diff.md` — Schema comparison, ALTER generation, column/constraint/index diffs, enum evolution

## Rules
- `.claude/rules/modular-architecture.md` — Project structure and module boundaries
- `.claude/rules/canvas-redraw-guarantee.md` — Lines must always redraw (the iron rule)
- `.claude/rules/code-style.md` — Naming and style conventions
- `.claude/rules/ddl-safety.md` — Quoted identifiers, reserved words, FK ordering, transaction wrapping, no injection
- `.claude/rules/schema-builder-architecture.md` — Builder module boundaries, state shape, event contracts

---

## LLM Coding Rules

### Default Mode: Plan First
- **ALWAYS enter plan mode before writing code.** Think, then do.
- For any change touching 2+ files or adding new behavior: outline the plan, list affected files, and get user confirmation before coding.
- For single-line fixes or trivial edits: skip plan, just do it.

### Read Before Write
- NEVER edit a file you haven't read in this conversation.
- Before modifying a function, read it AND its callers.
- Before accessing state, read `state.js`. Before emitting events, read `events.js`.
- Grep for a function/variable before assuming it exists.

### One Change, One Purpose
- Each edit does ONE thing. Don't bundle unrelated fixes.
- Change files in dependency order: state → events → logic → UI → connections redraw.
- Never leave the codebase in a half-changed state between edits.

### Keep It Simple and Clean
- Functions do one thing, describable in one sentence without "and".
- Max 40 lines per function. If longer, split by responsibility.
- Use clear names like in code-style rule 
- No dead code, no commented-out blocks, no "for later" params.
- Early returns for guard clauses. No deep nesting.
- Validate at boundaries (user input, API responses). Trust internal code.

### Import/Export Discipline
- Every `import` must match a real `export`. Verify after adding or removing functions.
- After deleting a function, find and update all import sites.

### State Is Sacred
- All mutations go through `state.js` functions. Never modify state objects directly.
- Never store derived data in state (computed line paths, filtered lists).
- Every state change must emit an event. No silent mutations.

---

## Plan Patterns

### Step 1: Understand Current State
- Read all files involved. Map data flow: source → transform → render.
- List affected modules, state keys, and events.

### Step 2: Define Target State
- Describe what the code should do AFTER the change, in plain words.
- Identify what's new (state keys, events, endpoints) and what must NOT change.

### Step 3: Sequence Changes
Order to avoid broken intermediate states:
1. Backend (new endpoints, data processing)
2. State shape (new keys, updated types)
3. Events (new events, updated payloads)
4. Core logic (the main change)
5. UI (rendering, interaction)
6. Connection redraw (verify the iron rule holds)
7. Cleanup (remove old code, unused imports)

### Step 4: Identify Risks
Before starting, ask:
- What breaks if my assumption about X is wrong?
- Does this change any event contract or public API?
- Will connection lines still redraw correctly?
- Edge cases: empty data, zero tables, extreme zoom?

---

## Verification Before Done

**NEVER mark work as complete without running this checklist:**

1. **Syntax check** — no typos, no missing brackets, no broken imports.
2. **Read the diff** — re-read every changed file. Does each edit do what was intended?
3. **Cross-file consistency** — if you changed a function signature, did you update all call sites? If you added a state key, is it initialized? If you added an event, is something listening?
4. **The Iron Rule** — does `connections.redrawAll()` still get called on every state change? Check explicitly.
5. **Edge cases** — what happens with 0 tables? 1 table? No connections? All filters active? All filters cleared?
6. **No dead code** — no unused variables, no orphan imports, no leftover console.logs.
7. **Style match** — naming, indentation, and patterns match the rest of the codebase.

If any check fails, fix it before presenting the result. Do not tell the user "done" with known issues.

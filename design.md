# Design Notes

This file captures the current application design so future iterations can be deliberate instead of ad hoc.

## Product goal

Replace the original single-page Streamlit interface with a web application that:

- separates backend workflow execution from frontend interaction state
- feels like an internal operations product rather than a prototype
- supports fast inspection, auditability, and iterative refinement

## Current architecture

### Backend

- Framework: FastAPI
- Entrypoint: `app.py`
- API module: `backend/main.py`
- Existing domain logic reused from `src/ssi_extraction/`
- Responsibilities:
  - file upload handling
  - config loading
  - extraction pipeline execution
  - optional field-catalog-assisted ISDA mapping
  - SQLite summaries and table views
  - read-only SQL execution
  - chat endpoints grounded in extracted JSON

### Frontend

- Framework: React with Vite
- Styling: Tailwind CSS
- Component style: shadcn-inspired local primitives
- Responsibilities:
  - runtime path configuration
  - workflow navigation
  - upload forms
  - latest extraction review
  - searchable database exploration
  - SQL tools
  - document-aware chat surfaces

## Visual direction

The current frontend is intentionally not a default dashboard.

### Design choices

- Warm editorial base:
  - cream background
  - white glass panels
  - rust accent
  - blue-green secondary accent
- Typography split:
  - serif display headings for a more document-centric feel
  - clean sans-serif body for dense operational content
- Spatial hierarchy:
  - large hero at the top
  - persistent left-side configuration and workflow rail
  - wide content canvas for data-heavy review panels
- Atmosphere:
  - layered gradients
  - subtle grid texture
  - soft panel shadows

## Interaction model

### Left rail

The left rail is now intentionally minimal and collapsible.

It contains only:

- workflow switching
- collapse and expand control

Runtime path and config editing have been removed from the visible UI so the product feels focused on document work rather than environment setup.

### SSI workflow

The SSI flow is now structured around two tabs:

1. `Overview`
2. `Database`

Within `Overview`, the content is stacked vertically:

1. Upload and run extraction
2. Review the latest extraction payload
3. Ask JSON-grounded questions

Within `Database`, the user can:

1. Inspect normalized DB views
2. Run custom SQL if needed

This mirrors how an operator typically validates extracted SSI data.

### ISDA workflow

The ISDA flow is also split into two tabs:

1. `Overview`
2. `Database`
3. `Catalog`

Within `Overview`, the content is stacked vertically:

1. Upload and extract a DOCX
2. Review the in-memory result
3. Ask document-grounded questions

Within `Database`, the user can:

1. Select from saved documents
2. Inspect searchable field rows
3. Run custom SQL if needed

Within `Catalog`, the user can:

1. Inspect the loaded field catalog from the configured JSON file
2. Search attribute definitions directly while reviewing extraction results

This reflects the document-centric nature of ISDA review work.

## Component decisions

The current UI uses a small local component set:

- `Button`
- `Card`
- `Input`
- `Textarea`
- `Badge`

The intent is to keep the surface area small while the design settles. If the UI grows, these primitives can be expanded into a more complete local design system.

## Data and UX decisions

### Why latest extraction and database views are separate

The application separates:

- latest API response review
- persisted SQLite exploration

This distinction matters because users often want to validate the immediate extraction result before relying on the database state.

### Why the header is simple

The header is deliberately reduced to a single product title:

- it removes dashboard noise
- it keeps attention on the active workflow
- it avoids turning the landing area into a metrics strip

### Why chat is grounded in JSON context

Chat is intentionally based on extracted JSON payloads rather than table rows alone because:

- the structured payload preserves more source context
- it avoids implying that SQLite tables are the full truth
- it matches how the existing extraction logic already thinks about context

### Why the ISDA field catalog is external

The large 201-field catalog is treated as an external JSON artifact rather than hardcoded application data because:

- it can change independently of UI iterations
- it belongs to the data model domain, not the frontend
- the airgapped workflow makes file-based handoff practical

The current design expects the backend to load that file from disk and feed it into extraction-time matching.

The current extraction model is:

1. field catalog drives canonical matching through `attributeName`
2. catalog-matched items stay in `normalized_fields`
3. unmatched document labels stay in `additional_fields`
4. the backend computes a mapping summary for coverage and auditability

### Why read-only SQL remains in the product

The SQL panels are useful for:

- audit and troubleshooting
- quick checks across normalized tables
- low-friction debugging during extraction tuning

They should remain read-only.

## Current strengths

- Clear split between backend and frontend concerns
- Better visual hierarchy than the old Streamlit UI
- Simpler top-level framing with less dashboard clutter
- Good support for operational review flows
- Layout scales better for dense data and multi-panel inspection
- Backend API is broad enough for iterative frontend changes

## Current weaknesses

- No authentication or user model
- No background job queue or extraction progress streaming
- Chat surfaces are basic and do not yet expose citations/snippets
- Tables are generic and not yet specialized per workflow
- Runtime config is session-local and not persisted beyond the app state

## Next iteration options

### Frontend UX

- Add route-based navigation instead of a single-page workflow switch
- Add workflow-specific empty states and guided onboarding
- Improve table ergonomics:
  - sticky filters
  - column visibility
  - copy actions
  - CSV export from the frontend
- Add stronger status feedback for long-running extractions

### Backend

- Add progress events for extraction jobs
- Add stronger response schemas for frontend typing
- Add endpoint-level tests
- Add structured logging around upload and chat requests

### Design system

- Expand local primitives into a fuller component set
- Standardize spacing, type scale, and motion tokens
- Introduce shared chart or summary components if analytics views are added

## Rule for future changes

When iterating on the UI:

- preserve the split between global controls and workflow content
- preserve the distinction between latest extraction review and persisted database review
- avoid reverting to a plain admin-dashboard look
- keep auditability and document context visible in the experience

---
Skill name: Interactive Filtering and Connection Highlighting

1. Filter Types:
   - Table name search (text input, fuzzy match)
   - Column name search across all tables
   - Data type filter (show only tables with specific types)
   - Key type filter (show only PK, FK, or indexed columns)
   - Relationship filter (show only connected/orphan tables)
   - Custom tag/group filter

2. Filter Behavior Rules:
   - Filtered-OUT tables fade to low opacity (not hidden) or can be hidden entirely (toggle)
   - Filtered-IN tables show at full opacity
   - Connection lines between filtered-in tables: BOLD and colored
   - Connection lines from filtered-in to filtered-out: DASHED and dimmed
   - Connection lines between filtered-out tables: HIDDEN
   - Lines ALWAYS redraw when filter state changes
   - Filter state is part of the central state store

3. Filter UI Design:
   - Sidebar panel (collapsible) or toolbar
   - Real-time results as user types (debounced 200ms)
   - Active filter chips/badges showing current filters
   - Clear all filters button
   - Filter count indicator (showing X of Y tables)

4. Connection Tracing:
   - Click a table to highlight ALL its connections (direct and transitive)
   - "Trace path" mode: click two tables to highlight the connection chain between them
   - Depth control: show connections up to N levels deep

5. Auto-Sort/Layout Button:
   - Force-directed graph layout algorithm
   - Hierarchical layout (tables with most connections centered)
   - Grid layout option
   - Animate transition from current positions to sorted positions
   - After sort: REDRAW ALL LINES with new positions

6. Integration with Canvas:
   - Filter module emits "filterChanged" events
   - Canvas listens and triggers full line redraw
   - Block visibility/opacity managed by filter state
   - Selected filters persist in URL hash for sharing

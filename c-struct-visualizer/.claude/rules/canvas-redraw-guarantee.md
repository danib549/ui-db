# Canvas Redraw Guarantee

## The Iron Rule

**Connection lines and blocks MUST be redrawn whenever ANY state change occurs.**

Every mutation in `cstruct-state.js` emits `cstructStateChanged`. `cstruct-app.js` subscribes to this event and calls `scheduleRender()`, which batches redraws via `requestAnimationFrame`.

### Trigger Events (exhaustive)
- Block dragged/moved
- Data loaded from backend (new parse result)
- Layout algorithm applied
- Viewport zoomed or panned
- Browser window resized
- Block collapsed or expanded
- Entity hovered or unhovered
- Entity selected or deselected
- Architecture changed (triggers re-parse → new data → full redraw)

### Implementation

```javascript
// cstruct-app.js
EventBus.on('cstructStateChanged', scheduleRender);

function scheduleRender() {
  if (rafId) return;
  rafId = requestAnimationFrame(render);
}

function render() {
  rafId = null;
  // clear → grid → connections → blocks (full pipeline)
}
```

### Enforcement

1. **Every state mutator emits** — no silent mutations in `cstruct-state.js`
2. **`scheduleRender()` uses rAF** — multiple synchronous state changes coalesce into one frame
3. **`cstruct-connections.js` never subscribes to events** — app.js calls drawing functions as part of render()
4. **No cached positions** — anchor points are always computed from current block positions

## Anti-Patterns

- Never skip redraw for "performance" — use rAF batching instead
- Never cache line positions between frames
- Never assume previous positions are valid after any state change
- Never draw connections outside the render pipeline

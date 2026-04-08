# Code Style

## JavaScript
- ES6 modules (`import`/`export`)
- `const` by default, `let` when reassignment needed, never `var`
- Arrow functions for callbacks
- Descriptive names: `drawBezierConnection()` not `dbc()`
- All coordinates use `{x, y}` objects
- All colors from `cstruct-constants.js` or `getColors()`/`getCategoryColors()`
- Functions max ~40 lines — split by responsibility if longer
- Early returns for guard clauses

## Python
- Python 3.10+
- Type hints on all function signatures
- `pathlib` for file paths
- `snake_case` everywhere
- Return dicts from backend functions, let routes handle JSON serialization
- Pure functions in `c_parser.py` — no Flask, no HTTP, no side effects

## Naming Conventions
- JS files: `cstruct-*.js` (kebab-case)
- JS functions: `camelCase`
- JS constants: `UPPER_SNAKE_CASE` for objects (`BLOCK`, `LINE`), `camelCase` for color dicts
- Python files: `snake_case.py`
- Events: `camelCase` with `cstruct` prefix (`cstructDataLoaded`, `cstructStateChanged`)
- CSS: kebab-case for classes, BEM-like (`.upload-zone`, `.upload-zone--active`, `.sidebar__badge`)

## File Organization
- Backend modules at project root: `app.py`, `cstruct_routes.py`, `c_parser.py`
- Frontend modules in `static/js/cstruct/`
- Shared modules in `static/js/` (events.js, utils.js)
- Styles in `static/css/`
- Templates in `templates/`

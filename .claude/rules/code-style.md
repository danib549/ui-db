---
description: Code style and conventions for the DB Diagram Visualizer
globs: ["**/*.py", "**/*.js", "**/*.html", "**/*.css"]
---

# Code Style Rules

## JavaScript
- Use ES6 modules (import/export)
- Use const by default, let when reassignment needed, never var
- Use arrow functions for callbacks
- Descriptive function names: `drawConnectionLine()` not `dcl()`
- All canvas coordinates use {x, y} objects
- All colors defined in a central theme/constants object

## Python
- Python 3.10+
- Type hints on all function signatures
- Use pathlib for file paths
- Flask or FastAPI (decide once, stick with it)
- Return dicts from backend functions, let routes handle JSON serialization

## HTML/CSS
- Semantic HTML5
- BEM-like CSS naming: `.table-block`, `.table-block__header`, `.table-block--selected`
- CSS custom properties for theming (colors, spacing)
- No CSS frameworks — keep it custom and lightweight

## Naming Conventions
- JS files: camelCase functions, PascalCase classes
- Python files: snake_case everywhere
- CSS: kebab-case for classes
- Events: camelCase strings (`tableMoved`, `filterChanged`)

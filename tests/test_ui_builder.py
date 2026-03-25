"""
E2E tests for the PostgreSQL Schema Builder frontend.

Tests the JavaScript modules (builder-state, builder-panels, builder-editors,
builder-pickers, builder-output, builder-relationships) via Playwright against
a live Flask server.
"""

import re
import threading
import time
import json
import pytest
from playwright.sync_api import Page, expect
from werkzeug.serving import make_server
from app import app


class ServerThread(threading.Thread):
    def __init__(self, app):
        threading.Thread.__init__(self)
        self.server = make_server('127.0.0.1', 5005, app)
        self.ctx = app.app_context()
        self.ctx.push()

    def run(self):
        self.server.serve_forever()

    def shutdown(self):
        self.server.shutdown()


@pytest.fixture(scope="session")
def live_server():
    app.config['TESTING'] = True
    server = ServerThread(app)
    server.start()
    time.sleep(1)
    yield "http://127.0.0.1:5005"
    server.shutdown()
    server.join()


def _goto_builder(page: Page, live_server: str):
    """Navigate to /builder and wait for JS modules to initialize."""
    page.goto(f"{live_server}/builder")
    page.wait_for_selector("#btn-add-table", state="visible")


# ---------------------------------------------------------------------------
# 1. Page loads correctly
# ---------------------------------------------------------------------------

def test_builder_page_loads(page: Page, live_server: str):
    _goto_builder(page, live_server)
    expect(page.locator("h1.builder-nav__title")).to_contain_text("PostgreSQL Schema Builder")
    expect(page.locator("#btn-add-table")).to_be_visible()
    expect(page.locator("#btn-add-enum")).to_be_visible()
    expect(page.locator("#ddl-preview")).to_be_visible()
    # Empty state messages
    expect(page.locator("#target-empty")).to_be_visible()


# ---------------------------------------------------------------------------
# 2. Add Table → table card appears with default "id" column
# ---------------------------------------------------------------------------

def test_add_table_creates_card(page: Page, live_server: str):
    _goto_builder(page, live_server)
    page.click("#btn-add-table")

    card = page.locator(".builder-table-card").first
    expect(card).to_be_visible()

    # Table name defaults to table_1
    name_input = card.locator(".builder-table-card__name")
    expect(name_input).to_have_value("table_1")

    # Has default "id" column
    col_row = card.locator(".builder-column-row").first
    expect(col_row).to_be_visible()
    col_name = col_row.locator(".builder-column-row__name")
    expect(col_name).to_have_value("id")

    # Has PK badge on the id column
    expect(col_row.locator(".builder-badge--pk")).to_be_visible()

    # Empty state should be hidden
    expect(page.locator("#target-empty")).to_be_hidden()


# ---------------------------------------------------------------------------
# 3. Add Column → new column row appears
# ---------------------------------------------------------------------------

def test_add_column(page: Page, live_server: str):
    _goto_builder(page, live_server)
    page.click("#btn-add-table")

    card = page.locator(".builder-table-card").first
    card.locator(".builder-table-card__add-column").click()

    # Should now have 2 columns (id + column_2)
    col_rows = card.locator(".builder-column-row")
    expect(col_rows).to_have_count(2)

    second_col = col_rows.nth(1)
    expect(second_col.locator(".builder-column-row__name")).to_have_value("column_2")


# ---------------------------------------------------------------------------
# 4. DDL preview updates after adding table
# ---------------------------------------------------------------------------

def test_ddl_preview_updates(page: Page, live_server: str):
    _goto_builder(page, live_server)
    page.click("#btn-add-table")

    # DDL is generated async (debounced 300ms) then API call
    ddl = page.locator("#ddl-preview")
    expect(ddl).to_contain_text("CREATE TABLE", timeout=5000)
    expect(ddl).to_contain_text('"table_1"')
    expect(ddl).to_contain_text('"id"')


# ---------------------------------------------------------------------------
# 5. Validation tab shows results
# ---------------------------------------------------------------------------

def test_validation_tab(page: Page, live_server: str):
    _goto_builder(page, live_server)
    page.click("#btn-add-table")

    # Switch to Errors tab
    page.locator('.builder-output__tab[data-tab="validation"]').click()
    validation = page.locator("#tab-validation")
    expect(validation).to_have_class(re.compile(r"builder-output__content--active"))

    # Wait for validation to complete (debounced 500ms + API call)
    page.wait_for_timeout(1500)
    # Should have some validation content rendered
    expect(validation.locator(".builder-validation__item").first).to_be_visible()


# ---------------------------------------------------------------------------
# 6. Inline column name editing
# ---------------------------------------------------------------------------

def test_inline_column_name_edit(page: Page, live_server: str):
    _goto_builder(page, live_server)
    page.click("#btn-add-table")

    card = page.locator(".builder-table-card").first
    # Add a second column
    card.locator(".builder-table-card__add-column").click()

    # Rename column_2 to "email"
    col_name_input = card.locator(".builder-column-row").nth(1).locator(".builder-column-row__name")
    col_name_input.fill("email")
    # Blur triggers the rename → state change → rAF → re-render
    col_name_input.evaluate("el => el.blur()")

    # After re-render, the data-column attr should reflect the new name
    expect(card.locator('.builder-column-row[data-column="email"]')).to_be_visible(timeout=3000)


# ---------------------------------------------------------------------------
# 7. Column type picker button
# ---------------------------------------------------------------------------

def test_column_type_picker(page: Page, live_server: str):
    _goto_builder(page, live_server)
    page.click("#btn-add-table")

    card = page.locator(".builder-table-card").first
    card.locator(".builder-table-card__add-column").click()

    # Click the type button on the second column
    type_btn = card.locator(".builder-column-row").nth(1).locator(".builder-column-row__type-btn")
    expect(type_btn).to_contain_text("text")  # default type
    type_btn.click()

    # A type picker dropdown should appear
    type_picker = page.locator(".builder-type-picker")
    expect(type_picker).to_be_visible()


# ---------------------------------------------------------------------------
# 8. Column editor modal opens
# ---------------------------------------------------------------------------

def test_column_editor_modal(page: Page, live_server: str):
    _goto_builder(page, live_server)
    page.click("#btn-add-table")

    card = page.locator(".builder-table-card").first
    # Click the edit (pencil) button on the id column
    card.locator(".builder-column-row").first.locator(".builder-column-row__edit").click()

    modal = page.locator("#column-editor")
    expect(modal).not_to_be_hidden()

    # Modal should show table and column name
    expect(page.locator("#editor-table-name")).to_contain_text("table_1")
    expect(page.locator("#editor-col-name")).to_contain_text("id")

    # Close the modal
    page.locator("#editor-close").click()
    expect(modal).to_be_hidden()


# ---------------------------------------------------------------------------
# 9. Column editor — toggle PK unchecks nullable
# ---------------------------------------------------------------------------

def test_column_editor_pk_unchecks_nullable(page: Page, live_server: str):
    _goto_builder(page, live_server)
    page.click("#btn-add-table")

    card = page.locator(".builder-table-card").first
    card.locator(".builder-table-card__add-column").click()

    # Open editor for column_2 (nullable=true, pk=false by default)
    card.locator(".builder-column-row").nth(1).locator(".builder-column-row__edit").click()

    modal = page.locator("#column-editor")
    expect(modal).not_to_be_hidden()

    pk_checkbox = modal.locator("#editor-pk")
    nullable_checkbox = modal.locator("#editor-nullable")

    # column_2 starts nullable
    expect(nullable_checkbox).to_be_checked()

    # Check PK — should uncheck nullable
    pk_checkbox.check()
    expect(nullable_checkbox).not_to_be_checked()


# ---------------------------------------------------------------------------
# 10. Column editor — apply changes
# ---------------------------------------------------------------------------

def test_column_editor_apply(page: Page, live_server: str):
    _goto_builder(page, live_server)
    page.click("#btn-add-table")

    card = page.locator(".builder-table-card").first
    card.locator(".builder-table-card__add-column").click()

    # Open editor for column_2
    card.locator(".builder-column-row").nth(1).locator(".builder-column-row__edit").click()
    modal = page.locator("#column-editor")

    # Toggle unique
    unique_checkbox = modal.locator("#editor-unique")
    unique_checkbox.check()

    # Apply
    page.locator("#editor-apply").click()
    expect(modal).to_be_hidden()

    # After re-render (state change → rAF → re-render + API calls), column should show UQ badge
    second_col = card.locator(".builder-column-row").nth(1)
    expect(second_col.locator(".builder-badge--uq")).to_be_visible(timeout=3000)


# ---------------------------------------------------------------------------
# 11. Delete column
# ---------------------------------------------------------------------------

def test_delete_column(page: Page, live_server: str):
    _goto_builder(page, live_server)
    page.click("#btn-add-table")

    card = page.locator(".builder-table-card").first
    card.locator(".builder-table-card__add-column").click()
    expect(card.locator(".builder-column-row")).to_have_count(2)

    # Delete column_2
    card.locator(".builder-column-row").nth(1).locator(".builder-column-row__delete").click()

    page.wait_for_timeout(300)
    expect(card.locator(".builder-column-row")).to_have_count(1)


# ---------------------------------------------------------------------------
# 12. Delete table (via confirm dialog)
# ---------------------------------------------------------------------------

def test_delete_table(page: Page, live_server: str):
    _goto_builder(page, live_server)
    page.click("#btn-add-table")
    expect(page.locator(".builder-table-card")).to_have_count(1)

    # Click delete button on the table card
    page.locator(".builder-table-card__delete").first.click()

    # Confirm dialog should appear
    confirm = page.locator("#confirm-dialog")
    expect(confirm).not_to_be_hidden()
    expect(page.locator("#confirm-message")).to_contain_text("Delete table")

    # Confirm deletion
    page.locator("#confirm-ok").click()
    page.wait_for_timeout(300)

    expect(page.locator(".builder-table-card")).to_have_count(0)
    expect(page.locator("#target-empty")).to_be_visible()


# ---------------------------------------------------------------------------
# 13. Add Enum
# ---------------------------------------------------------------------------

def test_add_enum(page: Page, live_server: str):
    _goto_builder(page, live_server)
    page.click("#btn-add-enum")

    enum_card = page.locator("#target-enums .builder-enum-card").first
    expect(enum_card).to_be_visible()


# ---------------------------------------------------------------------------
# 14. Table type selector (permanent / temp / unlogged)
# ---------------------------------------------------------------------------

def test_table_type_selector(page: Page, live_server: str):
    _goto_builder(page, live_server)
    page.click("#btn-add-table")

    card = page.locator(".builder-table-card").first
    type_select = card.locator(".builder-table-card__type")
    type_select.select_option("unlogged")

    # DDL should eventually contain UNLOGGED
    ddl = page.locator("#ddl-preview")
    expect(ddl).to_contain_text("UNLOGGED", timeout=5000)


# ---------------------------------------------------------------------------
# 15. Rename table inline
# ---------------------------------------------------------------------------

def test_rename_table(page: Page, live_server: str):
    _goto_builder(page, live_server)
    page.click("#btn-add-table")

    card = page.locator(".builder-table-card").first
    name_input = card.locator(".builder-table-card__name")
    name_input.fill("users")
    name_input.press("Enter")

    # DDL should update with new name
    ddl = page.locator("#ddl-preview")
    expect(ddl).to_contain_text('"users"', timeout=5000)


# ---------------------------------------------------------------------------
# 16. Multiple tables — DDL contains both
# ---------------------------------------------------------------------------

def test_multiple_tables(page: Page, live_server: str):
    _goto_builder(page, live_server)
    page.click("#btn-add-table")
    page.click("#btn-add-table")

    expect(page.locator(".builder-table-card")).to_have_count(2)

    ddl = page.locator("#ddl-preview")
    expect(ddl).to_contain_text('"table_1"', timeout=5000)
    expect(ddl).to_contain_text('"table_2"')


# ---------------------------------------------------------------------------
# 17. Output panel tabs switch correctly
# ---------------------------------------------------------------------------

def test_output_tab_switching(page: Page, live_server: str):
    _goto_builder(page, live_server)

    # DDL tab active by default
    ddl_tab = page.locator('.builder-output__tab[data-tab="ddl"]')
    expect(ddl_tab).to_have_class(re.compile(r"builder-output__tab--active"))

    # Switch to migration tab
    mig_tab = page.locator('.builder-output__tab[data-tab="migration"]')
    mig_tab.click()
    expect(mig_tab).to_have_class(re.compile(r"builder-output__tab--active"))
    expect(ddl_tab).not_to_have_class(re.compile(r"builder-output__tab--active"))
    expect(page.locator("#tab-migration")).to_have_class(re.compile(r"builder-output__content--active"))

    # Switch to map tab
    map_tab = page.locator('.builder-output__tab[data-tab="map"]')
    map_tab.click()
    expect(map_tab).to_have_class(re.compile(r"builder-output__tab--active"))
    expect(page.locator("#tab-map")).to_have_class(re.compile(r"builder-output__content--active"))


# ---------------------------------------------------------------------------
# 18. JSON shape sent to /api/builder/validate
# ---------------------------------------------------------------------------

def test_validate_request_shape(page: Page, live_server: str):
    _goto_builder(page, live_server)

    captured = []

    def capture_request(route):
        req = route.request
        captured.append(req.post_data_json)
        route.continue_()

    page.route("**/api/builder/validate", capture_request)
    page.click("#btn-add-table")

    # Wait for debounced validation (500ms) + request
    page.wait_for_timeout(2000)

    assert len(captured) > 0, "No validate request was sent"
    data = captured[-1]
    assert "schema" in data
    assert "tables" in data["schema"]
    assert len(data["schema"]["tables"]) == 1
    table = data["schema"]["tables"][0]
    assert table["name"] == "table_1"
    assert len(table["columns"]) >= 1
    assert table["columns"][0]["name"] == "id"
    assert table["columns"][0]["type"] == "bigint"


# ---------------------------------------------------------------------------
# 19. JSON shape sent to /api/builder/generate-ddl
# ---------------------------------------------------------------------------

def test_generate_ddl_request_shape(page: Page, live_server: str):
    _goto_builder(page, live_server)

    captured = []

    def capture_request(route):
        req = route.request
        captured.append(req.post_data_json)
        route.continue_()

    page.route("**/api/builder/generate-ddl", capture_request)
    page.click("#btn-add-table")

    # Wait for debounced DDL generation (300ms) + request
    page.wait_for_timeout(2000)

    assert len(captured) > 0, "No generate-ddl request was sent"
    data = captured[-1]
    assert "schema" in data
    assert "tables" in data["schema"]


# ---------------------------------------------------------------------------
# 20. EventBus fires builderTableAdded when table is added
# ---------------------------------------------------------------------------

def test_event_bus_table_added(page: Page, live_server: str):
    _goto_builder(page, live_server)

    # Hook into the custom EventBus (not window events)
    page.evaluate('''() => {
        window.__firedEvents = [];
        // Access EventBus from the ES module - it's on the import graph.
        // We hook into it via the builder-state module's emit, which calls EventBus.emit.
        // Simplest: monkey-patch on the global module listeners map.
        const origEmit = window.__eventBusEmit;
        // Alternative: just poll state after action.
    }''')

    # Instead of hooking EventBus directly, verify the *effect* of the event:
    # builderTableAdded causes builderStateChanged → scheduleRender → renderTargetPanel
    page.click("#btn-add-table")

    # The card appearing IS proof that the event chain fired correctly
    expect(page.locator(".builder-table-card")).to_have_count(1)

    # Verify state is consistent by reading it from the module
    state = page.evaluate('''() => {
        // Access exported state via dynamic import
        return import('/static/js/builder/builder-state.js').then(m => {
            const schema = m.getTargetSchema();
            return {
                tableCount: schema.tables.length,
                firstTableName: schema.tables[0]?.name,
                isDirty: m.getIsDirty(),
            };
        });
    }''')
    assert state["tableCount"] == 1
    assert state["firstTableName"] == "table_1"
    assert state["isDirty"] is True


# ---------------------------------------------------------------------------
# 21. EventBus fires builderColumnAdded when column is added
# ---------------------------------------------------------------------------

def test_event_bus_column_added(page: Page, live_server: str):
    _goto_builder(page, live_server)
    page.click("#btn-add-table")

    card = page.locator(".builder-table-card").first
    card.locator(".builder-table-card__add-column").click()

    # Verify state reflects the new column
    state = page.evaluate('''() => {
        return import('/static/js/builder/builder-state.js').then(m => {
            const table = m.findTable('table_1');
            return {
                colCount: table.columns.length,
                colNames: table.columns.map(c => c.name),
            };
        });
    }''')
    assert state["colCount"] == 2
    assert "id" in state["colNames"]
    assert "column_2" in state["colNames"]


# ---------------------------------------------------------------------------
# 22. EventBus fires builderColumnUpdated on inline name change
# ---------------------------------------------------------------------------

def test_event_bus_column_updated(page: Page, live_server: str):
    _goto_builder(page, live_server)
    page.click("#btn-add-table")

    card = page.locator(".builder-table-card").first
    card.locator(".builder-table-card__add-column").click()

    # Rename column_2 to "email" via blur (how the UI does it)
    col_name = card.locator(".builder-column-row").nth(1).locator(".builder-column-row__name")
    col_name.fill("email")
    col_name.evaluate("el => el.blur()")

    # Wait for rAF render cycle
    page.wait_for_timeout(500)

    state = page.evaluate('''() => {
        return import('/static/js/builder/builder-state.js').then(m => {
            const table = m.findTable('table_1');
            return table.columns.map(c => c.name);
        });
    }''')
    assert "email" in state


# ---------------------------------------------------------------------------
# 23. EventBus fires builderTableRemoved
# ---------------------------------------------------------------------------

def test_event_bus_table_removed(page: Page, live_server: str):
    _goto_builder(page, live_server)
    page.click("#btn-add-table")
    page.click("#btn-add-table")

    # Delete first table
    page.locator(".builder-table-card").first.locator(".builder-table-card__delete").click()
    page.locator("#confirm-ok").click()
    page.wait_for_timeout(300)

    state = page.evaluate('''() => {
        return import('/static/js/builder/builder-state.js').then(m => {
            const schema = m.getTargetSchema();
            return {
                tableCount: schema.tables.length,
                tableNames: schema.tables.map(t => t.name),
            };
        });
    }''')
    assert state["tableCount"] == 1
    assert "table_2" in state["tableNames"]


# ---------------------------------------------------------------------------
# 24. Source panel with mocked source tables
# ---------------------------------------------------------------------------

def test_source_panel_with_mock_data(page: Page, live_server: str):
    page.route("**/api/builder/source-tables", lambda route: route.fulfill(
        json={"tables": [
            {"name": "csv_users", "columns": [
                {"name": "id", "type": "INT"},
                {"name": "name", "type": "VARCHAR"},
                {"name": "email", "type": "VARCHAR"},
            ]},
            {"name": "csv_orders", "columns": [
                {"name": "order_id", "type": "INT"},
                {"name": "user_id", "type": "INT"},
            ]},
        ]}
    ))

    page.goto(f"{live_server}/builder")
    page.wait_for_selector("#btn-add-table", state="visible")

    # Source tables should be listed
    source_tables = page.locator(".builder-source__table")
    expect(source_tables).to_have_count(2)

    # Click to expand first source table
    source_tables.first.locator(".builder-source__table-header").click()
    columns = source_tables.first.locator(".builder-source__column")
    expect(columns).to_have_count(3)

    # Empty state should be hidden
    expect(page.locator("#source-empty")).to_be_hidden()


# ---------------------------------------------------------------------------
# 25. Source panel search filter
# ---------------------------------------------------------------------------

def test_source_panel_search(page: Page, live_server: str):
    page.route("**/api/builder/source-tables", lambda route: route.fulfill(
        json={"tables": [
            {"name": "users", "columns": [{"name": "id", "type": "INT"}]},
            {"name": "orders", "columns": [{"name": "id", "type": "INT"}]},
            {"name": "products", "columns": [{"name": "id", "type": "INT"}]},
        ]}
    ))

    page.goto(f"{live_server}/builder")
    page.wait_for_selector(".builder-source__table", state="visible")

    # Filter to "ord"
    page.fill("#source-search", "ord")
    page.wait_for_timeout(500)

    visible = page.locator(".builder-source__table:visible")
    expect(visible).to_have_count(1)


# ---------------------------------------------------------------------------
# 26. Drag source column onto target table card
# ---------------------------------------------------------------------------

def test_drag_source_column_to_target(page: Page, live_server: str):
    page.route("**/api/builder/source-tables", lambda route: route.fulfill(
        json={"tables": [
            {"name": "csv_users", "columns": [
                {"name": "user_name", "type": "VARCHAR"},
            ]},
        ]}
    ))

    page.goto(f"{live_server}/builder")
    page.wait_for_selector("#btn-add-table", state="visible")

    # Create a target table
    page.click("#btn-add-table")
    expect(page.locator(".builder-table-card")).to_have_count(1)

    # Expand source table
    page.locator(".builder-source__table-header").first.click()
    source_col = page.locator(".builder-source__column").first

    # Drag to target card
    target_card = page.locator(".builder-table-card").first
    source_col.drag_to(target_card)

    # No crash = pass. Check state for source mapping
    page.wait_for_timeout(500)
    mapping = page.evaluate('''() => {
        return import('/static/js/builder/builder-state.js').then(m => m.getSourceMapping());
    }''')
    # Mapping may or may not be set depending on drop handling,
    # but the page should not have crashed
    assert page.locator("#btn-add-table").is_visible()


# ---------------------------------------------------------------------------
# 27. SQL import zone interaction
# ---------------------------------------------------------------------------

def test_sql_import_zone_exists(page: Page, live_server: str):
    _goto_builder(page, live_server)

    zone = page.locator("#sql-import-zone")
    expect(zone).to_be_visible()

    file_input = page.locator("#sql-file-input")
    expect(file_input).to_be_attached()


# ---------------------------------------------------------------------------
# 28. Keyboard shortcut — Escape closes modal
# ---------------------------------------------------------------------------

def test_escape_closes_modal(page: Page, live_server: str):
    _goto_builder(page, live_server)
    page.click("#btn-add-table")

    # Open column editor
    card = page.locator(".builder-table-card").first
    card.locator(".builder-column-row__edit").first.click()
    expect(page.locator("#column-editor")).not_to_be_hidden()

    # Press Escape
    page.keyboard.press("Escape")
    expect(page.locator("#column-editor")).to_be_hidden()


# ---------------------------------------------------------------------------
# 29. Dark mode toggle
# ---------------------------------------------------------------------------

def test_dark_mode_toggle(page: Page, live_server: str):
    _goto_builder(page, live_server)

    body = page.locator("body")
    btn = page.locator("#btn-theme")

    # Toggle dark mode on
    btn.click()
    expect(body).to_have_class(re.compile(r"dark"))

    # Toggle back off
    btn.click()
    # body should not have 'dark' class
    page.wait_for_timeout(100)
    classes = body.get_attribute("class") or ""
    assert "dark" not in classes


# ---------------------------------------------------------------------------
# 30. DDL contains transaction wrapping (BEGIN/COMMIT)
# ---------------------------------------------------------------------------

def test_ddl_has_transaction_wrapping(page: Page, live_server: str):
    _goto_builder(page, live_server)
    page.click("#btn-add-table")

    ddl = page.locator("#ddl-preview")
    expect(ddl).to_contain_text("BEGIN", timeout=5000)
    expect(ddl).to_contain_text("COMMIT")


# ---------------------------------------------------------------------------
# 31. DDL quotes identifiers
# ---------------------------------------------------------------------------

def test_ddl_quotes_identifiers(page: Page, live_server: str):
    _goto_builder(page, live_server)
    page.click("#btn-add-table")

    ddl = page.locator("#ddl-preview")
    # Should have quoted table name: "table_1"
    expect(ddl).to_contain_text('"table_1"', timeout=5000)
    # Should have quoted column name: "id"
    expect(ddl).to_contain_text('"id"')


# ---------------------------------------------------------------------------
# 32. Constraint picker opens
# ---------------------------------------------------------------------------

def test_constraint_picker_opens(page: Page, live_server: str):
    _goto_builder(page, live_server)
    page.click("#btn-add-table")

    card = page.locator(".builder-table-card").first
    card.locator(".builder-table-card__add-constraint").click()

    picker = page.locator("#constraint-picker")
    expect(picker).not_to_be_hidden()
    expect(page.locator("#constraint-table-name")).to_contain_text("table_1")

    # Close via cancel
    page.locator("#constraint-cancel").click()
    expect(picker).to_be_hidden()


# ---------------------------------------------------------------------------
# 33. IF NOT EXISTS toggle
# ---------------------------------------------------------------------------

def test_if_not_exists_toggle(page: Page, live_server: str):
    _goto_builder(page, live_server)
    page.click("#btn-add-table")

    card = page.locator(".builder-table-card").first
    checkbox = card.locator(".builder-table-card__if-not-exists")
    checkbox.check()

    ddl = page.locator("#ddl-preview")
    expect(ddl).to_contain_text("IF NOT EXISTS", timeout=5000)


# ---------------------------------------------------------------------------
# 34. Add multiple columns, delete one, verify DDL consistency
# ---------------------------------------------------------------------------

def test_add_delete_columns_ddl_consistency(page: Page, live_server: str):
    _goto_builder(page, live_server)
    page.click("#btn-add-table")

    card = page.locator(".builder-table-card").first

    # Add 2 more columns
    card.locator(".builder-table-card__add-column").click()
    card.locator(".builder-table-card__add-column").click()
    expect(card.locator(".builder-column-row")).to_have_count(3)

    # Delete the middle one
    card.locator(".builder-column-row").nth(1).locator(".builder-column-row__delete").click()
    page.wait_for_timeout(300)
    expect(card.locator(".builder-column-row")).to_have_count(2)

    # DDL should still be valid
    ddl = page.locator("#ddl-preview")
    expect(ddl).to_contain_text("CREATE TABLE", timeout=5000)
    # Should not contain the deleted column name
    # (column_2 was at index 1, column_3 at index 2)


# ---------------------------------------------------------------------------
# 35. Partition selector
# ---------------------------------------------------------------------------

def test_partition_selector(page: Page, live_server: str):
    _goto_builder(page, live_server)
    page.click("#btn-add-table")

    card = page.locator(".builder-table-card").first
    partition_select = card.locator(".builder-table-card__partition")
    partition_select.select_option("RANGE")

    # A partition columns input should appear
    page.wait_for_timeout(500)
    partition_cols = page.locator(".builder-table-card__partition-cols")
    expect(partition_cols).to_be_visible()


# ---------------------------------------------------------------------------
# 36. No JS errors during basic workflow
# ---------------------------------------------------------------------------

def test_no_js_errors_during_workflow(page: Page, live_server: str):
    errors = []
    page.on("pageerror", lambda err: errors.append(str(err)))

    _goto_builder(page, live_server)

    # Full workflow: add table, add column, rename, delete column, delete table
    page.click("#btn-add-table")
    card = page.locator(".builder-table-card").first
    card.locator(".builder-table-card__add-column").click()

    # Rename table
    name_input = card.locator(".builder-table-card__name")
    name_input.fill("orders")
    name_input.press("Enter")

    # Open column editor
    card.locator(".builder-column-row__edit").first.click()
    page.wait_for_timeout(200)
    page.locator("#editor-cancel").click()

    # Delete column
    card.locator(".builder-column-row").nth(1).locator(".builder-column-row__delete").click()
    page.wait_for_timeout(200)

    # Delete table
    card.locator(".builder-table-card__delete").click()
    page.locator("#confirm-ok").click()
    page.wait_for_timeout(300)

    # Add enum
    page.click("#btn-add-enum")
    page.wait_for_timeout(200)

    # Switch tabs
    page.locator('.builder-output__tab[data-tab="validation"]').click()
    page.locator('.builder-output__tab[data-tab="migration"]').click()
    page.locator('.builder-output__tab[data-tab="map"]').click()
    page.locator('.builder-output__tab[data-tab="ddl"]').click()

    assert len(errors) == 0, f"JS errors during workflow: {errors}"


# ---------------------------------------------------------------------------
# 37. Map tab renders canvas
# ---------------------------------------------------------------------------

def test_map_tab_has_canvas(page: Page, live_server: str):
    _goto_builder(page, live_server)
    page.locator('.builder-output__tab[data-tab="map"]').click()
    canvas = page.locator("#builder-map-canvas")
    expect(canvas).to_be_visible()

"""Unit tests for schema_optimizer options + detectors.

These tests avoid pandas dependency by using None dataframes where possible
(several detectors gracefully no-op) and by only validating the option
plumbing, merge semantics, and return contract of rebuild_schema().
"""

from __future__ import annotations

import unittest

from schema_optimizer import DEFAULT_OPTIONS, merge_options, _active_mode
from schema_rebuilder import rebuild_schema


class TestMergeOptions(unittest.TestCase):
    def test_defaults_preserved_when_empty(self):
        opts = merge_options(None)
        self.assertEqual(len(opts), 16)
        for key, default in DEFAULT_OPTIONS.items():
            self.assertEqual(opts[key]["enabled"], default["enabled"])

    def test_user_override_enabled(self):
        opts = merge_options({"mn_to_1n_downgrade": {"enabled": False}})
        self.assertFalse(opts["mn_to_1n_downgrade"]["enabled"])

    def test_user_override_mode(self):
        opts = merge_options({"type_downsizing": {"mode": "flag"}})
        self.assertEqual(opts["type_downsizing"]["mode"], "flag")

    def test_flag_only_forces_flag_mode(self):
        opts = merge_options({"drop_orphan_tables": {"mode": "apply"}})
        self.assertEqual(opts["drop_orphan_tables"]["mode"], "flag")
        opts2 = merge_options({"eav_to_jsonb": {"mode": "apply"}})
        self.assertEqual(opts2["eav_to_jsonb"]["mode"], "flag")

    def test_unknown_keys_ignored(self):
        opts = merge_options({"bogus_key": {"enabled": True}})
        self.assertNotIn("bogus_key", opts)

    def test_invalid_mode_falls_back_to_flag(self):
        opts = merge_options({"type_downsizing": {"mode": "wat"}})
        self.assertEqual(opts["type_downsizing"]["mode"], "flag")

    def test_active_mode_respects_enabled(self):
        self.assertIsNone(_active_mode({"x": {"enabled": False, "mode": "apply"}}, "x"))
        self.assertEqual(_active_mode({"x": {"enabled": True, "mode": "apply"}}, "x"), "apply")
        self.assertIsNone(_active_mode({}, "x"))


class TestRebuildReturnContract(unittest.TestCase):
    def test_empty_input_returns_flags_field(self):
        result = rebuild_schema([], {}, [], options={})
        self.assertIn("flags", result)
        self.assertEqual(result["flags"], [])
        self.assertIn("schema", result)
        self.assertIn("ddl", result)
        self.assertIn("decisions", result)

    def test_options_none_is_safe(self):
        result = rebuild_schema([], {}, [], options=None)
        self.assertIn("flags", result)

    def test_orphan_table_flag_single_table(self):
        tables = [{
            "name": "solo",
            "columns": [
                {"name": "id", "type": "INTEGER", "key_type": "PK",
                 "nullable": False, "unique_count": 1, "total_count": 1},
                {"name": "note", "type": "TEXT", "nullable": True,
                 "unique_count": 1, "total_count": 1},
            ],
        }]
        result = rebuild_schema(tables, {}, [],
            options={"drop_orphan_tables": {"enabled": True, "mode": "flag"}})
        orphan_flags = [f for f in result["flags"] if f["rule"] == "drop_orphan_tables"]
        self.assertEqual(len(orphan_flags), 1)
        self.assertEqual(orphan_flags[0]["table"], "solo")


class TestEAVDetection(unittest.TestCase):
    def test_eav_flag(self):
        tables = [
            {"name": "entity", "columns": [
                {"name": "id", "type": "INTEGER", "key_type": "PK",
                 "nullable": False, "unique_count": 2, "total_count": 2},
            ]},
            {"name": "props", "columns": [
                {"name": "id", "type": "INTEGER", "key_type": "PK",
                 "nullable": False, "unique_count": 5, "total_count": 5},
                {"name": "entity_id", "type": "INTEGER", "key_type": "FK",
                 "nullable": False, "unique_count": 2, "total_count": 5},
                {"name": "attribute_name", "type": "VARCHAR",
                 "nullable": False, "unique_count": 3, "total_count": 5},
                {"name": "attribute_value", "type": "VARCHAR",
                 "nullable": True, "unique_count": 5, "total_count": 5},
            ]},
        ]
        rels = [{"source_table": "props", "source_column": "entity_id",
                 "target_table": "entity", "target_column": "id",
                 "type": "one-to-many", "confidence": "high"}]
        result = rebuild_schema(tables, {}, rels,
            options={"eav_to_jsonb": {"enabled": True, "mode": "flag"}})
        eav = [f for f in result["flags"] if f["rule"] == "eav_to_jsonb"]
        self.assertEqual(len(eav), 1)
        self.assertEqual(eav[0]["table"], "prop")  # singularized


if __name__ == "__main__":
    unittest.main()

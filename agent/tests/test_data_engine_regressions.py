import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from tools.data_engine_tools import GenerateSeedSQLTool, PreviewDatasetTool  # noqa: E402
from utils.tool import ToolResult  # noqa: E402


class _FakeSplit:
    def __init__(self, rows):
        self._rows = rows

    def take(self, n):
        return self._rows[:n]


class _FakeDatasetDict:
    def __init__(self, rows):
        self._rows = rows

    def __getitem__(self, key):
        if key != "train":
            raise KeyError(key)
        return _FakeSplit(self._rows)


class DataEngineRegressionTests(unittest.TestCase):
    def test_resolve_field_mapping_case_insensitive(self):
        tool = GenerateSeedSQLTool()
        resolved = tool._resolve_field_mapping(
            field_mapping={"Name": "title", "Price": "price"},
            available_columns=["name", "price", "genres"],
        )
        self.assertEqual(resolved["Name"]["resolved_source"], "name")
        self.assertEqual(resolved["Price"]["resolved_source"], "price")
        self.assertTrue(resolved["Name"]["matched_case_insensitive"])

    def test_quality_gate_required_fields_case_insensitive(self):
        tool = GenerateSeedSQLTool()
        gate_config = tool._build_quality_gate_config(
            field_mapping={"Name": "title", "Price": "price"},
            quality_gate=None,
        )

        preview_data = ToolResult(
            success=True,
            data={
                "columns": {"name": "string", "price": "float"},
                "quality_summary": {
                    "completeness_score": 1.0,
                    "null_rate_by_column": {"name": 0.0, "price": 0.0},
                },
            },
        )

        with patch.object(PreviewDatasetTool, "execute", return_value=preview_data):
            result = tool._run_quality_gate(
                dataset_id="demo/dataset",
                subset=None,
                sample_size=5,
                gate_config=gate_config,
            )

        self.assertTrue(result["passed"])
        self.assertEqual(result["resolved_required_source_fields"]["Name"], "name")
        self.assertEqual(result["resolved_required_source_fields"]["Price"], "price")

    def test_execute_returns_resolved_field_mapping(self):
        tool = GenerateSeedSQLTool()
        fake_rows = [{"name": "Game A", "price": 19.9}]
        fake_datasets = types.ModuleType("datasets")
        fake_datasets.load_dataset = lambda **kwargs: _FakeDatasetDict(fake_rows)

        with tempfile.TemporaryDirectory() as td:
            output_file = str(Path(td) / "seed.sql")
            with patch.dict(sys.modules, {"datasets": fake_datasets}):
                with patch.object(GenerateSeedSQLTool, "_run_quality_gate", return_value={"passed": True, "violations": []}):
                    result = tool.execute(
                        dataset_id="demo/dataset",
                        table_name="games",
                        field_mapping={"Name": "title", "Price": "price"},
                        output_file=output_file,
                        limit=1,
                    )

            self.assertTrue(result.success)
            mapping = result.data["resolved_field_mapping"]
            self.assertEqual(mapping["Name"]["resolved_source"], "name")
            self.assertEqual(mapping["Price"]["resolved_source"], "price")

            sql = Path(output_file).read_text(encoding="utf-8")
            self.assertIn("INSERT INTO games (title, price)", sql)
            self.assertIn("'Game A'", sql)
            self.assertIn("19.9", sql)


if __name__ == "__main__":
    unittest.main()


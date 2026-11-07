"""真实题库与研究程序在三条执行路径上逐字、逐内存项差分。"""

from hashlib import sha256
import json
from pathlib import Path
import unittest

from src import pp3
from tests.test_execution import snapshot


FIXTURES = Path(__file__).resolve().parents[1] / "benchmarks" / "fixtures"


class FixtureTests(unittest.TestCase):
    def test_every_archived_example_matches_reference_and_expected_output(self):
        entries = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(len(entries), 20)
        builder = pp3.IRBuilder(pp3.std_register)
        for entry in entries:
            path = FIXTURES / entry["file"]
            self.assertEqual(sha256(path.read_text(encoding="ascii").encode("ascii")).hexdigest(), entry["sha256"])
            ir = builder.build(path.read_text(encoding="ascii"))
            for case in entry["cases"]:
                with self.subTest(program=entry["name"], case=case["name"]):
                    expected = snapshot(pp3.ReferenceRuntime(), ir, case["stdin"])
                    self.assertEqual(expected[2], case["stdout"])
                    self.assertIsNone(expected[3])
                    engines = ("auto", "specialized") + (() if pp3._native_unavailable() else ("native",))
                    for engine in engines:
                        self.assertEqual(snapshot(pp3.Runtime(engine=engine), ir, case["stdin"]), expected)


if __name__ == "__main__":
    unittest.main()

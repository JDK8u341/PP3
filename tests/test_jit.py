"""LLVM JIT 的原生小整数快路径、异常出口和退优化回归。"""

import importlib.util
import json
import os
from pathlib import Path
import unittest

from src import pp3, _executor
from tests.test_execution import snapshot


@unittest.skipUnless(os.environ.get("PP3_TEST_JIT") == "1" and _executor._native is not None
                     and importlib.util.find_spec("llvmlite"), "未启用 LLVM JIT 测试")
class JITTests(unittest.TestCase):
    def test_machine_code_matches_complete_state(self):
        from src.jit import compile_jit
        from benchmarks.run import execute
        for source, stdin in (
            ("&9223372036854775807 @+ ^1 @- @- ^1 &-9223372036854775808 @- ^1 @+ ^1", ""),
            ("&1 [ &9 ~80 &3 ^3 &0 ]", ""),
            ("@input [ @- ] @input_as_char @print_as_char &9 ~3 @input", "30\nA\nbad\n"),
            ("&1 [ &9 ~3 &77 #1 ]", ""),
        ):
            handles = pp3.IRBuilder(pp3.std_register).build(source)
            program = compile_jit(handles)
            expected = snapshot(pp3.ReferenceRuntime(), handles, stdin)
            _, actual = execute(pp3.Runtime(), handles, stdin, program)
            self.assertEqual((actual[0], actual[1], actual[2], actual[4]),
                             (expected[0], expected[1], expected[2], expected[4]))
            self.assertEqual(actual[3], None if expected[3] is None else (expected[3][0].__name__, str(expected[3][0](*expected[3][1]))))

    def test_arithmetic_summary_and_mutation(self):
        from src.jit import compile_jit
        handles = [pp3.Data(10**200), pp3.LoopBlock([pp3.SubSelf()])]
        program = compile_jit(handles)
        rt = pp3.Runtime()
        program.run(rt)
        self.assertEqual(rt.view, 0)
        handles[:] = [pp3.Data(73)]
        program.run(rt)
        self.assertEqual(rt.view, 73)

    def test_callback_changes_memory_before_throwing(self):
        from src.jit import compile_jit

        class Change(pp3.InPlaceHandler):
            def handle(self, rt):
                rt.memory[5] = rt.view
                rt.view = 77
                raise KeyError("host")

        handles = [pp3.Data(12), Change()]
        program = compile_jit(handles)
        rt = pp3.Runtime()
        with self.assertRaises(KeyError):
            program.run(rt)
        self.assertEqual(rt.view, 77)
        self.assertEqual(list(rt.memory.items()), [(5, 12)])

    def test_archived_programs_match_reference(self):
        from src.jit import compile_jit
        from benchmarks.run import execute
        root = Path(__file__).resolve().parents[1] / "benchmarks" / "fixtures"
        for entry in json.loads((root / "manifest.json").read_text(encoding="utf-8")):
            ir = pp3.IRBuilder(pp3.std_register).build((root / entry["file"]).read_text(encoding="ascii"))
            program = compile_jit(ir)
            for case in entry["cases"]:
                with self.subTest(program=entry["name"], case=case["name"]):
                    _, expected = execute(pp3.ReferenceRuntime(), ir, case["stdin"])
                    _, actual = execute(pp3.Runtime(), ir, case["stdin"], program)
                    self.assertEqual(actual, expected)

    def test_callback_deoptimizes_into_modified_body(self):
        from src.jit import compile_jit
        body = []

        class Change(pp3.InPlaceHandler):
            def handle(self, rt):
                body.append(pp3.Data(0))
                rt.view = 73

        body.append(Change())
        handles = [pp3.Data(1), pp3.LoopBlock(body), pp3.Data(9)]
        program = compile_jit(handles)
        rt = pp3.Runtime()
        program.run(rt)
        self.assertEqual(rt.view, 9)
        self.assertEqual(rt.execution_stats["deoptimizations"], 1)

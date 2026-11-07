"""机器码编译需要工具链；CI 显式开启，本地可通过 PP3_TEST_AOT=1 运行。"""

import os
from pathlib import Path
import unittest

from src import pp3, _executor
from tests.test_execution import snapshot


@unittest.skipUnless(os.environ.get("PP3_TEST_AOT") == "1" and _executor._native is not None,
                     "未启用机器码构建测试")
class AOTTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from src.aot import compile_aot
        cls.handles = pp3.IRBuilder(pp3.std_register).build(
            "@input $-1 &9223372036854775807 @+ ^1 @- #0 ~80 @input_as_char "
            "@print_as_char &6 [ @- @- ] &9 ^1 &33 @print_as_char")
        cls.program = compile_aot(cls.handles, Path(__file__).resolve().parents[1] / "build" / "aot-tests")

    def test_machine_code_matches_reference_across_inputs_and_errors(self):
        for stdin in ("42\nA\n", "-900000000000000000000000000000\n中\n", "bad\n", "0\n"):
            expected = snapshot(pp3.ReferenceRuntime(True), self.handles, stdin)
            native = pp3.Runtime(True)
            # 以相同捕获入口调用机器码，不替换 Runtime.run（否则会触发动态守卫）。
            from benchmarks.run import execute
            _, actual = execute(native, self.handles, stdin, self.program)
            normalized = (actual[0], actual[1], actual[2], actual[4])
            self.assertEqual(normalized, (expected[0], expected[1], expected[2], expected[4]))
            self.assertEqual(None if actual[3] is None else actual[3][0],
                             None if expected[3] is None else expected[3][0].__name__)

    def test_mutated_ir_uses_current_code(self):
        from benchmarks.run import execute
        last = self.handles[-2]
        original = last.data
        try:
            last.data = 35
            _, actual = execute(pp3.Runtime(True), self.handles, "42\nA\n", self.program)
            self.assertEqual(actual[2], "A#")
        finally:
            last.data = original

    def test_wrong_bytecode_is_rejected_without_native_crash(self):
        module = self.program.plan.module
        wrong = module.compile(((0, 1, 1, 0),))
        with self.assertRaisesRegex(ValueError, "does not match"):
            module.run(wrong, pp3.Runtime())

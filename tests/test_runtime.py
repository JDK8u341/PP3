"""覆盖原有运行器、寻址、循环及标准操作的行为。"""

from contextlib import redirect_stdout
from io import StringIO
import unittest
from unittest.mock import patch

from src import pp3


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.builder = pp3.IRBuilder(op_map=pp3.std_register)
        self.rt = pp3.Runtime()

    def run_code(self, code):
        self.rt.run(self.builder.build(code))

    def test_initial_state_and_default_memory(self):
        self.assertEqual(self.rt.view, 0)
        self.assertEqual(self.rt.memory[-123], 0)
        self.assertFalse(self.rt.can_direct_addressing)

    def test_runtime_memory_is_isolated(self):
        self.rt.memory[7] = 42
        self.assertEqual(pp3.Runtime().memory[7], 0)

    def test_clear_resets_state_and_preserves_configuration(self):
        self.rt = pp3.Runtime(can_direct_addressing=True)
        self.run_code("&7 $1")
        self.rt.clear()
        self.assertEqual(self.rt.view, 0)
        self.assertEqual(dict(self.rt.memory), {})
        self.assertTrue(self.rt.can_direct_addressing)

    def test_constants_and_increment_decrement(self):
        for number in [0, -1, 10**100, -(10**100)]:
            with self.subTest(number=number):
                self.run_code(f"&{number} @+ @+ @-")
                self.assertEqual(self.rt.view, number + 1)

    def test_integer_input_updates_view(self):
        for text, expected in [("0", 0), (" -42 ", -42), (str(10**100), 10**100)]:
            with self.subTest(text=text), patch("builtins.input", return_value=text):
                self.run_code("@input")
                self.assertEqual(self.rt.view, expected)

    def test_invalid_integer_input_does_not_replace_view(self):
        self.rt.view = 7
        with patch("builtins.input", return_value="abc"), self.assertRaises(ValueError):
            self.run_code("@input")
        self.assertEqual(self.rt.view, 7)

    def test_integer_input_propagates_eof(self):
        with patch("builtins.input", side_effect=EOFError), self.assertRaises(EOFError):
            self.run_code("@input")

    def test_print_preserves_view(self):
        output = StringIO()
        with redirect_stdout(output):
            self.run_code("&-42 @print @print")
        self.assertEqual(output.getvalue(), "-42\n-42\n")
        self.assertEqual(self.rt.view, -42)

    def test_direct_addressing_is_disabled_by_default(self):
        for instruction in ["#1", "$1", "%1"]:
            with self.subTest(instruction=instruction), self.assertRaises(ValueError):
                self.run_code(instruction)

    def test_direct_get_set_swap(self):
        self.rt = pp3.Runtime(can_direct_addressing=True)
        self.run_code("&7 $-2 &9 %-2")
        self.assertEqual(self.rt.view, 7)
        self.assertEqual(self.rt.memory[-2], 9)
        self.run_code("#-2")
        self.assertEqual(self.rt.view, 9)

    def test_indirect_get_set_swap_at_multiple_depths(self):
        for symbol in ["~", "^", "*"]:
            for depth, address, old_value in [(1, 7, 11), (2, 11, 13), (3, 13, 17)]:
                with self.subTest(symbol=symbol, depth=depth):
                    self.rt = pp3.Runtime()
                    self.rt.memory.update({7: 11, 11: 13, 13: 17})
                    self.run_code(f"&7 {symbol}{depth}")
                    expected_view = 7 if symbol == "^" else old_value
                    expected_memory = old_value if symbol == "~" else 7
                    self.assertEqual(self.rt.view, expected_view)
                    self.assertEqual(self.rt.memory[address], expected_memory)

    def test_indirect_self_loop(self):
        self.run_code("&-1 ^2 ^1 &-1 ~3")
        self.assertEqual(self.rt.view, -1)
        self.assertEqual(self.rt.memory[0], -1)

    def test_zero_skips_loop(self):
        self.run_code("&0 [ @+ ]")
        self.assertEqual(self.rt.view, 0)

    def test_loops_can_approach_zero_from_either_direction(self):
        for code in ["&3 [ @- ]", "&-3 [ @+ ]"]:
            with self.subTest(code=code):
                self.run_code(code)
                self.assertEqual(self.rt.view, 0)

    def test_nested_loops(self):
        self.rt = pp3.Runtime(can_direct_addressing=True)
        output = StringIO()
        with redirect_stdout(output):
            self.run_code("&2 $1 #1 [ @print #1 @- $1 &2 [ @- ] #1 ]")
        self.assertEqual(output.getvalue(), "2\n1\n")
        self.assertEqual(self.rt.view, 0)

    def test_handlers_mutate_runtime_and_return_values_are_ignored(self):
        class Mutate(pp3.InPlaceHandler):
            def handle(self, runtime):
                runtime.view *= 2
                return -999

        builder = pp3.IRBuilder({"double": Mutate})
        self.rt.run(builder.build("&6 @double"))
        self.assertEqual(self.rt.view, 12)

    def test_debug_counter_is_per_runtime_and_clearable(self):
        output = StringIO()
        with redirect_stdout(output):
            self.run_code("&7 @debug @debug")
        self.assertEqual(self.rt.memory["_debug_idx"], 2)
        self.assertEqual(self.rt.view, 7)
        self.assertIn("# Debug 1", output.getvalue())
        self.assertIn("# Debug 2", output.getvalue())
        self.rt.clear()
        self.assertEqual(self.rt.memory["_debug_idx"], 0)

    def test_original_indirect_assignment_example(self):
        self.run_code("&5 ^2 &6 ^3")
        self.assertEqual(self.rt.memory[5], 6)


if __name__ == "__main__":
    unittest.main()

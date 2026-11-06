"""验证字符取模、逐行缓冲、生命周期及与整数输入混用的语义。"""

from contextlib import redirect_stdout
from io import StringIO
import unittest
from unittest.mock import patch

from src import char_io, pp3


class CharacterIOTests(unittest.TestCase):
    def setUp(self):
        self.builder = pp3.IRBuilder(op_map=pp3.std_register)
        self.rt = pp3.Runtime()

    def run_code(self, code, runtime=None):
        (runtime if runtime is not None else self.rt).run(self.builder.build(code))

    def test_character_operations_are_in_standard_register(self):
        self.assertIs(pp3.std_register["input_as_char"], pp3.InputAsChar)
        self.assertIs(pp3.std_register["print_as_char"], pp3.PrintAsChar)
        self.assertIs(pp3.InputAsChar, char_io.InputAsChar)
        self.assertIs(pp3.PrintAsChar, char_io.PrintAsChar)

    def test_each_runtime_creates_its_own_standard_instances(self):
        other = pp3.Runtime()
        for name, operation in pp3.std_register.items():
            with self.subTest(name=name):
                self.assertIsInstance(self.rt.std_register[name], operation)
                self.assertIsNot(self.rt.std_register[name], other.std_register[name])

    def test_output_modulo_and_no_implicit_newline(self):
        values = [65, 10, 0, 255, 256, 321, -1, -256, -(10**100), 10**100]
        output = StringIO()
        with redirect_stdout(output):
            for value in values:
                self.run_code(f"&{value} @print_as_char")
                self.assertEqual(self.rt.view, value)
        self.assertEqual(output.getvalue(), "".join(chr(value % 256) for value in values))

    def test_one_line_is_consumed_character_by_character_by_one_instance(self):
        instruction = self.builder.build("@input_as_char")
        with patch("builtins.input", return_value="ABC") as read_line:
            values = []
            for _ in range(4):
                self.rt.run(instruction)
                values.append(self.rt.view)
        self.assertEqual(values, [65, 66, 67, 10])
        read_line.assert_called_once_with()

    def test_next_line_is_read_only_after_buffer_is_exhausted(self):
        instruction = self.builder.build("@input_as_char")
        with patch("builtins.input", side_effect=["AB", "C"]) as read_line:
            for _ in range(3):
                self.rt.run(instruction)
            self.assertEqual(read_line.call_count, 1)
            self.rt.run(instruction)
            self.assertEqual(self.rt.view, ord("C"))
            self.assertEqual(read_line.call_count, 2)

    def test_empty_lines_return_newline_instead_of_retrying(self):
        with patch("builtins.input", side_effect=["", "", "A"]) as read_line:
            self.run_code("@input_as_char")
            self.assertEqual(self.rt.view, 10)
            self.run_code("@input_as_char")
            self.assertEqual(self.rt.view, 10)
            self.assertEqual(read_line.call_count, 2)
            self.run_code("@input_as_char")
            self.assertEqual(self.rt.view, 65)

    def test_spaces_tabs_null_and_unicode_input_keep_their_code_points(self):
        text = " \t\x00\xff中😀"
        instruction = self.builder.build("@input_as_char")
        with patch("builtins.input", return_value=text):
            actual = []
            for _ in range(len(text) + 1):
                self.rt.run(instruction)
                actual.append(self.rt.view)
        self.assertEqual(actual, list(map(ord, text + "\n")))

    def test_different_builds_share_the_runtime_buffer(self):
        with patch("builtins.input", return_value="AB") as read_line:
            self.run_code("@input_as_char")
            self.run_code("@input_as_char")
        self.assertEqual(self.rt.view, 66)
        read_line.assert_called_once_with()

    def test_different_tokens_share_the_runtime_input_instance(self):
        instruction = self.builder.build("@input_as_char @input_as_char")
        with patch("builtins.input", side_effect=["AB", "XY"]) as read_line:
            self.rt.run(instruction)
        self.assertEqual(self.rt.view, ord("B"))
        self.assertEqual(read_line.call_count, 1)

    def test_buffer_is_preserved_between_run_calls(self):
        instruction = self.builder.build("@input_as_char")
        with patch("builtins.input", return_value="AB") as read_line:
            self.rt.run(instruction)
            self.rt.run(instruction)
        self.assertEqual(self.rt.view, 66)
        read_line.assert_called_once_with()

    def test_reused_ir_does_not_share_buffer_between_runtimes(self):
        instruction = self.builder.build("@input_as_char")
        other = pp3.Runtime()
        with patch("builtins.input", side_effect=["AB", "XY"]) as read_line:
            self.rt.run(instruction)
            other.run(instruction)
            self.rt.run(instruction)
            other.run(instruction)
        self.assertEqual(self.rt.view, ord("B"))
        self.assertEqual(other.view, ord("Y"))
        self.assertEqual(read_line.call_count, 2)

    def test_runtime_clear_discards_its_own_character_buffer(self):
        instruction = self.builder.build("@input_as_char")
        with patch("builtins.input", side_effect=["AB", "CD"]) as read_line:
            self.rt.run(instruction)
            self.rt.clear()
            self.rt.run(instruction)
        self.assertEqual(self.rt.view, ord("C"))
        self.assertEqual(read_line.call_count, 2)

    def test_clearing_one_runtime_does_not_clear_another(self):
        instruction = self.builder.build("@input_as_char")
        other = pp3.Runtime()
        with patch("builtins.input", side_effect=["AB", "XY"]) as read_line:
            self.rt.run(instruction)
            other.run(instruction)
            self.rt.clear()
            other.run(instruction)
        self.assertEqual(other.view, ord("Y"))
        self.assertEqual(read_line.call_count, 2)

    def test_loop_and_initial_input_share_one_buffer(self):
        output = StringIO()
        with patch("builtins.input", return_value="AB\x00") as read_line, redirect_stdout(output):
            self.run_code("@input_as_char [ @print_as_char @input_as_char ]")
        self.assertEqual(output.getvalue(), "AB")
        read_line.assert_called_once_with()

    def test_buffer_does_not_occupy_dsl_memory(self):
        with patch("builtins.input", return_value="AB"):
            self.run_code("@input_as_char")
        self.assertEqual(dict(self.rt.memory), {})

    def test_eof_keeps_view_and_can_be_retried(self):
        instruction = self.builder.build("@input_as_char")
        self.rt.view = 123
        with patch("builtins.input", side_effect=EOFError), self.assertRaises(EOFError):
            self.rt.run(instruction)
        self.assertEqual(self.rt.view, 123)
        with patch("builtins.input", return_value="A"):
            self.rt.run(instruction)
        self.assertEqual(self.rt.view, 65)

    def test_buffer_is_drained_before_eof_is_reported(self):
        instruction = self.builder.build("@input_as_char")
        with patch("builtins.input", side_effect=["A", EOFError]) as read_line:
            self.rt.run(instruction)
            self.rt.run(instruction)
            self.assertEqual(self.rt.view, 10)
            self.assertEqual(read_line.call_count, 1)
            with self.assertRaises(EOFError):
                self.rt.run(instruction)

    def test_integer_input_does_not_consume_character_buffer(self):
        instruction = self.builder.build("@input_as_char")
        with patch("builtins.input", side_effect=["AB", "42", "CD"]) as read_line:
            self.rt.run(instruction)
            self.run_code("@input")
            self.assertEqual(self.rt.view, 42)
            self.rt.run(instruction)
            self.assertEqual(self.rt.view, ord("B"))
            self.rt.run(instruction)
            self.assertEqual(self.rt.view, 10)
            self.rt.run(instruction)
            self.assertEqual(self.rt.view, ord("C"))
        self.assertEqual(read_line.call_count, 3)

    def test_actual_stdin_round_trip_including_empty_and_final_lines(self):
        expected = "AB\n\nC\n"
        output = StringIO()
        instruction = self.builder.build("@input_as_char @print_as_char")
        with patch("sys.stdin", StringIO("AB\n\nC")), redirect_stdout(output):
            for _ in expected:
                self.rt.run(instruction)
            with self.assertRaises(EOFError):
                self.rt.run(self.builder.build("@input_as_char"))
        self.assertEqual(output.getvalue(), expected)

    def test_independent_module_can_be_imported_before_runtime(self):
        # 在新进程中从扩展模块开始导入，防止共同基类造成循环导入
        import subprocess
        import sys
        from pathlib import Path

        result = subprocess.run(
            [sys.executable, "-B", "-c", "from src.char_io import register; from src.pp3 import Runtime; assert set(register) <= Runtime().std_register.keys()"],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_integer_and_character_output_can_be_mixed(self):
        output = StringIO()
        with redirect_stdout(output):
            self.run_code("&65 @print_as_char @print &10 @print_as_char")
        self.assertEqual(output.getvalue(), "A65\n\n")


if __name__ == "__main__":
    unittest.main()

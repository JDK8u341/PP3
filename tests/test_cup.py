"""覆盖 cup 双端操作、整数运算、异常原子性及状态隔离。"""

from collections import deque
import unittest

from src import cup, pp3


class CupTests(unittest.TestCase):
    def setUp(self):
        self.builder = pp3.IRBuilder(op_map={**pp3.std_register, **cup.register})
        self.rt = pp3.Runtime()
        self.run_code("@init_cup")

    def run_code(self, code):
        self.rt.run(self.builder.build(code))

    def test_push_and_pop_both_ends(self):
        self.run_code("&1 @push &2 @push &3 @push_left")
        self.assertEqual(list(self.rt.memory["_cup"]), [3, 1, 2])
        self.run_code("@pop_left")
        self.assertEqual(self.rt.view, 3)
        self.run_code("@pop")
        self.assertEqual(self.rt.view, 2)
        self.assertEqual(list(self.rt.memory["_cup"]), [1])

    def test_push_preserves_view(self):
        self.run_code("&7 @push @push_left")
        self.assertEqual(self.rt.view, 7)

    def test_reinitialization_and_clear(self):
        self.run_code("&1 @push @init_cup")
        self.assertEqual(list(self.rt.memory["_cup"]), [])
        self.rt.clear()
        self.assertNotIn("_cup", self.rt.memory)

    def test_arithmetic_order_and_remaining_stack(self):
        for operation, result in [("add", 9), ("sub", 5), ("mul", 14), ("div", 3)]:
            with self.subTest(operation=operation):
                self.rt.memory["_cup"] = deque([99, 7, 2])
                self.run_code(f"@{operation}")
                self.assertEqual(self.rt.view, result)
                self.assertEqual(list(self.rt.memory["_cup"]), [99])

    def test_integer_division_truncates_toward_zero(self):
        for left, right, result in [
            (5, 2, 2), (-5, 2, -2), (5, -2, -2), (-5, -2, 2),
            (-1, 2, 0), (1, -2, 0), (0, -2, 0), (4, 2, 2),
        ]:
            with self.subTest(left=left, right=right):
                self.run_code(f"&{left} @push &{right} @push @div")
                self.assertEqual(self.rt.view, result)
                self.assertIsInstance(self.rt.view, int)

    def test_large_integer_division_does_not_use_floating_point(self):
        left = 10**400 + 5
        right = 3
        for sign_left, sign_right in [(1, 1), (-1, 1), (1, -1), (-1, -1)]:
            with self.subTest(sign_left=sign_left, sign_right=sign_right):
                self.run_code(f"&{sign_left * left} @push &{sign_right * right} @push @div")
                self.assertEqual(self.rt.view, sign_left * sign_right * (left // right))

    def test_binary_underflow_preserves_stack_and_view(self):
        for operation in ["add", "sub", "mul", "div"]:
            for values in [[], [42]]:
                with self.subTest(operation=operation, values=values):
                    self.rt.memory["_cup"] = deque(values)
                    self.rt.view = 123
                    with self.assertRaises(IndexError):
                        self.run_code(f"@{operation}")
                    self.assertEqual(list(self.rt.memory["_cup"]), values)
                    self.assertEqual(self.rt.view, 123)

    def test_division_by_zero_preserves_stack_and_view(self):
        self.rt.memory["_cup"] = deque([99, 7, 0])
        self.rt.view = 123
        with self.assertRaises(ZeroDivisionError):
            self.run_code("@div")
        self.assertEqual(list(self.rt.memory["_cup"]), [99, 7, 0])
        self.assertEqual(self.rt.view, 123)

    def test_pop_underflow_preserves_view(self):
        for operation in ["pop", "pop_left"]:
            with self.subTest(operation=operation):
                self.rt.view = 123
                with self.assertRaises(IndexError):
                    self.run_code(f"@{operation}")
                self.assertEqual(self.rt.view, 123)

    def test_stack_is_isolated_between_runtimes(self):
        other = pp3.Runtime()
        other.run(self.builder.build("@init_cup &9 @push"))
        self.assertEqual(list(self.rt.memory["_cup"]), [])
        self.assertEqual(list(other.memory["_cup"]), [9])


if __name__ == "__main__":
    unittest.main()

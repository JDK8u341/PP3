"""验证文本分词、严格 token 列表及循环括号检查。"""

import unittest

from src import pp3


class BuilderTests(unittest.TestCase):
    def setUp(self):
        self.builder = pp3.IRBuilder(op_map=pp3.std_register)

    def test_string_whitespace_is_split_before_parsing(self):
        rt = pp3.Runtime()
        rt.run(self.builder.build("\n\t &2 \r\n [ \t @- \n ] \n"))
        self.assertEqual(rt.view, 0)

    def test_strict_list_matches_string(self):
        for source in ["&-2 [ @+ ]", ["&-2", "[", "@+", "]"]]:
            with self.subTest(source=source):
                rt = pp3.Runtime()
                rt.run(self.builder.build(source))
                self.assertEqual(rt.view, 0)

    def test_empty_source(self):
        for source in ["", " \t\n", []]:
            with self.subTest(source=source):
                self.assertEqual(self.builder.build(source), [])

    def test_list_tokens_must_not_contain_whitespace(self):
        for token in ["", " ", " &0", "&0 ", " [ ", "& 0", "\t@+", "\n"]:
            with self.subTest(token=token), self.assertRaises(ValueError):
                self.builder.build([token])

    def test_list_tokens_must_be_strings(self):
        for token in [None, 1, [], b"&0"]:
            with self.subTest(token=token), self.assertRaises(TypeError):
                self.builder.build([token])

    def test_token_list_is_not_modified(self):
        tokens = ["&2", "[", "@-", "]"]
        original = tokens.copy()
        self.builder.build(tokens)
        self.assertEqual(tokens, original)

    def test_nested_bracket_pairs(self):
        self.assertEqual(self.builder.match_brackets(["[", "[", "]", "]"]), {1: 2, 0: 3})

    def test_unmatched_brackets_raise_value_error(self):
        for source in ["[", "]", "[ [ ]", "[ ] ]", "] ["]:
            with self.subTest(source=source), self.assertRaises(ValueError):
                self.builder.build(source)

    def test_nested_and_empty_blocks(self):
        handles = self.builder.build("[ [ ] ] [ ]")
        self.assertEqual(len(handles), 2)
        self.assertIsInstance(handles[0].body[0], pp3.LoopBlock)
        self.assertEqual(handles[1].body, [])

    def test_indirect_depth_must_be_positive(self):
        for symbol in ["~", "^", "*"]:
            for depth in [0, -1]:
                with self.subTest(symbol=symbol, depth=depth), self.assertRaises(ValueError):
                    self.builder.build(f"{symbol}{depth}")

    def test_malformed_numeric_arguments(self):
        for symbol in ["&", "#", "$", "%", "~", "^", "*"]:
            for suffix in ["", "abc", "1.5"]:
                with self.subTest(symbol=symbol, suffix=suffix), self.assertRaises(ValueError):
                    self.builder.build(symbol + suffix)

    def test_unregistered_operation_is_rejected(self):
        with self.assertRaises(KeyError):
            self.builder.build("@not_registered")

    def test_default_operation_map_is_not_shared(self):
        first = pp3.IRBuilder()
        second = pp3.IRBuilder()
        first.op_map["custom"] = pp3.Print
        self.assertNotIn("custom", second.op_map)


if __name__ == "__main__":
    unittest.main()

"""原生整段执行、宿主边界和机器整数极值的差分回归。"""

from collections import defaultdict
from io import StringIO
import subprocess
import sys
import textwrap
import random
import unittest
from unittest.mock import patch

from src import pp3, _executor
from tests.test_execution import snapshot


@unittest.skipIf(_executor._native is None, "未构建可选原生扩展")
class NativeTests(unittest.TestCase):
    def compare(self, code, stdin="", memory=None):
        builder = pp3.IRBuilder(pp3.std_register)
        # 足够长的入口强制经过整段执行器，而不是只测原来的纯循环。
        handles = [pp3.Data(0) for _ in range(17)] + builder.build(code)
        reference, native = pp3.ReferenceRuntime(True), pp3.Runtime(True, engine="native")
        for rt in (reference, native):
            if memory is not None:
                rt.memory.update(memory)
        expected = snapshot(reference, handles, stdin)
        self.assertEqual(snapshot(native, handles, stdin), expected)
        self.assertEqual(native.execution_stats["compiled_programs"], 1)
        return native, expected

    def test_native_standard_io_and_error_prefix(self):
        self.compare("@input_as_char @print_as_char @input @print @input_as_char @print_as_char", "AB\n-42\n")
        self.compare("&9 ~3 &65 @print_as_char @input", "bad\n")
        self.compare("@input_as_char @print_as_char @input_as_char @print_as_char @input_as_char", "X")
        self.compare("&-257 @print_as_char &256 @print_as_char &100000000000000000000000000000000000000000 @print_as_char")

    def test_int64_overflow_roundtrip_and_graph_invalidation(self):
        for value in (2**63 - 1, -(2**63), 2**63, -(2**63) - 1, 10**200, -(10**200)):
            self.compare(f"&{value} @+ ^1 @- ^1 @- ^1 @+ @print")
        self.compare("&1 ~3 &8 $2 &1 ~3 &9 %2 &1 ~3", memory={1: 2, 2: 3, 3: 1})

    def test_long_walk_preserves_missing_order_and_final_write(self):
        for instruction in ("~", "^", "*"):
            for depth in (64, 65, 66, 93, 101):
                self.compare(f"&7 {instruction}{depth}")
                self.compare(f"&1 {instruction}{depth}", memory={1: 2, 2: 3, 3: 2})

    def test_modifying_active_lists_resumes_at_exact_index(self):
        def case(runtime):
            outer = [pp3.Data(0) for _ in range(17)]
            body = []

            class Change(pp3.InPlaceHandler):
                def handle(self, rt):
                    body[:] = [self, pp3.Data(77), pp3.Set(-3), pp3.Data(0)]
                    outer.append(pp3.Data(99))
                    rt.view = 123

            body.append(Change())
            outer.extend([pp3.Data(1), pp3.LoopBlock(body), pp3.Set(-4)])
            return snapshot(runtime, outer)

        reference = case(pp3.ReferenceRuntime(True))
        native = pp3.Runtime(True, engine="native")
        self.assertEqual(case(native), reference)
        self.assertEqual(native.execution_stats["deoptimizations"], 1)

    def test_callbacks_replace_memory_reenter_and_raise(self):
        def case(runtime):
            class Change(pp3.InPlaceHandler):
                def handle(self, rt):
                    rt.memory = defaultdict(int, {"seen": (rt.view, list(rt.memory.items()))})
                    rt.run([pp3.Data(11), pp3.IndirectSet(1)])
                    rt.view = 73
                    raise ValueError("callback")

            handles = [pp3.Data(0) for _ in range(17)] + [pp3.Data(5), pp3.IndirectGet(3), Change()]
            return snapshot(runtime, handles)

        self.assertEqual(case(pp3.ReferenceRuntime()), case(pp3.Runtime(engine="native")))

    def test_cached_program_observes_standard_handler_change(self):
        handles = [pp3.Data(0) for _ in range(17)] + [pp3.Data(4), pp3.LoopBlock([pp3.SubSelf()])]
        rt = pp3.Runtime(engine="native")
        rt.run(handles)
        rt._std_handlers[pp3.SubSelf].handle = lambda rt: setattr(rt, "view", rt.view - 2)
        rt.run(handles)
        self.assertEqual(rt.view, 0)
        self.assertEqual(rt.execution_stats["compiled_programs"], 1)

    def test_io_stream_callback_sees_state_and_changes_ir(self):
        def case(runtime):
            handles = [pp3.Data(0) for _ in range(17)]
            last = pp3.Data(1)
            handles.extend([pp3.Data(65), pp3.IndirectSet(1), pp3.PrintAsChar(), last])
            observations = []

            class Stream(StringIO):
                def write(self, text):
                    observations.append((runtime.view, list(runtime.memory.items()), text))
                    last.data = 7
                    runtime.memory[100] = 91
                    runtime.view = 123
                    return super().write(text)

            output = Stream()
            with patch("sys.stdout", output):
                runtime.run(handles)
            return observations, runtime.view, list(runtime.memory.items()), output.getvalue()

        self.assertEqual(case(pp3.ReferenceRuntime()), case(pp3.Runtime(engine="native")))

    def test_seeded_programs_cross_host_boundaries(self):
        rng = random.Random(490172)
        for _ in range(80):
            operations = []
            for index in range(32):
                operations.append(rng.choice([f"&{rng.randrange(-8, 9)}", "@+", "@-", "~3", "^3", "*2", "@print"]))
            self.compare(" ".join(operations))

    def test_custom_buffer_boolean_can_replace_buffer(self):
        from collections import deque

        def case(runtime):
            target = runtime.std_register["input_as_char"]

            class Buffer:
                def __bool__(self):
                    target.buffer = deque()
                    return False

            target.buffer = Buffer()
            handles = [pp3.Data(0) for _ in range(17)] + [pp3.InputAsChar(), pp3.Print()]
            return snapshot(runtime, handles, "X\n")

        self.assertEqual(case(pp3.ReferenceRuntime()), case(pp3.Runtime(engine="native")))

    def test_cyclic_handler_runtime_can_be_collected(self):
        import gc
        import weakref

        class Callback(pp3.InPlaceHandler):
            def handle(self, rt):
                self.runtime = rt

        rt = pp3.Runtime(engine="native")
        ir = [pp3.Data(0) for _ in range(17)] + [Callback()]
        rt.run(ir)
        reference = weakref.ref(rt)
        del ir, rt
        gc.collect()
        self.assertIsNone(reference())

    def test_function_code_replacement_is_not_bypassed(self):
        original = pp3.ReferenceRuntime.get.__code__

        def replacement(self, place):
            self.view = 73

        try:
            pp3.ReferenceRuntime.get.__code__ = replacement.__code__
            ir = [pp3.Data(0) for _ in range(17)] + [pp3.Data(3), pp3.IndirectGet(2)]
            self.assertEqual(snapshot(pp3.ReferenceRuntime(), ir), snapshot(pp3.Runtime(engine="native"), ir))
        finally:
            pp3.ReferenceRuntime.get.__code__ = original

    def test_nonterminating_math_loops_remain_interruptible(self):
        source = textwrap.dedent('''
            import _thread, threading, time
            from src import pp3
            rt = pp3.Runtime(engine="native")
            ir = pp3.IRBuilder(pp3.std_register).build(SOURCE)
            def stop():
                time.sleep(0.05)
                _thread.interrupt_main()
            threading.Thread(target=stop, daemon=True).start()
            try:
                rt.run(ir)
            except KeyboardInterrupt:
                assert rt.view != 0
                print("interrupted")
            else:
                raise AssertionError("nonterminating loop was removed")
        ''')
        for code in ("&1 [ @- @- ]", "&1 [ @+ ]", "&1 [ @+ @- ]", "&1 [ ]"):
            result = subprocess.run([sys.executable, "-X", "faulthandler", "-c", "SOURCE=" + repr(code) + "\n" + source],
                                    text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("interrupted", result.stdout)

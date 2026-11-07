"""高速执行器与保留的原版逐项差分；同时核对错误前的完整状态。"""

from collections import defaultdict
from contextlib import redirect_stdout
import copy
from io import StringIO
import os
import random
import sys
import unittest
from unittest.mock import patch

from src import cup, pp3


def snapshot(runtime, handles, stdin=""):
    output = StringIO()
    error = None
    with patch("sys.stdin", StringIO(stdin)), redirect_stdout(output):
        try:
            runtime.run(handles)
        except Exception as exception:
            error = (type(exception), exception.args)
    buffer = tuple(runtime.std_register["input_as_char"].buffer)
    return runtime.view, list(runtime.memory.items()), output.getvalue(), error, buffer


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.builder = pp3.IRBuilder(pp3.std_register)

    def compare(self, source, stdin="", *, memory=None, view=0, direct=False):
        results = []
        engines = ("reference", "auto", "specialized") + (() if pp3._native_unavailable() else ("native",))
        for engine in engines:
            rt = pp3.Runtime(direct, engine=engine)
            rt.view = view
            if memory is not None:
                rt.memory.update(copy.deepcopy(memory))
            ir = self.builder.build(source)
            results.append(snapshot(rt, ir, stdin))
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0], results[2])
        if len(results) > 3:
            self.assertEqual(results[0], results[3])
        return results[0]

    def test_hot_loop_uses_specialization_and_global_ir_cache(self):
        ir = self.builder.build("&10000 [ @- ]")
        first = pp3.Runtime()
        first.run(ir)
        self.assertEqual(first.view, 0)
        self.assertEqual(first.execution_stats["compiled_loops"], 1)
        other = pp3.Runtime()
        other.run(ir)
        self.assertEqual(other.execution_stats["cache_hits"], 1)
        self.assertEqual(other.view, 0)

    def test_short_loop_avoids_compilation(self):
        rt = pp3.Runtime()
        rt.run(self.builder.build("&3 [ @- ]"))
        self.assertEqual(rt.execution_stats["compiled_loops"], 0)
        rt.run(self.builder.build("&0 [ ~99 ]"))
        self.assertEqual(dict(rt.memory), {})
        rt.run(self.builder.build("&9 [ @- ]"))
        self.assertEqual(rt.execution_stats["compiled_loops"], 0)

    def test_reference_class_and_engine_agree(self):
        ir = self.builder.build("&25 [ @- ]")
        self.assertEqual(snapshot(pp3.ReferenceRuntime(), ir), snapshot(pp3.Runtime(engine="reference"), ir))

    def test_big_integer_negative_address_and_cycles(self):
        self.compare("&-100 [ @+ ]")
        self.compare("&100 [ &-5 ~25 &-5 ^25 &0 ]", memory={-5: -5})
        self.compare("&100 [ &-5 *26 &0 ]", memory={-5: -6, -6: -5})
        large = 10**400
        self.compare(f"&20 [ &{large} @+ @- ^1 ~1 &0 ]")

    def test_native_graph_cycle_skips_large_indirect_depth(self):
        if pp3._native_unavailable():
            self.skipTest("原生扩展未构建")
        runtime = pp3.Runtime(engine="native")
        runtime.view = 1
        runtime.memory.update({1: 2, 2: 1})
        depth = 10**12 + 1
        runtime.run(self.builder.build(f"[ ~{depth} ^1 &0 ]"))
        self.assertEqual(runtime.view, 0)
        self.assertEqual(list(runtime.memory.items()), [(1, 2), (2, 2)])

    def test_native_engine_requires_built_extension(self):
        if not pp3._native_unavailable():
            self.skipTest("原生扩展已构建")
        with self.assertRaisesRegex(RuntimeError, "未安装"):
            pp3.Runtime(engine="native").run([])

    def test_native_extension_is_built_when_required(self):
        if os.environ.get("PP3_REQUIRE_NATIVE") == "1":
            self.assertFalse(pp3._native_unavailable())

    def test_native_arithmetic_summary_keeps_python_integer_range(self):
        if pp3._native_unavailable():
            self.skipTest("原生扩展未构建")
        runtime = pp3.Runtime(engine="native")
        runtime.view = 10**200
        runtime.run(self.builder.build("[ @- ]"))
        self.assertEqual(runtime.view, 0)
        self.assertGreater(runtime.execution_stats["native_runs"], 0)

    def test_memory_insertion_order_and_missing_reads_are_preserved(self):
        state = self.compare("&20 [ &7 ~5 &8 ^4 &9 *3 &0 ]")
        self.assertEqual(state[0], 0)
        self.assertEqual(state[1][:2], [(7, 0), (0, 8)])

    def test_direct_permission_checks_occur_only_when_reached(self):
        self.compare("&0 [ #1 ] &7")
        self.compare("&1 [ &7 #42 ]")
        self.compare("&12 $1 #1 [ @- $1 #1 ]", direct=True)

    def test_exception_commits_view_and_defaultdict_prefix(self):
        state = self.compare("&1 [ &9 ~3 &77 #1 ]")
        self.assertEqual(state[0], 77)
        self.assertEqual(state[1], [(9, 0), (0, 0)])
        self.assertIs(state[3][0], ValueError)

    def test_ir_mutation_invalidates_the_compiled_function(self):
        ir = self.builder.build("&24 [ @- ]")
        rt = pp3.Runtime(engine="specialized")
        rt.run(ir)
        ir[0].data = -24
        ir[1].body[:] = [pp3.AddSelf()]
        rt.run(ir)
        self.assertEqual(rt.view, 0)
        self.assertEqual(rt.execution_stats["compiled_loops"], 2)
        ir[1].body[:] = [pp3.Data(0)]
        rt.view = 9
        rt.run(ir[1:])
        self.assertEqual(rt.view, 0)

    def test_mutating_depth_and_memory_operation_is_observed(self):
        loop = pp3.LoopBlock([pp3.Data(-1), pp3.IndirectGet(2), pp3.Data(0)])
        rt = pp3.Runtime(engine="specialized")
        rt.memory[-1] = 7
        rt.view = 1
        rt.run([loop])
        loop.body[1].depth = 1
        loop.body[1].h_type = pp3.MemHandlerType.Set
        rt.view = 1
        rt.run([loop])
        self.assertEqual(rt.memory[-1], -1)

    def test_custom_handler_sees_state_reenters_and_can_replace_memory(self):
        class Callback(pp3.InPlaceHandler):
            def handle(self, runtime):
                runtime.observations.append((runtime.view, list(runtime.memory.items())))
                runtime.memory = defaultdict(int, {20: 3})
                runtime.run([pp3.Data(30), pp3.LoopBlock([pp3.SubSelf()])])
                runtime.view = 0
                return 999

        for engine in ("auto", "specialized"):
            reference = pp3.ReferenceRuntime()
            fast = pp3.Runtime(engine=engine)
            reference.observations, fast.observations = [], []
            ir = [pp3.Data(20), pp3.LoopBlock([pp3.SubSelf()]), Callback()]
            self.assertEqual(snapshot(reference, ir), snapshot(fast, ir))
            self.assertEqual(reference.observations, fast.observations)

    def test_handler_can_mutate_the_active_body(self):
        for engine in ("reference", "auto", "specialized"):
            body = []

            class Change(pp3.InPlaceHandler):
                def handle(self, runtime):
                    body.append(pp3.Data(0))
                    runtime.view = 4

            body.append(Change())
            rt = pp3.Runtime(engine=engine)
            rt.view = 1
            rt.run([pp3.LoopBlock(body)])
            self.assertEqual(rt.view, 0)

    def test_overridden_standard_operation_and_memory_dispatch_are_used(self):
        for engine in ("reference", "auto", "specialized"):
            rt = pp3.Runtime(engine=engine)

            def decrement_twice(runtime):
                runtime.view -= 2

            rt._std_handlers[pp3.SubSelf].handle = decrement_twice
            rt.run(self.builder.build("&40 [ @- ]"))
            self.assertEqual(rt.view, 0)
            rt.mem_handler_map[pp3.MemHandlerType.Get] = lambda address: setattr(rt, "view", 0)
            rt.view = 20
            rt.run(self.builder.build("[ ~1 ]"))
            self.assertEqual(rt.view, 0)

    def test_replaced_mapping_and_numeric_subclass_are_not_specialized(self):
        class Memory(defaultdict):
            def __getitem__(self, key):
                self.reads += 1
                return super().__getitem__(key)

        class Number(int):
            def __sub__(self, other):
                return Number(int(self) - other)

        rt = pp3.Runtime(engine="specialized")
        rt.memory = Memory(int)
        rt.memory.reads = 0
        rt.view = Number(12)
        rt.run([pp3.LoopBlock([pp3.SubSelf()])])
        self.assertEqual(rt.view, 0)
        self.assertEqual(rt.execution_stats["specialized_runs"], 0)
        rt.view = 1
        rt.run(self.builder.build("[ &5 ~3 &0 ]"))
        self.assertEqual(rt.memory.reads, 3)

    def test_subclass_can_observe_recursive_run_calls(self):
        class Observe(pp3.Runtime):
            def run(self, handles):
                self.calls += 1
                return super().run(handles)

        rt = Observe()
        rt.calls = 0
        rt.run(self.builder.build("&20 [ @- ]"))
        self.assertEqual(rt.calls, 21)
        self.assertEqual(rt.execution_stats["compiled_loops"], 0)

    def test_instance_run_override_keeps_recursive_callbacks(self):
        rt = pp3.Runtime(engine="specialized")
        original = rt.run
        calls = []

        def observe(handles):
            calls.append(handles)
            return original(handles)

        rt.run = observe
        rt.run(self.builder.build("&20 [ @- ]"))
        self.assertEqual(rt.view, 0)
        self.assertEqual(len(calls), 21)
        self.assertEqual(rt.execution_stats["specialized_runs"], 0)

    def test_trace_hook_disables_specialized_execution(self):
        rt = pp3.Runtime(engine="specialized")
        old = sys.gettrace()
        try:
            sys.settrace(lambda frame, event, arg: None)
            rt.run(self.builder.build("&20 [ @- ]"))
        finally:
            sys.settrace(old)
        self.assertEqual(rt.view, 0)
        self.assertEqual(rt.execution_stats["specialized_runs"], 0)

    def test_cup_io_and_exceptions_match_reference(self):
        self.builder = pp3.IRBuilder({**pp3.std_register, **cup.register})
        self.compare("&20 [ @- ] @init_cup &-5 @push &2 @push @div @print")
        self.compare("@init_cup &9 @push &0 @push &20 [ @- ] @div")
        self.compare("@input_as_char &20 [ @- ] @input @input_as_char @print_as_char", "AB\n42\n")
        self.compare("&99 @input", "x\n")
        self.compare("&99 @input_as_char", "")

    def test_partial_output_and_debug_memory_order_match(self):
        self.compare("&20 [ @- ] &5 ~3 @debug &65 @print_as_char @input", "bad\n")

    def test_generated_bounded_programs_match_full_state(self):
        rng = random.Random(20261107)
        for index in range(160):
            body = []
            for _ in range(rng.randrange(1, 12)):
                instruction = rng.choice(["data", "add", "sub", "~", "^", "*"])
                if instruction == "data":
                    body.append(f"&{rng.randint(-8, 8)}")
                elif instruction == "add":
                    body.append("@+")
                elif instruction == "sub":
                    body.append("@-")
                else:
                    body.append(f"{instruction}{rng.randint(1, 16)}")
            # 固定出口保证随机内存图不会使测试永久循环。
            source = "&1 [ " + " ".join(body) + " &0 ]"
            memory = {key: rng.randint(-8, 8) for key in range(-8, 9)}
            with self.subTest(index=index):
                self.compare(source, memory=memory)

    def test_malformed_unreachable_manual_ir_is_not_eagerly_rejected(self):
        loop = pp3.LoopBlock([object()])
        for engine in ("reference", "auto", "specialized"):
            rt = pp3.Runtime(engine=engine)
            rt.run([loop])
            rt.view = 1
            with self.assertRaises(AttributeError):
                rt.run([loop])

    def test_mutated_malformed_ir_fails_at_its_original_position(self):
        for engine in ("reference", "auto", "specialized"):
            rt = pp3.Runtime(engine=engine)
            broken = pp3.IndirectGet(1)
            broken.h_type = []
            loop = pp3.LoopBlock([pp3.Data(0), pp3.LoopBlock([broken])])
            rt.view = 1
            rt.run([loop])
            self.assertEqual(rt.view, 0)
            rt.view = 1
            with self.assertRaises(TypeError):
                rt.run([pp3.LoopBlock([pp3.Data(73), broken])])
            self.assertEqual(rt.view, 73)

    def test_cache_has_bounded_size_and_does_not_keep_ir_alive(self):
        import gc
        import weakref
        from src import _executor

        rt = pp3.Runtime(engine="specialized")
        ir = self.builder.build("&1 [ &0 ]")
        reference = weakref.ref(ir[1])
        rt.run(ir)
        key = id(ir[1])
        self.assertIn(key, _executor._CACHE)
        del ir
        gc.collect()
        self.assertIsNone(reference())
        self.assertNotIn(key, _executor._CACHE)
        retained = [self.builder.build("&1 [ &0 ]") for _ in range(140)]
        for item in retained:
            rt.run(item)
        self.assertLessEqual(len(_executor._CACHE), _executor._CACHE_LIMIT)

    def test_compile_failure_falls_back_without_losing_progress(self):
        rt = pp3.Runtime()
        with patch("src._executor._compile", side_effect=PermissionError("禁止动态编译")):
            rt.run(self.builder.build("&1000 [ @- ]"))
        self.assertEqual(rt.view, 0)
        self.assertEqual(rt.execution_stats["compiled_loops"], 0)
        self.assertGreater(rt.execution_stats["fallbacks"], 0)

    @unittest.skipUnless(hasattr(sys, "monitoring"), "Python 3.12 起提供 monitoring")
    def test_monitoring_tool_forces_reference_semantics(self):
        monitoring = sys.monitoring
        available = next((i for i in range(6) if monitoring.get_tool(i) is None), None)
        if available is None:
            self.skipTest("所有 monitoring 工具槽已占用")
        monitoring.use_tool_id(available, "pp3-test")
        try:
            rt = pp3.Runtime(engine="specialized")
            rt.run(self.builder.build("&1000 [ @- ]"))
            self.assertEqual(rt.view, 0)
            self.assertEqual(rt.execution_stats["specialized_runs"], 0)
        finally:
            monitoring.free_tool_id(available)

    def test_class_descriptor_override_is_not_called_by_the_compiler(self):
        original = pp3.SubSelf.handle
        calls = []

        def descriptor(instance):
            calls.append(instance)
            return lambda runtime: setattr(runtime, "view", 0)

        try:
            pp3.SubSelf.handle = property(descriptor)
            rt = pp3.Runtime(engine="specialized")
            rt.run(self.builder.build("&20 [ @- ]"))
            self.assertEqual(len(calls), 1)
            self.assertEqual(rt.view, 0)
        finally:
            pp3.SubSelf.handle = original


if __name__ == "__main__":
    unittest.main()

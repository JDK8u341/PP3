"""整段 PP3 原生字节码；宿主回调前物化，结构改变时从原位置退优化。"""

import builtins
from collections import deque
from io import StringIO
from itertools import islice

from . import _executor as executor
from . import char_io, pp3
from ._native_codegen import encode


_BUILTINS = executor._IO_BUILTINS
_STD_MODES = {pp3.Input: 15, pp3.Print: 16, pp3.InputAsChar: 17, pp3.PrintAsChar: 18}


def _watch_objects(handles):
    objects, seen = [], set()

    def add(value):
        if isinstance(value, type) and value.__flags__ & (1 << 8):
            return
        if id(value) not in seen:
            seen.add(id(value))
            objects.append(value)

    def sequence(body):
        add(body)
        for node in body:
            add(node)
            for cls in type(node).__mro__:
                add(cls)
            if type(node) is pp3.LoopBlock:
                sequence(node.body)

    sequence(handles)
    for value in (vars(builtins), vars(pp3), vars(char_io)):
        add(value)
    return tuple(objects)


def _resume(runtime, frames):
    # islice 保留原列表迭代位置语义；不得切成新列表。
    for sequence, index, owner in reversed(frames):
        runtime.run(islice(sequence, index, None))
        if owner is not None:
            while runtime.view != 0:
                runtime.run(owner.body)


class NativeProgram:
    def __init__(self, runtime, handles, module=None):
        self.handles = handles
        native = executor._native
        description = executor._describe(pp3.LoopBlock(handles), runtime, allow_host=True)
        if description is None:
            raise ValueError("此 IR 不满足整段原生编译守卫")
        modes = {}
        self.objects = _watch_objects(handles)
        ordinary_builtins = all(getattr(builtins, name, None) is value for name, value in _BUILTINS.items())
        for value in self.objects:
            cls = type(value)
            if cls in _STD_MODES and executor._standard_handler(runtime, value) and ordinary_builtins:
                globals_ = cls.handle.__globals__
                if (not any(name in globals_ for name in _BUILTINS)
                        and not (cls is pp3.InputAsChar and any("buffer" in base.__dict__ for base in cls.__mro__))):
                    modes[id(value)] = _STD_MODES[cls]
        self.code, self.nodes, self.resumes = encode(description, handles, modes)
        self.requirements = tuple({type(node): node for node in self.objects
                                   if type(node) in (pp3.Data, pp3.AddSelf, pp3.SubSelf)
                                   or id(node) in modes}.values())
        self.module = module or native
        self.capsule = self.module.compile(self.code)
        self.signature = native.snapshot(self.objects, None)

    def valid(self, runtime):
        return (executor._native.unchanged(self.signature)
                and all(executor._standard_handler(runtime, node) for node in self.requirements))

    def run(self, runtime):
        native = executor._native
        targets = tuple(runtime._std_handlers.get(type(node), node) for node in self.nodes)
        watched = [runtime, runtime._std_handlers, runtime.std_register, runtime.mem_handler_map]
        watched.extend(targets)
        watched.extend(runtime._std_handlers.values())
        watched.extend(cls for cls in type(runtime).__mro__ if not cls.__flags__ & (1 << 8))
        try:
            snapshot = native.snapshot(tuple(watched), runtime)
        except (TypeError, AttributeError, MemoryError):
            # 结构守卫本身不应使未执行的宿主操作提前报错。
            runtime._execution_stats["fallbacks"] += 1
            return pp3.ReferenceRuntime.run(runtime, self.handles)

        def guard():
            return (self.valid(runtime) and native.unchanged(snapshot)
                    and not executor._callbacks_active() and executor._ordinary_state(runtime))

        runtime._execution_stats["native_runs"] += 1
        next_pc = self.module.run(self.capsule, runtime, targets, guard, (StringIO, deque))
        if next_pc is not None:
            runtime._execution_stats["deoptimizations"] += 1
            _resume(runtime, self.resumes[next_pc])


def try_run(runtime, handles):
    if executor._native is None or executor._callbacks_active() or not executor._ordinary_state(runtime):
        return False
    cache = runtime._native_program_cache
    entry = cache.get(id(handles))
    if entry is not None and entry[0] is handles and entry[1].valid(runtime):
        program = entry[1]
    else:
        from time import perf_counter
        start = perf_counter()
        try:
            program = NativeProgram(runtime, handles)
        except Exception:
            runtime._execution_stats["fallbacks"] += 1
            return False
        finally:
            runtime._execution_stats["compile_seconds"] += perf_counter() - start
        if len(cache) >= 4:
            cache.clear()
        cache[id(handles)] = handles, program
        runtime._execution_stats["compiled_programs"] += 1
    program.run(runtime)
    return True

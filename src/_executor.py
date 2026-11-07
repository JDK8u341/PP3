"""PP3 热点循环专用编译器；动态 Python 扩展保持原版执行路径。"""

import builtins
from collections import OrderedDict, defaultdict
import signal
import sys
from time import perf_counter
from types import MethodType
import weakref

from .handlers import HandlerType
from .pp3 import (
    AddSelf, Data, Debug, IndirectMemHandler, Input, InputAsChar, LoopBlock,
    MemHandler, MemHandlerType, Print, PrintAsChar, ReferenceRuntime, Runtime, SubSelf,
)


_INT, _TYPE, _STR = int, type, str
_RANGE = range
_RUN = Runtime.run
_HANDLES = {cls: cls.handle for cls in (Data, AddSelf, SubSelf, Input, Print, InputAsChar, PrintAsChar, Debug)}
_MEMORY = {
    MemHandlerType.Get: ReferenceRuntime.get,
    MemHandlerType.Set: ReferenceRuntime.set,
    MemHandlerType.Swap: ReferenceRuntime.swap,
}
_CACHE = OrderedDict()
_CACHE_LIMIT = 128
_HOT_ITERATIONS = 8
_MAX_NODES = 4096
_MAX_NESTING = 12
_SIGNALS = tuple(signal.valid_signals())


def _plain_class(cls):
    return (cls.__getattribute__ is object.__getattribute__ and "__getattr__" not in cls.__dict__
            and _TYPE(next((base.__dict__["TYPE"] for base in cls.__mro__ if "TYPE" in base.__dict__), None)) is HandlerType
            and all(name not in cls.__dict__ for name in ("data", "place", "depth", "h_type", "body")))


def _standard_handler(runtime, node):
    if _TYPE(runtime._std_handlers) is not dict:
        return False
    cls = _TYPE(node)
    target = runtime._std_handlers.get(cls, node)
    return (cls in _HANDLES and _TYPE(target) is cls
            and cls.__dict__.get("handle") is _HANDLES[cls] and "handle" not in target.__dict__)


def _plain_memory_dispatch(runtime):
    table = runtime.mem_handler_map
    return _TYPE(table) is dict and all(
        _TYPE(table.get(kind)) is MethodType and table[kind].__self__ is runtime
        and table[kind].__func__ is function
        for kind, function in _MEMORY.items()
    )


def _ordinary_state(runtime):
    cls = _TYPE(runtime)
    if (cls.__getattribute__ is not object.__getattribute__ or cls.__setattr__ is not object.__setattr__
            or any(name in base.__dict__ for base in cls.__mro__
                   for name in ("view", "memory", "can_direct_addressing"))):
        return False
    runner = runtime.run
    if _TYPE(runner) is not MethodType or runner.__self__ is not runtime or runner.__func__ is not _RUN:
        return False
    memory = runtime.memory
    if (_TYPE(runtime.view) is not _INT or _TYPE(memory) is not defaultdict
            or memory.default_factory is not _INT or not _plain_memory_dispatch(runtime)
            or _TYPE(runtime.can_direct_addressing) is not bool):
        return False
    # 字符串键可保存 cup 等扩展状态；纯整数路径不会访问这些单元。
    return all((_TYPE(key) is _INT and _TYPE(value) is _INT) or _TYPE(key) is _STR
               for key, value in memory.items())


def _callbacks_active():
    if sys.gettrace() is not None or sys.getprofile() is not None:
        return True
    monitoring = getattr(sys, "monitoring", None)
    if monitoring is not None and any(monitoring.get_tool(tool) is not None for tool in range(6)):
        return True
    # 自定义信号回调可以观察 view；此时不把 view 缓存在局部变量。
    for number in _SIGNALS:
        handler = signal.getsignal(number)
        if callable(handler) and handler is not signal.default_int_handler:
            return True
    return False


def _describe(loop, runtime):
    """仅查看已知原生节点；未知或延迟序列不提前求值或报错。"""
    budget = [_MAX_NODES]
    visiting = set()
    checked = set()

    if (not _plain_memory_dispatch(runtime) or _TYPE(runtime._std_handlers) is not dict
            or builtins.range is not _RANGE):
        return None

    def known_class(cls):
        if cls not in checked:
            if not _plain_class(cls):
                return False
            checked.add(cls)
        return True

    def block(node, depth):
        if (_TYPE(node) is not LoopBlock or not known_class(LoopBlock)
                or node.TYPE is not HandlerType.Loop or _TYPE(node.body) is not list
                or depth > _MAX_NESTING or id(node.body) in visiting):
            return None
        visiting.add(id(node.body))
        result = []
        for child in node.body:
            budget[0] -= 1
            if budget[0] < 0:
                return None
            cls = _TYPE(child)
            if cls is LoopBlock:
                nested = block(child, depth + 1)
                if nested is None:
                    return None
                result.append(("loop", nested))
            elif cls is Data and known_class(cls) and child.TYPE is HandlerType.InPlace:
                if _TYPE(child.data) is not _INT or not _standard_handler(runtime, child):
                    return None
                result.append(("data", child.data))
            elif cls in (AddSelf, SubSelf) and known_class(cls) and child.TYPE is HandlerType.InPlace:
                if not _standard_handler(runtime, child):
                    return None
                result.append(("add" if cls is AddSelf else "sub",))
            elif cls in (MemHandler, IndirectMemHandler) and known_class(cls):
                direct = cls is MemHandler
                parameter = child.place if direct else child.depth
                if (child.TYPE is not (HandlerType.Mem if direct else HandlerType.InPlaceMem)
                        or _TYPE(child.h_type) is not MemHandlerType or child.h_type not in _MEMORY
                        or _TYPE(parameter) is not _INT or (not direct and parameter <= 0)):
                    return None
                result.append(("direct" if direct else "indirect", child.h_type, parameter))
            else:
                return None
        visiting.remove(id(node.body))
        return tuple(result)

    try:
        return block(loop, 0)
    except (AttributeError, TypeError, RecursionError, MemoryError):
        # 手工 IR 的错误仍在原来的执行位置触发，不能由编译检查提前触发。
        return None


def _compile(description):
    constants = []
    lines = ["def execute(runtime):", "    memory = runtime.memory", "    view = runtime.view", "    try:"]

    def constant(value):
        constants.append(value)
        return f"constants[{len(constants) - 1}]"

    def emit(line, indent):
        lines.append("    " * indent + line)

    def loop(body, indent):
        emit("while view != 0:", indent)
        if not body:
            emit("pass", indent + 1)
        for operation in body:
            kind = operation[0]
            if kind == "loop":
                loop(operation[1], indent + 1)
            elif kind == "data":
                emit("view = " + constant(operation[1]), indent + 1)
            elif kind in ("add", "sub"):
                emit("view += 1" if kind == "add" else "view -= 1", indent + 1)
            else:
                direct, action, parameter = kind == "direct", operation[1], operation[2]
                if direct:
                    emit("if not runtime.can_direct_addressing:", indent + 1)
                    emit("raise ValueError('Your Config Not Allow Direct Addressing!')", indent + 2)
                    emit("place = " + constant(parameter), indent + 1)
                else:
                    emit("place = view", indent + 1)
                    if parameter <= 8:
                        for _ in range(parameter - 1):
                            emit("place = memory[place]", indent + 1)
                    else:
                        emit("for _ in range(" + constant(parameter - 1) + "):", indent + 1)
                        emit("place = memory[place]", indent + 2)
                if action is MemHandlerType.Get:
                    emit("view = memory[place]", indent + 1)
                elif action is MemHandlerType.Set:
                    emit("memory[place] = view", indent + 1)
                else:
                    # 先赋 view 再写内存，与原版元组赋值的顺序一致。
                    emit("view, memory[place] = memory[place], view", indent + 1)

    loop(description, 2)
    lines.extend(("    finally:", "        runtime.view = view"))
    namespace = {"constants": tuple(constants)}
    exec(compile("\n".join(lines), "<pp3-specialized>", "exec"), namespace)
    return namespace["execute"]


def _cached(loop):
    entry = _CACHE.get(id(loop))
    if entry is not None and entry[0]() is loop:
        _CACHE.move_to_end(id(loop))
        return entry
    return None


def _specialize(runtime, node):
    stats = runtime._execution_stats
    description = _describe(node, runtime)
    if description is None:
        stats["fallbacks"] += 1
        return False
    if _callbacks_active() or not _ordinary_state(runtime):
        stats["fallbacks"] += 1
        return False
    cached = _cached(node)
    if cached is not None and cached[1] == description:
        function = cached[2]
        stats["cache_hits"] += 1
    else:
        start = perf_counter()
        try:
            function = _compile(description)
        except Exception:
            # 宿主也可能禁止动态编译；优化失败不能变成 DSL 的新增异常。
            stats["fallbacks"] += 1
            return False
        finally:
            stats["compile_seconds"] += perf_counter() - start
        stats["compiled_loops"] += 1
        key = id(node)
        reference = weakref.ref(node, lambda ignored, key=key: _CACHE.pop(key, None))
        _CACHE[key] = reference, description, function
        _CACHE.move_to_end(key)
        while len(_CACHE) > _CACHE_LIMIT:
            _CACHE.popitem(last=False)
    stats["specialized_runs"] += 1
    function(runtime)
    return True


def _run_loop(runtime, node):
    iterations = 0
    eager = runtime._engine == "specialized" or _cached(node) is not None
    if eager and runtime.view != 0 and _specialize(runtime, node):
        return
    while runtime.view != 0:
        runner = runtime.run
        if (_TYPE(runner) is MethodType and runner.__func__ is _RUN
                and sys.gettrace() is None and sys.getprofile() is None):
            execute(runtime, node.body)
        else:
            runner(node.body)
        iterations += 1
        if iterations == _HOT_ITERATIONS and runtime.view != 0:
            # 单一递增/递减的短倒数可预知剩余次数，避免在临近退出时付编译费。
            if runtime._engine == "auto" and _short_countdown(runtime, node):
                continue
            if _specialize(runtime, node):
                return


def _short_countdown(runtime, node):
    if _TYPE(node) is not LoopBlock or _TYPE(runtime.view) is not _INT:
        return False
    body = node.__dict__.get("body")
    if _TYPE(body) is not list or len(body) != 1:
        return False
    operation = _TYPE(body[0])
    return ((operation is SubSelf and 0 < runtime.view <= 512)
            or (operation is AddSelf and -512 <= runtime.view < 0))


def execute(runtime, handles):
    for node in handles:
        if node.TYPE == HandlerType.Mem:
            if not runtime.can_direct_addressing:
                raise ValueError("Your Config Not Allow Direct Addressing!")
            runtime.mem_handler_map[node.h_type](node.place)
        elif node.TYPE == HandlerType.InPlaceMem:
            place = runtime.view
            for _ in range(node.depth - 1):
                place = runtime.memory[place]
            runtime.mem_handler_map[node.h_type](place)
        elif node.TYPE == HandlerType.InPlace:
            runtime._std_handlers.get(_TYPE(node), node).handle(runtime)
        else:
            _run_loop(runtime, node)

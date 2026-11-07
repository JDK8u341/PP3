"""LLVM MCJIT：把 PP3 控制流和小整数运算直接降为本机机器码。"""

from time import perf_counter
import struct

from . import pp3, _executor
from ._program import NativeProgram
from .aot import AOTProgram


def _emit(code, ir, triple, layout):
    module = ir.Module(name="pp3_jit")
    module.triple = triple
    module.data_layout = layout
    i8, i32, i64 = ir.IntType(8), ir.IntType(32), ir.IntType(64)
    pointer = i8.as_pointer()
    function = ir.Function(module, ir.FunctionType(i64, [pointer, pointer, pointer]), name="pp3_entry")
    entry = function.append_basic_block("entry")
    blocks = [function.append_basic_block(f"op_{index}") for index in range(len(code) + 1)]
    failure = function.append_basic_block("error")
    start = ir.IRBuilder(entry)
    number = start.bitcast(function.args[2], ir.LiteralStructType([i64, pointer]).as_pointer())
    small = start.gep(number, [i32(0), i32(0)])
    big = start.gep(number, [i32(0), i32(1)])
    start.branch(blocks[0])
    helpers = {}

    def helper(builder, opcode, index):
        if opcode not in helpers:
            target = ir.Function(module, ir.FunctionType(i32, [pointer, pointer, i64]), name=f"pp3_op_{opcode}")
            target.attributes.add("nounwind")
            helpers[opcode] = target
        return builder.call(helpers[opcode], [function.args[0], function.args[1], i64(index)])

    def checked(builder, result, continuation):
        builder.cbranch(builder.icmp_signed("<", result, i32(0)), failure, continuation)

    def is_zero(builder):
        return builder.and_(builder.icmp_unsigned("==", builder.load(big), ir.Constant(pointer, None)),
                            builder.icmp_signed("==", builder.load(small), i64(0)))

    add = ir.Function(module, ir.FunctionType(ir.LiteralStructType([i64, ir.IntType(1)]), [i64, i64]),
                      name="llvm.sadd.with.overflow.i64")
    for index, (opcode, argument, depth, jump) in enumerate(code):
        builder = ir.IRBuilder(blocks[index])
        if opcode == 12 or index % 32 == 0:
            continuation = function.append_basic_block(f"polled_{index}")
            checked(builder, helper(builder, 19, index), continuation)
            builder.position_at_end(continuation)
        following = blocks[index + 1]
        if opcode in (11, 12):
            condition = is_zero(builder)
            builder.cbranch(condition, blocks[jump] if opcode == 11 else following,
                            following if opcode == 11 else blocks[jump])
        elif opcode == 13:
            result = helper(builder, opcode, index)
            continuation = function.append_basic_block(f"solved_{index}")
            checked(builder, result, continuation)
            builder.position_at_end(continuation)
            builder.cbranch(builder.icmp_signed("==", result, i32(1)), blocks[jump], following)
        elif opcode >= 14:
            result = helper(builder, opcode, index)
            continuation = function.append_basic_block(f"host_{index}")
            deopt = function.append_basic_block(f"deopt_{index}")
            checked(builder, result, continuation)
            builder.position_at_end(continuation)
            builder.cbranch(builder.icmp_signed("==", result, i32(1)), deopt, following)
            ir.IRBuilder(deopt).ret(i64(index + 1))
        elif opcode == 1 or (opcode == 0 and -(2**63) <= argument < 2**63):
            slow = function.append_basic_block(f"big_{index}")
            fast = function.append_basic_block(f"small_{index}")
            builder.cbranch(builder.icmp_unsigned("==", builder.load(big), ir.Constant(pointer, None)), fast, slow)
            builder.position_at_end(fast)
            if opcode == 1:
                result = builder.call(add, [builder.load(small), i64(argument)])
                store = function.append_basic_block(f"store_{index}")
                builder.cbranch(builder.extract_value(result, 1), slow, store)
                builder.position_at_end(store)
                builder.store(builder.extract_value(result, 0), small)
            else:
                builder.store(i64(argument), small)
            builder.branch(following)
            builder.position_at_end(slow)
            checked(builder, helper(builder, opcode, index), following)
        else:
            checked(builder, helper(builder, opcode, index), following)
    ir.IRBuilder(blocks[-1]).ret(i64(len(code)))
    ir.IRBuilder(failure).ret(i64(-1))
    return str(module)


class _JITModule:
    def __init__(self, capsule):
        self.capsule = capsule

    def run(self, *arguments):
        return _executor._native.run(*arguments, self.capsule)


def compile_jit(handles, *, runtime=None):
    """显式 LLVM 机器码编译；返回对象拥有引擎生命周期，不向自动路径强加 LLVM 依赖。"""
    from llvmlite import binding as llvm, ir
    if struct.calcsize("P") != 8:
        raise RuntimeError("LLVM JIT 当前仅支持 64 位进程")
    if _executor._native is None:
        raise RuntimeError("JIT 需要先构建 PP3 原生扩展")
    runtime = runtime or pp3.Runtime()
    if type(handles) is not list or not _executor._ordinary_state(runtime):
        raise ValueError("当前运行器或 IR 不满足 JIT 守卫")
    start = perf_counter()
    plan = NativeProgram(runtime, handles)
    llvm.initialize_native_target()
    llvm.initialize_native_asmprinter()
    llvm.check_jit_execution()
    machine = llvm.Target.from_default_triple().create_target_machine(
        cpu=llvm.get_host_cpu_name(), features=llvm.get_host_cpu_features().flatten(), opt=3, jit=True)
    text = _emit(plan.code, ir, llvm.get_default_triple(), str(machine.target_data))
    module = llvm.parse_assembly(text)
    module.verify()
    if hasattr(llvm, "create_pass_builder"):
        with llvm.create_pipeline_tuning_options(speed_level=3) as options:
            with llvm.create_pass_builder(machine, options) as passes:
                with passes.getModulePassManager() as manager:
                    manager.run(module, passes)
    for index, address in enumerate(_executor._native.jit_symbols()):
        llvm.add_symbol(f"pp3_op_{index}", address)
    engine = llvm.create_mcjit_compiler(module, machine)
    engine.finalize_object()
    address = engine.get_function_address("pp3_entry")
    capsule = _executor._native.bind_jit(address, plan.capsule, engine)
    plan.module = _JITModule(capsule)
    program = AOTProgram(handles, plan, None, perf_counter() - start)
    program.llvm_ir = text
    program.llvm_version = llvm.llvm_version_info
    program.engine = engine
    return program

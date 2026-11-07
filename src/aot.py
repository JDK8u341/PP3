"""将 PP3 专属字节码编译为本机机器码扩展；构建成本由调用者显式承担。"""

from hashlib import sha256
import importlib.util
from pathlib import Path
import pickle
import subprocess
import sys
import sysconfig
from time import perf_counter

from . import pp3, _executor
from ._program import NativeProgram


def _body(code):
    lines = ["// 由 PP3 AOT 生成；每个分支已成为本机跳转，不再分派 opcode。",
             "bool validate_aot(const Program& program) {",
             f"    if (program.size() != {len(code)}) return false;"]
    for index, (opcode, argument, depth, jump) in enumerate(code):
        check = f"program[{index}].opcode != {opcode} || program[{index}].depth != {depth}ULL || program[{index}].jump != {jump}"
        if opcode in (1, 13):
            check += f" || program[{index}].argument.big || program[{index}].argument.small != {argument}"
        lines.append(f"    if ({check}) return false;")
    lines.extend(("    return true;", "}", "size_t execute_aot(Frame& frame, const Program& program) {"))
    for index, (opcode, argument, depth, jump) in enumerate(code):
        lines.extend((f"L{index}:", "    frame.poll();"))
        if opcode == 0:
            lines.append(f"    frame.view = program[{index}].argument;")
        elif opcode == 1:
            lines.append(f"    frame.view.add({argument});")
        elif opcode == 11:
            lines.append(f"    if (frame.view.zero()) goto L{jump};")
        elif opcode == 12:
            lines.append(f"    if (!frame.view.zero()) goto L{jump};")
        elif opcode == 13:
            lines.append(f"    if (frame.view.reaches_zero({argument})) {{ frame.view = Number(); goto L{jump}; }}")
        elif opcode >= 14:
            lines.append(f"    if (!frame.host(program[{index}])) return {index + 1};")
        else:
            # 编译器可内联 access，并把 opcode/depth 的分支和循环专门化。
            lines.append(f"    frame.access(Instruction{{static_cast<Opcode>({opcode}), program[{index}].argument, {depth}ULL, 0}}, {index});")
    lines.extend((f"L{len(code)}:", f"    return {len(code)};", "}"))
    return "\n".join(lines) + "\n"


class AOTProgram:
    """机器码及原 IR 的绑定；IR/扩展被修改时回退到当前语义，不执行旧机器码。"""

    def __init__(self, handles, plan, artifact, build_seconds):
        self.handles = handles
        self.plan = plan
        self.artifact = artifact
        self.build_seconds = build_seconds

    def run(self, runtime):
        if (type(runtime) is not pp3.Runtime or runtime._engine == "reference" or not self.plan.valid(runtime)
                or _executor._callbacks_active() or not _executor._ordinary_state(runtime)):
            return runtime.run(self.handles)
        self.plan.run(runtime)


def compile_aot(handles, build_dir, *, runtime=None):
    """生成 C++、编译并加载扩展；已有同一实现/字节码/ABI 产物时直接复用。"""
    if _executor._native is None:
        raise RuntimeError("AOT 需要先构建 PP3 原生扩展")
    if type(handles) is not list:
        raise TypeError("AOT 输入必须是 IRBuilder 返回的普通列表")
    runtime = runtime or pp3.Runtime()
    if not _executor._ordinary_state(runtime):
        raise ValueError("当前运行器不满足 AOT 守卫")
    start = perf_counter()
    plan = NativeProgram(runtime, handles)
    source_dir = Path(__file__).resolve().parent
    fingerprint = sha256()
    for name in ("_native.cpp", "_native_guard.hpp", "_native_jit.hpp", "_native_codegen.py", "_toolchain.py", "aot.py"):
        fingerprint.update((source_dir / name).read_bytes())
    fingerprint.update(pickle.dumps(plan.code, protocol=4))
    fingerprint.update((sys.version + str(sysconfig.get_config_var("EXT_SUFFIX"))).encode("ascii"))
    module_name = "_pp3_aot_" + fingerprint.hexdigest()[:24]
    output = Path(build_dir).resolve() / module_name
    output.mkdir(parents=True, exist_ok=True)
    artifact = output / (module_name + sysconfig.get_config_var("EXT_SUFFIX"))
    reused = artifact.is_file()
    if not reused:
        (output / "body.inc").write_text(_body(plan.code), encoding="utf-8")
        (output / "program.cpp").write_text(
            f'#define PP3_MODULE_NAME "{module_name}"\n'
            f'#define PP3_MODULE_INIT PyInit_{module_name}\n'
            '#define PP3_AOT_BODY "body.inc"\n'
            '#include "_native.cpp"\n', encoding="ascii")
        setup = ("from setuptools import Extension, setup\nimport os, sys\n"
                 f"sys.path.insert(0, {str(source_dir)!r})\nfrom _toolchain import LLVMBuildExt\n"
                 f"setup(name={module_name!r}, cmdclass={{'build_ext': LLVMBuildExt}}, ext_modules=[Extension({module_name!r}, ['program.cpp'], "
                 f"include_dirs=[{str(source_dir)!r}], language='c++', "
                 "extra_compile_args=['/O2','/std:c++17','/EHsc','/utf-8'] if os.name=='nt' "
                 "else ['-O3','-std=c++17'])])\n")
        (output / "setup.py").write_text(setup, encoding="utf-8")
        result = subprocess.run([sys.executable, "setup.py", "build_ext", "--inplace"],
                                cwd=output, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                errors="replace")
        (output / "build.log").write_text(result.stdout, encoding="utf-8")
        if result.returncode or not artifact.is_file():
            raise RuntimeError(f"AOT 构建失败，详见 {output / 'build.log'}")
    spec = importlib.util.spec_from_file_location(module_name, artifact)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    plan.module = module
    plan.capsule = module.compile(plan.code)
    program = AOTProgram(handles, plan, artifact, perf_counter() - start)
    program.reused_artifact = reused
    return program

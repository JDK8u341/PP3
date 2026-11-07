"""统一使用 Clang/LLVM；Windows 仅借用 SDK、CRT 头文件和链接库。"""

import os
from pathlib import Path
import shutil

from setuptools.command.build_ext import build_ext
from setuptools.errors import CompileError


def llvm_tool(name):
    executable = shutil.which(name)
    if executable:
        return executable
    if os.name == "nt":
        candidate = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "LLVM" / "bin" / (name + ".exe")
        if candidate.is_file():
            return str(candidate)
    raise CompileError(f"缺少 LLVM 工具 {name}；请安装 Clang/LLVM 并加入 PATH")


def configure_llvm(compiler):
    if compiler.compiler_type == "msvc":
        if not compiler.initialized:
            compiler.initialize()
        compiler.cc = llvm_tool("clang-cl")
        compiler.linker = llvm_tool("lld-link")
        compiler.compile_options[:] = [option for option in compiler.compile_options if option != "/GL"]
        # 保留 distutils 的 Windows ABI 参数，但不调用 cl.exe/link.exe。
        for name in ("ldflags_shared", "ldflags_exe", "ldflags_static"):
            options = getattr(compiler, name, [])
            options[:] = [option for option in options if option != "/LTCG"]
    else:
        clang, clangxx = llvm_tool("clang"), llvm_tool("clang++")
        for name in ("compiler", "compiler_so", "linker_so", "linker_exe"):
            current = getattr(compiler, name, None)
            if current:
                compiler.set_executable(name, [clangxx if "linker" in name else clang, *current[1:]])
        compiler.set_executable("compiler_cxx", [clangxx])
        if getattr(compiler, "compiler_so_cxx", None):
            compiler.set_executable("compiler_so_cxx", [clangxx, *compiler.compiler_so_cxx[1:]])
        if getattr(compiler, "linker_so_cxx", None):
            compiler.set_executable("linker_so_cxx", [clangxx, *compiler.linker_so_cxx[1:]])


class LLVMBuildExt(build_ext):
    def build_extensions(self):
        try:
            configure_llvm(self.compiler)
        except CompileError as error:
            if not all(extension.optional for extension in self.extensions):
                raise
            self.warn(str(error) + "；保留纯 Python 安装")
            self.extensions[:] = []
            return
        super().build_extensions()

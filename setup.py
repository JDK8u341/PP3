"""原生模块按需构建；没有 C++ 编译器时仍可安装纯 Python 执行器。"""

import os
from pathlib import Path
import sys
from setuptools import Extension, setup
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from _toolchain import LLVMBuildExt

extensions = []
if os.environ.get("PP3_NO_NATIVE") != "1":
    extensions.append(Extension(
        "src._native", ["src/_native.cpp"], language="c++", optional=True,
        depends=["src/_native_guard.hpp", "src/_native_jit.hpp"],
        extra_compile_args=["/O2", "/std:c++17", "/EHsc", "/utf-8"] if os.name == "nt"
        else ["-O3", "-std=c++17"],
    ))

setup(ext_modules=extensions, cmdclass={"build_ext": LLVMBuildExt})

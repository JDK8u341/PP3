"""测量惯用 C++ 同题算法，作为语义更窄的性能参照，不与 VM 等价混淆。"""

import json
import os
from pathlib import Path
from statistics import median
import subprocess
import sys

from setuptools._distutils.ccompiler import new_compiler
from setuptools._distutils.sysconfig import customize_compiler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from benchmarks.run import workloads
from src import pp3
from src._toolchain import configure_llvm
from tests.test_execution import snapshot


def main():
    output = ROOT / "build" / "cpp-baseline"
    output.mkdir(parents=True, exist_ok=True)
    compiler = new_compiler()
    customize_compiler(compiler)
    configure_llvm(compiler)
    flags = ["/O2", "/EHsc", "/std:c++17", "/utf-8"] if os.name == "nt" else ["-O3", "-std=c++17"]
    objects = compiler.compile([str(ROOT / "benchmarks" / "cpp_tasks.cpp")], output_dir=str(output), extra_postargs=flags)
    executable = output / ("cpp_tasks.exe" if os.name == "nt" else "cpp_tasks")
    compiler.link_executable(objects, str(executable), target_lang="c++")
    rows = []
    for name, source, stdin in workloads(None):
        if not name.startswith("P"):
            continue
        data = stdin
        if name in ("P006", "P007", "P008"):
            length, payload = stdin.split("\n", 1)
            data = payload[:int(length)]
        expected = snapshot(pp3.ReferenceRuntime(), pp3.IRBuilder(pp3.std_register).build(source), stdin)[2]
        expected_checksum = sum(map(ord, expected))
        actual = subprocess.run([str(executable), name, "0"], input=data.encode("latin1"),
                                stdout=subprocess.PIPE, check=True).stdout
        if actual != expected.encode("latin1"):
            raise AssertionError(name + " C++ 逐字输出差分失败")
        times = []
        for _ in range(7):
            result = subprocess.run([str(executable), name, "20000"], input=data.encode("latin1"),
                                    stdout=subprocess.PIPE, check=True)
            seconds, checksum = result.stdout.decode("ascii").split()
            if int(checksum) != expected_checksum * 20000:
                raise AssertionError(name + " C++ 输出校验失败")
            times.append(float(seconds))
        rows.append({"name": name, "seconds_per_call": median(times)})
    report = {"scope": "惯用 C++ 题目算法；仅此固定有效输入，机器整数；不含 DSL 内存、逐字符 flush、启动和协议解码",
              "repeat": 7, "batch": 20000, "compiler": "Clang/LLVM", "flags": flags, "workloads": rows}
    (ROOT / "benchmarks" / "results-cpp-windows.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()

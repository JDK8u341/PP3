"""机器码 AOT 对照：单独列出编译/载入成本与热运行，先逐项差分再计时。"""

import argparse
import json
from pathlib import Path
import platform
from statistics import median
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import pp3, _executor
from src.aot import compile_aot
from src.jit import compile_jit
from benchmarks.run import execute, workloads


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeat", type=int, default=7)
    parser.add_argument("--only", nargs="*")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("repeat 必须为正数")
    report = {"python": sys.version, "platform": platform.platform(), "repeat": args.repeat,
              "native_compiler": getattr(_executor._native, "compiler", "unknown"), "workloads": []}
    for name, source, stdin in workloads(None):
        if (args.only and name not in args.only) or (not args.only and not name.startswith("P")):
            continue
        ir = pp3.IRBuilder(pp3.std_register).build(source)
        direct = name in ("深度寻址", "大整数")
        print(name + "：编译真实机器码", flush=True)
        program = compile_aot(ir, ROOT / "build" / "aot-benchmark", runtime=pp3.Runtime(direct))
        jit = compile_jit(ir, runtime=pp3.Runtime(direct))
        row = {"name": name, "aot_prepare_seconds": program.build_seconds,
               "jit_prepare_seconds": jit.build_seconds, "llvm_version": jit.llvm_version,
               "reused_artifact": program.reused_artifact, "binary_bytes": program.artifact.stat().st_size,
               "engines": {}}
        _, expected = execute(pp3.ReferenceRuntime(direct), ir, stdin)
        row["memory_cells"] = len(expected[1])
        for engine in ("reference", "specialized", "native", "aot", "jit"):
            rt = pp3.ReferenceRuntime(direct) if engine == "reference" else pp3.Runtime(direct, engine="native" if engine in ("aot", "jit") else engine)
            runner = program if engine == "aot" else jit if engine == "jit" else None
            cold, actual = execute(rt, ir, stdin, runner)
            if actual != expected:
                raise AssertionError(f"{name} {engine} 冷执行差分失败")
            samples = []
            for _ in range(args.repeat):
                rt.clear()
                elapsed, actual = execute(rt, ir, stdin, runner)
                if actual != expected:
                    raise AssertionError(f"{name} {engine} 热执行差分失败")
                samples.append(elapsed)
            row["engines"][engine] = {"cold_seconds": cold, "hot_seconds": median(samples)}
        reference = row["engines"]["reference"]["hot_seconds"]
        for result in row["engines"].values():
            result["speedup"] = reference / result["hot_seconds"]
        saved = row["engines"]["native"]["hot_seconds"] - row["engines"]["aot"]["hot_seconds"]
        row["break_even_runs"] = program.build_seconds / saved if saved > 0 else None
        saved = row["engines"]["native"]["hot_seconds"] - row["engines"]["jit"]["hot_seconds"]
        row["jit_break_even_runs"] = jit.build_seconds / saved if saved > 0 else None
        report["workloads"].append(row)
        print(name + ": " + ", ".join(f"{engine}={data['speedup']:.2f}x" for engine, data in row["engines"].items()), flush=True)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

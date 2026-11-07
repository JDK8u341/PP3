"""测量冷启动、编译与热执行，所有被测路线先与参考运行器完整差分。"""

import argparse
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import platform
from statistics import median
import sys
from time import perf_counter
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import pp3
from src import _executor
from benchmarks.bytecode_probe import FlatBytecode


def execute(runtime, handles, stdin, bytecode=None):
    output = StringIO()
    error = None
    with patch("sys.stdin", StringIO(stdin)), redirect_stdout(output):
        start = perf_counter()
        try:
            if bytecode is None:
                runtime.run(handles)
            else:
                bytecode.run(runtime)
        except Exception as exception:
            error = type(exception).__name__, str(exception)
        elapsed = perf_counter() - start
    return elapsed, (runtime.view, list(runtime.memory.items()), output.getvalue(), error,
                     tuple(runtime.std_register["input_as_char"].buffer))


def workloads(challenges):
    rows = [
        ("短直线", "&1 @+ @- ^1 ~1", ""),
        ("短循环", "&3 [ @- ]", ""),
        ("临界短循环", "&9 [ @- ]", ""),
        ("长递减", "&200000 [ @- ]", ""),
        ("深度寻址", "&5000 [ $-1 &7 ~5 &-1 ~1 @- ]", ""),
        ("大整数", "&2000 [ $-1 &" + str(10**100) + " @+ @- ^1 &-1 ~1 @- ]", ""),
    ]
    fixtures = ROOT / "benchmarks" / "fixtures"
    inputs = {
        "P003": "-001234\n", "P004": "-123\n87\n", "P005": "-987\n610\n",
        "P006": "128\n" + "AbZ!" * 32,
        "P007": "128\n" + "".join(map(chr, reversed(range(128)))),
        "P008": "200\n" + "a b\nc\t" * 34,
    }
    if challenges:
        catalog = json.loads((challenges / "catalog.json").read_text(encoding="utf-8"))
        for entry in catalog["problems"]:
            if entry["id"] in inputs:
                rows.append((entry["id"], (challenges / entry["directory"] / "solution.pp3").read_text(encoding="ascii"),
                             inputs[entry["id"]]))
    else:
        for problem_id, stdin in inputs.items():
            path = fixtures / f"{problem_id}.pp3"
            if path.is_file():
                rows.append((problem_id, path.read_text(encoding="ascii"), stdin))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--challenges", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("repeat 必须为正数")
    report = {"python": sys.version, "platform": platform.platform(), "repeat": args.repeat,
              "timing": "perf_counter 中位数；冷启动包括 run 内编译，build 和 Runtime 初始化分列",
              "workloads": []}
    builder = pp3.IRBuilder(pp3.std_register)
    for name, source, stdin in workloads(args.challenges):
        start = perf_counter()
        ir = builder.build(source)
        build_seconds = perf_counter() - start
        start = perf_counter()
        flat = FlatBytecode(ir)
        flat_compile = perf_counter() - start
        direct = name in ("深度寻址", "大整数")
        reference_time, expected = execute(pp3.ReferenceRuntime(direct), ir, stdin)
        row = {"name": name, "tokens": len(source.split()), "build_seconds": build_seconds,
               "can_direct_addressing": direct, "flat_compile_seconds": flat_compile, "engines": {}}
        for engine in ("reference", "flat", "auto", "specialized"):
            cold, hot, compilation, initial = [], [], [], []
            compiled, specialized = [], []
            for _ in range(args.repeat):
                _executor._CACHE.clear()
                start = perf_counter()
                runtime = (pp3.ReferenceRuntime(direct) if engine in ("reference", "flat")
                           else pp3.Runtime(direct, engine=engine))
                initial.append(perf_counter() - start)
                cold_time, actual = execute(runtime, ir, stdin, flat if engine == "flat" else None)
                if actual != expected:
                    raise AssertionError(f"冷执行差分失败：{name} {engine}")
                cold.append(cold_time + (flat_compile if engine == "flat" else 0))
                stats = getattr(runtime, "execution_stats", {})
                compilation.append(flat_compile if engine == "flat" else stats.get("compile_seconds", 0))
                compiled.append(stats.get("compiled_loops", 0))
                specialized.append(stats.get("specialized_runs", 0))
                runtime.clear()
                hot_time, actual = execute(runtime, ir, stdin, flat if engine == "flat" else None)
                if actual != expected:
                    raise AssertionError(f"热执行差分失败：{name} {engine}")
                if name in ("短直线", "短循环", "临界短循环"):
                    # 微秒级程序批量计时，降低计时器与上下文管理器的噪声。
                    count = 2000
                    start = perf_counter()
                    for _ in range(count):
                        if engine == "flat":
                            flat.run(runtime)
                        else:
                            runtime.run(ir)
                    hot_time = (perf_counter() - start) / count
                hot.append(hot_time)
            row["engines"][engine] = {
                "cold_seconds": median(cold), "hot_seconds": median(hot),
                "compile_seconds": median(compilation), "init_seconds": median(initial),
                "compiled_loops": median(compiled), "specialized_runs": median(specialized),
            }
        base = row["engines"]["reference"]["hot_seconds"]
        for data in row["engines"].values():
            data["hot_speedup"] = base / data["hot_seconds"]
        report["workloads"].append(row)
        print(name + ": " + ", ".join(f"{engine}={data['hot_speedup']:.2f}x"
                                         for engine, data in row["engines"].items()), flush=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

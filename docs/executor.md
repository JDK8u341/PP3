# PP3 原生执行与机器码编译

目标是保持 PP3 的整数、寻址、输入输出和 Python 扩展语义，改变内部表示与执行方式以减少开销。实现分成 PP3 专属字节码 VM、LLVM JIT、Clang AOT；原 Python 专用函数作为没有原生工具链时的回退，`ReferenceRuntime` 保留原版用于差分，不建议日常使用。

## 四条执行路线

| 路线 | 实际执行方式 | 入口 |
| --- | --- | --- |
| 原生 VM | PP3 自己的 opcode、常量、深度和跳转表，由 C++17 执行 | 安装原生扩展后 `Runtime()` 自动选择 |
| LLVM JIT | PP3 字节码生成 LLVM IR，再由 LLVM MCJIT 生成可执行机器码 | `src.jit.compile_jit` |
| Clang AOT | PP3 字节码生成 C++ 控制流，通过 Clang/LLVM 编译为 `.pyd`/`.so` | `src.aot.compile_aot` |
| Python 专用函数 | 纯循环生成 CPython 字节码函数 | `engine="specialized"` 或未安装扩展时的 auto |

原生 VM 的字节码不是 Python bytecode。LLVM JIT 与 Clang AOT 都产生真实本机机器码。机器码版本仍共享原生整数、图存储、I/O 和退优化辅助函数，不是脱离 Python 的独立可执行文件。

## 构建与使用

原生 VM 和 AOT 使用 Clang，Windows 链接使用 LLD；不调用 MSVC 的 `cl.exe`/`link.exe`。Windows 仍需系统 SDK 和 CRT 头文件/库来匹配 CPython ABI；这些文件所在目录含 `MSVC` 不表示使用了 MSVC 编译器。Linux 需 Clang/C++17 和 Python 开发头文件。

```text
python -m pip install -e .
python -m pip install -e ".[jit,aot]"
```

第二条额外安装 JIT 的 llvmlite 与 AOT 运行期构建需要的 setuptools；LLVM 可与本机 Clang 版本不同，二者只通过稳定的原生函数地址桥接，不混合不同 LLVM 版本的 bitcode。机器码 JIT 当前限定 64 位进程。

```python
from src.pp3 import IRBuilder, Runtime, std_register
from src.jit import compile_jit
from src.aot import compile_aot

ir = IRBuilder(std_register).build("@input [ @- ] @print")
Runtime().run(ir)                         # 默认 VM
jit = compile_jit(ir)                     # 显式支付 JIT 成本
jit.run(Runtime())                       # 可反复执行
aot = compile_aot(ir, "build/my-aot")     # 显式构建机器码扩展
aot.run(Runtime())
```

`Runtime(engine="native")` 要求扩展存在，缺失时明确报错；特殊动态状态仍回退以保持语义。`PP3_NO_NATIVE=1` 禁止构建扩展，`PP3_DISABLE_NATIVE=1` 在导入时禁用已构建的扩展。纯 Python 使用没有第三方运行依赖。

默认路径不自动启动 LLVM JIT 或外部 AOT 编译器。短任务的编译成本可能超过执行成本；测量分别记录首次编译、热运行与回本次数。AOT 缓存键包含执行器源码、编译模板、字节码和 Python ABI；IR 或扩展被修改时先回退，不执行失效的机器码。构建目录应由调用者自己控制，目录中的二进制是可执行代码。

## 数学模型

令状态为 `(v, f, D)`：`v` 是 view，`f: Z -> Z` 是内存映射，`D` 是已存在的键及其顺序。缺失读取不仅得到 0，也把该地址加入 `D`。因此不能把所有未写入地址看作“无需记录的零”。

每个整数地址只有一条出边 `a -> f(a)`，构成可修改的函数图。间接指令深度为 `d` 时，先求目标地址 `p = f^(d-1)(v)`，然后：

| 指令 | 状态变化 |
| --- | --- |
| `~d` | `v = f(p)` |
| `^d` | `f(p) = v` |
| `*d` | 先读取旧 `f(p)`，再交换 view 与该单元 |

节点编号、哈希表、缓存、opcode 均不属于语言语义，可以按性能需要重排；`v`、实际键值、缺失创建及顺序、回调边界可见状态必须保留。

### 出边缓存与局部失效

Graph 为触达地址分配紧凑编号，记录值与 `successor`。读取一条已解析的边直接访问编号，不重复做 Python 整数装箱与字典查找。写入 `a` 改变的仅是 `a` 的出边；因此只失效该节点缓存。等值写入不改变边，可以保留缓存，但仍按语义记录赋值。

不缓存整条路径，也不假设零槽或某个锚点永远不变。链、环、负地址、地址与载荷碰撞以及任意修改都沿当前图执行。

### 长寻址的环摘要

单次寻址期间没有写入，映射固定。顺序记录节点首次出现的位置；若在第 `j` 步重复第 `i` 步的节点，则周期 `k=j-i`，剩余 `r` 步可替换为 `r mod k` 步。

首次重复之前仍按参考顺序访问所有节点，因此所有缺失零单元均已按原顺序创建。环内没有新节点，跳跃不会漏掉可见插入。实现只在深度超过 65 时建立游走表，短路径直接走出边缓存。极长的无环前缀仍须遍历。测试包含 `10^12+1` 层两节点环、缺失链、尾链进入环、最终写入与交换。

当前 native 深度字段为 uint64，超过它的合法 Python 整数深度回退到原 Python 执行，绝不截断为 64 位。

### 纯算术循环摘要

仅含 `@+`/`@-` 的循环体，整轮净增量为 `k`。每轮结束值为 `v_n=v_0+n*k`。由于循环只在整轮边界检查 view：

- `v_0=0`：不进入循环。
- `k!=0` 且 `n=-v_0/k` 是正整数：最终恰为零，可直接赋零。
- 其他情况：保留不终止行为，不擅自清零。

例如 `[ @- @- ]` 对 4 可终止，对 3 不会终止；`[ @+ @- ]` 对非零输入也不会终止。方向和整除判定支持任意精度整数。连续加减另融合为净增量指令；不会删除中间的内存操作或宿主调用。不终止循环仍周期性检查信号、让出 GIL，测试通过后台线程请求 KeyboardInterrupt 验证。

## 原生数值和内存

`Number` 规范化为内联 int64 或拥有引用的 Python PyLong。加法在 C++ 中先判断范围；JIT 使用 LLVM 的有符号溢出 intrinsic。溢出时进入 PyLong，回到范围内又进入快路径。地址同样支持大整数，不截断、不转成浮点数、不使用有符号溢出未定义行为。

原生图按需从公开字典取值，并按首次触达顺序保存节点。正常退出、异常退出、宿主回调前按该顺序将修改值和缺失零值写回同一个 `defaultdict(int)`。已有键更新不改变原次序，扩展使用的字符串键保持不动。公开 memory 对象身份不替换。

## 标准操作与扩展边界

较长的普通 IR 列表可整体编码，循环、分支和标准 I/O 均进入 PP3 VM。不是每个短循环都返回 Python、重新验证和重建图。

标准 `input`、`print`、字符输入输出有 C 层 opcode。仍保留 `input()` 的行和 EOF 规则、整数转换、字符缓冲属于各 Runtime 的独立 handler、Unicode `ord()`、输出模 256、每字符 `flush=True` 等行为。

已填充的精确 deque 缓冲、无实例覆盖的精确 StringIO 输出可走无用户回调快路径；普通终端、自定义流、改写后的标准函数、特殊缓冲走物化边界。不会为吞吐而合并用户可观察的 flush，也不绕过 `sys.stdin/stdout`。因此 StringIO 基准不能当作真实终端吞吐承诺。

自定义 handler、cup 和 debug 通过 HOST opcode 调用原接口，返回值仍忽略。宿主可重入、改写 view/内存、替换映射、修改活动 IR 或抛异常。调用前先提交状态；调用后重新校验结构。若失效，按保存的原列表迭代位置与循环栈继续，不能从程序入口重跑，也不能用旧影子图覆盖回调留下的状态。

快照持有的 Python 引用放在可被 GC 遍历的容器中，避免 capsule 隐藏 Runtime/handler 回环。字节码 capsule 只拥有原生结构与精确整数；JIT capsule 拥有代码引擎和对应字节码，防止机器码释放后再调用。

## 守卫与兼容范围

入口检查 Runtime/IR 类型、普通实例布局、标准方法及代码、内存分派、精确整数、defaultdict 默认工厂、直接寻址许可类型。IR、类、注册表和关键模块的结构改变会失效缓存。tracing、profiling、monitoring、自定义信号处理器和 GC callbacks 会禁用高速路径。

直接寻址权限只在到达指令时检查；不可达分支不会提前报错。C++ 辅助函数不向 JIT 抛出 C++ 异常，改用错误状态返回；统一出口保留 Python 异常及其发生前的 DSL 状态。

承诺对象是顺序执行的语言状态、标准 I/O 与原 Python API。不同内部表示不能保持完全相同的分配次数、MemoryError 触发时刻、内部栈帧、traceback 行号、计时、编译 audit 事件和异步信号落在哪条机器指令上。需要这些宿主实现观测时使用 ReferenceRuntime。活动 Runtime、IR 或执行所依赖的全局操作的并发改写需要外部同步。没有声称对任意 Python 元编程给出形式化全程序等价证明。

## 缓存与代码生成

纯循环缓存沿用有界 128 项弱引用 LRU；每个 Runtime 另最多保留 4 个整段程序。整段候选限制 16000 个 IR 节点、32 层嵌套、20000 条编码指令；超出仅回退，不拒绝语言输入。`clear()` 保留编译缓存、重置原有运行状态和字符缓冲。

JIT 将控制流和常见整数操作内联为 LLVM IR；图访问、大整数、I/O、宿主守卫通过 C ABI 辅助函数。没有把 Python handler 逐项调用改名为 JIT。AOT 生成显式分支/跳转，Clang 可以内联共享图内核；运行前验证字节码结构匹配，错误 capsule 不能越界执行。

选择 MCJIT 是因为 llvmlite 的公开文档与 Windows 可用接口足以覆盖当前需求；本次没有把 ORC、LLVM JITLink 或跨版本 bitcode 混用强塞进默认路径。后续可沿基本块融合、图 helper 内联、按证明消除重复访存继续探索，必须同时保留键插入和别名影响。

## 验证与研究来源

测试比较 view、完整有序 `memory.items()`、stdout、异常类型/参数及字符缓冲；包含 20 个固定题库/研究样本、随机有界程序、int64 边界、改写 IR、回调异常、垃圾回收和中断。CI 在 Linux/Windows、Python 3.10/3.12/3.14 构建 Clang 原生模块，运行 AOT/JIT 和禁用原生后的纯 Python 回归。

Exa 共 6 组搜索、34 个候选结果位（含重复，不能当作 34 篇已验证论文），覆盖整数/字典 API、图表示与物化、部分求值、VM 分派、LLVM ORC 与 llvmlite。下列为核验并采用的主要原始资料；加速比只来自本仓库实测。

- [CPython 3.10 整数 C API](https://docs.python.org/3.10/c-api/long.html)：任意精度、转换及溢出。
- [CPython 3.12 字典 C API](https://docs.python.org/3.12/c-api/dict.html)：字典直接访问与错误区分。
- [CPython 3.12 类型 API](https://docs.python.org/3.12/c-api/type.html)及[实现](https://github.com/python/cpython/blob/3.12/Objects/typeobject.c)：PyType_GetDict 所有权和版本差异。
- [Graal 部分求值](https://www.graalvm.org/latest/graalvm-as-a-platform/language-implementation-framework/PartialEvaluation/)：稳定程序专门化、守卫与失效。
- [Bolz/Tratt，The Impact of Meta-Tracing on VM Design and Implementation](https://tratt.net/laurie/research/pubs/html/bolz_tratt__the_impact_of_metatracing_on_vm_design_and_implementation/)：表示方式与跨边界成本。
- [Ertl/Gregg，PLDI 2003](https://dl.acm.org/doi/10.1145/781131.781162)：VM 分派与 superinstructions；不把旧硬件测量直接套用到本机。
- [Vmgen 原论文](https://onlinelibrary.wiley.com/doi/10.1002/spe.434)：生成式解释器及与原生编译器的差距。
- [LLVM ORC 设计](https://llvm.org/docs/ORCv2.html)、[按函数惰性编译](https://llvm.org/docs/tutorial/BuildingAJIT3.html)：链接、代码生命周期和编译时机。
- [llvmlite 执行引擎](https://llvmlite.readthedocs.io/en/latest/user-guide/binding/execution-engine.html)：真实机器码生成、执行内存检查和引擎生命周期。
- [Eli Bendersky 的 BF 解释/JIT 实验](https://eli.thegreenplace.net/2017/adventures-in-jit-compilation-part-1-an-interpreter/)：语言字节码与本机编译的可测对照方法。

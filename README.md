# PP3

PP3 是一个用 Python 实现的极简指令语言运行时。项目核心文件是 `src/pp3.py`，它提供：

- 一个基于 `view` 和 `memory` 的运行时 `Runtime`
- 一组基础指令 handler，例如读写内存、交换内存、字符输入输出、加一减一
- 一个 `IRBuilder`，用于把文本形式的 PP3 指令编译成可执行 IR
- 两种内存访问方式：直接寻址和间接寻址

`Runtime` 现在默认使用热点循环专用执行器：保留原 IR、任意精度整数和 `defaultdict(int)`，在运行中把已验证的纯计算热点编译为专用 Python 字节码函数，短程序和动态扩展继续解释执行。无需额外安装原生编译器。

旧实现保留为 `ReferenceRuntime`，用于回归对照和诊断，不建议作为日常默认执行器。路线比较、兼容性证明和冷/热测量见[执行器设计](docs/executor.md)与[基准报告](benchmarks/README.md)。

## 获取项目

请自行 clone 本仓库，然后进入项目目录即可使用。

项目没有额外的第三方依赖，只需要 Python 3。

## 快速开始

在项目根目录下创建或运行 Python 文件：

```python
from src.pp3 import *

builder = IRBuilder({
    "print": Print,
    "+": AddSelf,
    "-": SubSelf,
    "input": Input,
})

code = "&5 @print"
ir = builder.build(code)

rt = Runtime(can_direct_addressing=True)
rt.run(ir)
```

输出：

```text
5
```

## 运行时模型

PP3 的运行时由两个核心状态组成：

- `view`：当前视图值，可以理解为寄存器或当前工作值。
- `memory`：默认值为 `0` 的整数内存表，底层使用 `defaultdict(int)`。

大多数指令都会读取或修改 `view`，部分指令会通过 `view` 或指定地址访问 `memory`。

```python
rt = Runtime(can_direct_addressing=True)
print(rt.view)      # 0
print(rt.memory[1]) # 0
```

## 指令语言教程

PP3 指令默认使用空格分隔。每条指令由一个符号前缀和参数组成。

### 立即数

`&数字` 会把 `view` 设置为指定整数。

```text
&5
&-10
```

示例：

```python
ir = builder.build("&5 @print")
rt.run(ir)
```

### 自定义操作

`@名称` 会调用 `IRBuilder` 中注册的操作类。

内置操作类包括：

- `Print`：打印当前 `view`，并保持 `view` 不变。
- `Input`：读取用户输入并转成整数。
- `PrintAsChar`：输出 `view % 256` 对应的单个字符，不追加换行。
- `InputAsChar`：从按行读取的字符缓冲中取出一个字符，并把其 `ord()` 写入 `view`。
- `AddSelf`：让 `view + 1`。
- `SubSelf`：让 `view - 1`。

注册方式：

```python
builder = IRBuilder({
    "print": Print,
    "input": Input,
    "+": AddSelf,
    "-": SubSelf,
})
```

调用方式：

```text
&1 @+ @print
```

输出：

```text
2
```

### 直接寻址

直接寻址需要创建运行时时开启 `can_direct_addressing=True`。

| 指令 | 含义 |
| --- | --- |
| `#地址` | 从 `memory[地址]` 读取值到 `view` |
| `$地址` | 把当前 `view` 写入 `memory[地址]` |
| `%地址` | 交换当前 `view` 和 `memory[地址]` |

示例：

```python
code = "&5 $0 #0 @print"
ir = builder.build(code)

rt = Runtime(can_direct_addressing=True)
rt.run(ir)
```

执行过程：

1. `&5`：`view = 5`
2. `$0`：`memory[0] = 5`
3. `#0`：`view = memory[0]`
4. `@print`：输出 `5`

如果没有开启直接寻址却使用 `#`、`$`、`%`，运行时会抛出：

```text
ValueError: Your Config Not Allow Direct Addressing!
```

### 字符输入输出

标准注册表 `std_register` 包含两个字符操作：

```python
builder = IRBuilder(op_map=std_register)
```

`@print_as_char` 输出当前 `view` 对 256 取模后的字符，不输出额外换行，也不修改 `view`：

```text
&65 @print_as_char
```

上面的代码输出 `A`。负数也按 Python 的取模规则处理，例如 `-1` 输出码点 `255` 对应的字符。

`@input_as_char` 每次取出一个字符，并把字符的 `ord()` 写入 `view`。由于 Python 的 `input()` 一次读取一整行，字符缓冲由 `InputAsChar` 操作实例独立维护；一行耗尽后才读取下一行，并把被 `input()` 去掉的换行补回缓冲。因此输入 `ABC` 后，在同一个 Runtime 中连续读取四次得到：

```text
65, 66, 67, 10
```

空行也会产生一个换行字符。输入到达 EOF 时抛出 `EOFError`。整数操作 `@input` 使用独立的 `input()` 调用，不会消费字符缓冲。

字符 I/O 实现在独立模块 `src/char_io.py`，该模块的注册表在加载时并入 `std_register`。全局注册表保存操作类型，每个 Runtime 都通过它创建自己的标准操作实例，可通过 `rt.std_register` 查看。同一个 Runtime 中的多个字符输入指令、循环和多次 `run()` 共用该 Runtime 的输入实例；不同 Runtime 的缓冲互不影响，即使它们执行同一份 IR。

`Runtime.clear()` 会清空该 Runtime 的字符缓冲；缓冲不占用 DSL 的 `memory` 地址。整数输入行为保持不变。字符输入直接保存 Unicode 码点，因此中文输入的 `view` 可以大于 255；只有字符输出取模，非字节范围的输入不会原样回显。

### 间接寻址

间接寻址不需要开启 `can_direct_addressing`。它会从当前 `view` 出发，沿着 `memory` 链寻找目标地址。

| 指令 | 含义 |
| --- | --- |
| `~深度` | 间接读取 |
| `^深度` | 间接写入 |
| `*深度` | 间接交换 |

深度必须是正整数，否则会抛出：

```text
ValueError: depth must be positive
```

间接寻址的目标地址计算方式：

```python
place = view
for i in range(depth - 1):
    place = memory[place]
```

然后再对这个 `place` 执行 get、set 或 swap。

例如：

```text
&5 ^2 &6 ^3
```

可以把 `memory[5]` 设置为 `6`。因为未初始化地址的默认值都是 `0`，这类链式寻址可以利用默认零值构造地址关系。

### 循环

`[ ... ]` 表示循环块。当进入循环时，只要当前 `view != 0`，就会反复执行括号内的指令。

示例：输入一个数字，然后从该数字开始递减打印到 `1`。

```python
code = "@input [ @print @- ]"
ir = builder.build(code)

rt = Runtime(can_direct_addressing=True)
rt.run(ir)
```

如果输入：

```text
3
```

输出：

```text
3
2
1
```

循环括号必须匹配，否则 `IRBuilder.build()` 会抛出：

```text
ValueError: Unmatched closing bracket at position ...
ValueError: Unmatched opening bracket(s) at positions ...
```

## API 调用

### Runtime

```python
rt = Runtime(can_direct_addressing=False)
```

参数：

- `can_direct_addressing`：是否允许直接寻址。默认是 `False`。
- `engine`：新增的可选关键字参数。默认 `"auto"` 按热点选择编译；`"reference"` 强制参考路径；`"specialized"` 尝试立即编译可支持循环，仅建议用于诊断或已知热点，短程序可能因编译和检查变慢。

常用属性：

- `rt.view`：当前视图值。
- `rt.memory`：运行时内存。

常用方法：

```python
rt.run(handles)
rt.clear()
```

- `run(handles)`：执行由 `IRBuilder.build()` 生成的 IR，或手动构造的 handler 列表。
- `clear()`：清空内存和本 Runtime 的字符输入缓冲，并把 `view` 重置为 `0`。

原有调用、手工 handler 列表和 `IRBuilder.build()` 返回的列表接口不变。新增 `rt.execution_stats` 返回编译次数、命中、回退和编译秒数的副本；这些统计不占用 DSL 内存。`clear()` 保持原来的作用，不清空累计统计或全局有界代码缓存。

```python
rt = Runtime()                       # 推荐：自动执行器
rt = Runtime(engine="reference")     # 诊断时强制原路径
reference = ReferenceRuntime()        # 独立原版语义对照
```

自定义 handler、I/O、debug 和 cup 始终通过原 handler 接口执行；修改标准操作或内存分派、替换内存对象、继承 Runtime 时，不能证明安全的区域回退。IR 修改会在再次进入编译循环前核对，缓存不持有 Runtime 或字符缓冲。

### IRBuilder

```python
builder = IRBuilder(op_map=None)
```

参数：

- `op_map`：自定义操作映射，key 是 `@` 后面的名称，value 是 `InPlaceHandler` 子类。

构建 IR：

```python
ir = builder.build("&5 @print")
```

`build()` 可以接收字符串，也可以接收已经分词后的列表。

```python
ir = builder.build(["&5", "@print"])
```

字符串会先按空白分词；列表则必须提供已经分好的严格 token，不能包含空项或带空白的项。例如 `[' [ ', '&0', ' ] ']` 会抛出 `ValueError`，不会再次分词。

### 自定义操作

自定义操作需要继承 `InPlaceHandler` 并实现 `handle(self, runtime)`。

```python
from src.pp3 import *

class Double(InPlaceHandler):
    def handle(self, runtime):
        runtime.view *= 2

builder = IRBuilder({
    "print": Print,
    "double": Double,
})

code = "&6 @double @print"
ir = builder.build(code)

rt = Runtime(can_direct_addressing=True)
rt.run(ir)
```

输出：

```text
12
```

`handle()` 的返回值会被忽略。自定义操作需要直接修改 `runtime.view`；如果操作还需要保存状态，应将状态放在操作实例自身，或明确放入 `runtime.memory`。

### 手动构造 IR

除了使用文本指令，也可以直接调用 API 构造 IR：

```python
from src.pp3 import *

handles = [
    Data(5),
    Set(0),
    Get(0),
    Print(),
]

rt = Runtime(can_direct_addressing=True)
rt.run(handles)
```

等价于：

```text
&5 $0 #0 @print
```

## 指令速查

| 指令 | API | 说明 |
| --- | --- | --- |
| `&n` | `Data(n)` | 设置 `view = n` |
| `@name` | 自定义 `InPlaceHandler` | 执行注册操作 |
| `@input_as_char` | `InputAsChar` | 读取一个字符，将 `ord()` 写入 `view` |
| `@print_as_char` | `PrintAsChar` | 输出 `view % 256` 对应的字符 |
| `#n` | `Get(n)` | 直接读取 `memory[n]` |
| `$n` | `Set(n)` | 直接写入 `memory[n]` |
| `%n` | `Swap(n)` | 直接交换 `view` 和 `memory[n]` |
| `~n` | `IndirectGet(n)` | 间接读取 |
| `^n` | `IndirectSet(n)` | 间接写入 |
| `*n` | `IndirectSwap(n)` | 间接交换 |
| `[ ... ]` | `LoopBlock(...)` | 当 `view != 0` 时循环 |

## 示例：A+B Problem

`test/A+B Problem.py` 中包含一个不依赖直接寻址的加法示例。核心思路是通过间接寻址保存两个输入，并循环递增第一个数、递减第二个数，最后输出结果。

可以参考其中的代码：

```python
from src.pp3 import *

builder = IRBuilder(op_map={
    "print": Print,
    "-": SubSelf,
    "+": AddSelf,
    "input": Input,
})

code = """
&-3 ^2 &0 ^2 &1 ^3
&-1 ^2 &0 ^2 @input @+ ^3
&-2 ^2 &0 ^2 @input ^3
&-2 ~1
[
  &-3 ^3 &0 ^2 &-1 ~1 ^3
  &-1 ^3 &0 ^2 &-3 ~1 @+ ^3
  &-3 ^3 &0 ^2 &-2 ~1 ^3
  &-2 ^3 &0 ^2 &-3 ~1 @- ^3
]
&-1 ~1 @- @print
"""

ir = builder.build(code)
rt = Runtime(can_direct_addressing=False)
rt.run(ir)
```

## cup 扩展

`src/cup.py` 提供可选的双端栈和二元运算。注册时将其与标准操作合并，并在使用前执行 `@init_cup`：

```python
from src import cup, pp3

builder = pp3.IRBuilder(op_map={**pp3.std_register, **cup.register})
rt = pp3.Runtime()
rt.run(builder.build("@init_cup &-5 @push &2 @push @div @print"))
```

输出 `-2`。二元运算把栈顶作为右操作数、次栈顶作为左操作数，结果写入 `view`，不会自动压回栈。

- `@push`、`@pop`：在右端压入当前 `view`、弹出到 `view`。
- `@push_left`、`@pop_left`：在左端压入当前 `view`、弹出到 `view`。
- `@add`、`@sub`、`@mul`：整数加、减、乘。
- `@div`：整数除法，按 C++ 规则向零截断；例如 `-5 / 2` 得到 `-2`，`5 / -2` 也得到 `-2`。计算不经过浮点数，大整数不会因浮点转换丢失精度。

操作数不足时抛出 `IndexError`，除数为零时抛出 `ZeroDivisionError`。二元运算失败会保留原栈及 `view`；成功后才移除两个操作数。栈仍保存在各 Runtime 的 `memory['_cup']` 中，`clear()` 会将其一并清除，之后需要重新初始化。

## 自动测试

在仓库根目录运行：

```text
python -B -m unittest discover -v
```

`tests/` 中的测试全部使用 Python 标准库，不需要安装第三方依赖。除原有测试外，还逐项比较参考路径与高速路径的 view、内存键值及插入顺序、输出、异常及字符缓冲；归档 20 个题库/研究程序作为离线样例，测试 IR 修改、扩展回调、缓存生命周期和编译失败回退。

`test/` 保留原有交互示例，不作为自动测试收集。GitHub Actions 会在 PR 和主分支提交上，分别于 Linux、Windows 运行 Python 3.10、3.12、3.14 的自动测试。

## 注意事项

- 指令之间必须用空格分隔。
- `@name` 必须提前注册到 `IRBuilder(op_map=...)`。
- 直接寻址默认关闭，需要显式使用 `Runtime(can_direct_addressing=True)`。
- 循环是否结束完全取决于循环体是否能让 `view` 变为 `0`。
- `memory` 的默认值是 `0`，这对间接寻址很重要。

## 许可证

本项目使用 `LICENSE` 文件中的许可证。

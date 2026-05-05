# PP3

PP3 是一个用 Python 实现的极简指令语言运行时。项目核心文件是 `src/pp3.py`，它提供：

- 一个基于 `view` 和 `memory` 的运行时 `Runtime`
- 一组基础指令 handler，例如读写内存、交换内存、输入输出、加一减一
- 一个 `IRBuilder`，用于把文本形式的 PP3 指令编译成可执行 IR
- 两种内存访问方式：直接寻址和间接寻址

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

常用属性：

- `rt.view`：当前视图值。
- `rt.memory`：运行时内存。

常用方法：

```python
rt.run(handles)
rt.clear()
```

- `run(handles)`：执行由 `IRBuilder.build()` 生成的 IR，或手动构造的 handler 列表。
- `clear()`：清空内存并把 `view` 重置为 `0`。

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

### 自定义操作

自定义操作需要继承 `InPlaceHandler` 并实现 `handle(self, runtime)`。

```python
from src.pp3 import *

class Double(InPlaceHandler):
    def handle(self, runtime):
        return runtime.view * 2

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

`handle()` 的返回值会成为新的 `runtime.view`。

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

## 注意事项

- 指令之间必须用空格分隔。
- `@name` 必须提前注册到 `IRBuilder(op_map=...)`。
- 直接寻址默认关闭，需要显式使用 `Runtime(can_direct_addressing=True)`。
- 循环是否结束完全取决于循环体是否能让 `view` 变为 `0`。
- `memory` 的默认值是 `0`，这对间接寻址很重要。

## 许可证

本项目使用 `LICENSE` 文件中的许可证。

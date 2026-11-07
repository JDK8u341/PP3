# 原生执行改动审查记录

本记录按 find-bugs 工作流检查此次改动；实施任务已授权修复，因此已确认的问题直接修复并附回归。

## 审查范围

逐项读取的实现：`src/pp3.py`、`src/_executor.py`、`src/_native.cpp`、`src/_native_guard.hpp`、`src/_native_jit.hpp`、`src/_native_codegen.py`、`src/_program.py`、`src/aot.py`、`src/jit.py`、`src/_toolchain.py`。

构建与验证：`setup.py`、`pyproject.toml`、`.gitignore`、`.github/workflows/tests.yml`、`tests/test_execution.py`、`tests/test_fixtures.py`、`tests/test_native.py`、`tests/test_aot.py`、`tests/test_jit.py`。

基准与文档：`benchmarks/run.py`、`benchmarks/aot_run.py`、`benchmarks/cpp_run.py`、`benchmarks/cpp_tasks.cpp`、`README.md`、`docs/executor.md`、`benchmarks/README.md`，以及对应 JSON 的测量字段和差分结果。固定 fixtures 未改。

## 输入与状态边界

输入来自现有 IR、Python handler、运行时字典、标准输入、编译输出目录和字节码内部接口。没有数据库、网络服务认证、Web 模板或会话功能。AOT 唯一外部命令是以参数列表运行本机 Python/setuptools/Clang，源代码只来自固定模板和验证后的整数。

Python 回调可以修改活动对象，因此进入前同步，返回后验证对象身份、字典条目、类和列表结构；不能依赖仅在最初编译时检查。JIT 通过拥有引擎引用的 capsule 绑定特定字节码，AOT 则验证目标结构，防止机器码与错配输入组合。

## 已修复问题

1. CPython 版本差异导致内置类型字典字段不可直接读取：3.12+ 使用 PyType_GetDict，核对返回引用所有权，并跳过不可变类型。
2. 原生快照 capsule 隐藏 Python 回环引用：改为 GC 可遍历的 Python 容器，新增 Runtime/handler 回环释放测试。
3. 回调抛错后旧原生图可能覆盖回调状态：设置物化边界标志，异常出口不重复写入旧状态。
4. 函数身份检查漏掉 `__code__` 原地修改：补充代码对象守卫和内存方法回归。
5. 原生溢出、负数取模与大整数回落：用显式范围检查/LLVM 溢出 intrinsic，补充 int64 两侧边界测试。
6. 活动列表改变后的续执行：保留原列表与索引，测试嵌套循环、追加节点、替换 body 和内存。
7. 错配 AOT/JIT 产物：执行前验证结构或特定字节码绑定，不进入不匹配的机器码。
8. 长时间原生运行阻塞中断线程：周期性让出 GIL，并验证非终止循环不会被误消除。

## 检查清单

| 类别 | 结论 |
| --- | --- |
| 命令/模板注入 | 使用参数数组，不执行 shell；生成模板无用户操作名拼接，任意整数通过常量表传递 |
| XSS、CSRF、认证、IDOR、会话 | 无对应网络/浏览器入口，不适用 |
| 竞争与生命周期 | 活动对象并发写入需外部同步；编译产物绑定生命周期；多进程同时写同一 AOT 目录未作为支持接口 |
| 密码学 | SHA256 只作产物内容标识，不作为签名或权限校验；不处理凭据 |
| 信息泄露 | 编译日志只保存本机编译诊断，无主动环境变量/凭据转储 |
| 资源消耗 | 编译输入、节点深度与缓存有界；DSL 可合法无限循环，保留可中断性 |
| 数值与状态逻辑 | 极值、缺失键顺序、图边失效、回调错误及模型摘要均有差分回归 |

## 未完全验证的范围

只支持当前 CI 所覆盖的普通 GIL CPython，未验证 free-threaded CPython、替代 Python VM、32 位 JIT、任意 audit hook/析构器的实现级观测或恶意通过 ctypes 篡改原生地址。改变物理存储无法保持原版的分配失败时刻；并发写活动状态不在无锁契约内。这些边界在设计文档中明示，不当作语言功能等价的普遍证明。

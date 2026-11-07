# 固定的真实程序

这些纯 DSL 文件及原始样例用于离线差分与性能测量，不读取测试输入生成答案。

- P001..P008 来自 [PP3-Challenges](https://github.com/JDK8u341/PP3-Challenges)，固定提交 `c5c4d638101fbbfc8abe12f81cbac2ef94a25b3d`。
- 其余 12 个来自 [PP3-Lab](https://github.com/JDK8u341/PP3-Lab)，固定提交 `3debbe3b5b580c2e4a86ab0f0c1d3ba050adfda6`。
- 两个来源均为同一维护者的 GPL-3.0 项目；保留源项目署名、版本和许可，原文件没有算法改写。

`manifest.json` 记录来源、提交、样例及将 CRLF/LF 统一为 LF 后的 ASCII 文本 SHA-256，避免操作系统换行影响检查。

需要重新导入时，先将两个源项目检出到上述固定提交，然后执行：

```text
python benchmarks/import_fixtures.py --challenges ../PP3-Challenges --lab ../PP3-Lab
```

正常测试和基准无需联网或检出其他项目。

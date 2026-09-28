# yolo_audit

面向遥感研究者的离线 YOLO 目标检测标注文本检查工具。仅使用 Python 3.10+ 标准库，无须安装软件包或依赖。从本仓库根目录执行命令即可。

工具不训练模型、不调用网络、不读取图片、不检查图片是否存在，也不修改原始标注。当前阶段不检查边框是否越出图像边界，因此 `0 0 1 1 1` 是合法标注。

## 运行

```console
python -m yolo_audit --labels examples/labels --num-classes 2 --output demo-report.json
python -m unittest discover -s tests -v
```

`examples/labels` 中全部为手工构造的**合成数据**，不来自真实数据集：`valid.txt` 有两个合法目标，`empty.txt` 是零字节无目标标注，`nested/invalid.txt` 有四行错误。演示命令预期退出码为 1，统计为 3 个文件、6 个非空行、2 个合法目标、4 个问题。

检查自己的标注：

```console
python -m yolo_audit --labels "D:/dataset/labels" --num-classes 5 --output "D:/reports/audit.json"
```

报告父目录必须已存在。报告不能放在 labels 目录内（包括经符号链接解析后落入其中的路径）。外部已有报告会被替换；写入使用同目录临时文件及原子替换。

## 排除目录与输出格式

`--exclude-dir` 可重复指定，路径相对于 labels 根目录，以 `/` 分隔，按完整路径组件、区分大小写精确匹配。例如 `cache` 排除根目录下的 `cache` 及全部后代，不排除 `cache2` 或 `nested/cache`；`nested/archive` 只排除该位置及其后代。被排除目录不遍历、不贡献任何统计；合法但不存在的目录忽略。不指定时保持原有扫描行为。

排除参数不得为空、含盘符、为绝对路径、含反斜杠、空组件或 `.`、`..` 组件。例如 `/cache`、`C:/cache`、`a//b`、`a/`、`a/../b` 均会在扫描前以退出码 2 拒绝。

以下命令继续使用上述合成数据，不修改输入：

```console
python -m yolo_audit --labels examples/labels --num-classes 2 --exclude-dir nested --exclude-dir cache --format json --output demo-excluded.json
python -m yolo_audit --labels examples/labels --num-classes 2 --format csv --output demo-issues.csv
python -m yolo_audit --help
```

第一条命令预期退出码为 0，扫描 2 个文件、2 个非空行、2 个合法目标、0 个问题，`class_counts` 为 `{"0": 1, "1": 1}`；不存在的 `cache` 不影响结果。第二条命令预期退出码为 1，扫描 3 个文件、6 个非空行、2 个合法目标、4 个问题，CSV 含表头和 4 条问题记录。

`--format json|csv` 默认 `json`，只按参数选择格式，与报告文件扩展名无关。两种格式均输出终端统计摘要，使用相同的输出路径保护、写入失败处理及退出码。

## 校验规则

- 递归检查扩展名严格为 `.txt` 的普通文件（区分大小写），跳过符号链接文件及目录；根目录也不能是符号链接。
- UTF-8 编码，可带文件头 BOM；允许空白行和空文件。
- 每个非空行恰有五个空白分隔字段：`class_id x_center y_center width height`。
- 类别编号仅含 ASCII 数字，允许前导零，范围为 `[0, num_classes)`。
- 四个坐标字段通过 Python `float()` 解析，必须有限；中心范围为 `[0,1]`，宽高为 `(0,1]`。
- 单行只记录首个可核实的问题，继续检查后续行与文件。
- 文件读取或解码失败时记录文件级问题，该文件计入扫描数，但不统计其行数及目标数。子目录无法访问时记录目录级问题，继续其他路径；这类报告不能视为完整覆盖全部文件。
- 扫描期间应保持输入目录稳定。

## JSON 字段

| 字段 | 含义 |
| --- | --- |
| `scanned_files` | 发现并尝试读取的 `.txt` 普通文件数，包括读取失败文件 |
| `nonempty_lines` | 成功读取并解码的文件中非空白行数 |
| `valid_objects` | 整行通过所有校验的目标数 |
| `class_counts` | 各合法类别的目标数，键为十进制字符串，按类别编号升序，仅列出实际出现的合法类别 |
| `issue_count` | `issues` 列表长度 |
| `issues` | 问题列表，每项含 `path`、`line`、`code`、`message` |

`path` 使用相对 labels 根目录的路径，分隔符为 `/`。`line` 从 1 开始，文件级或目录级问题为 JSON `null`。文件按相对路径排序检查；问题按路径、行号排序，同一路径的文件级问题在前。JSON 使用 UTF-8，保留中文。

类别键去除前导零，例如 `02` 和 `2` 合并为 `"2"`；非法行及被排除目录不贡献计数。`class_counts` 的值之和等于 `valid_objects`，没有合法目标时为 `{}`。其余原有 JSON 字段及含义保持不变。

## CSV 字段

CSV 仅输出与 JSON 中 `issues` 相同顺序的问题列表，不包含汇总统计或类别计数。固定表头为 `path,line,code,message`，文件级及目录级问题的 `line` 留空。无问题时仍输出表头。编码为 UTF-8 BOM，使用标准库 CSV 转义规则处理逗号、双引号和字段内换行；请用 CSV 解析器读取，不能简单按换行或逗号拆分。

问题代码：`FIELD_COUNT` 字段数量错误；`CLASS_FORMAT` 类别格式错误；`CLASS_RANGE` 类别越界；`NUMBER_FORMAT` 浮点解析失败；`NON_FINITE` 非有限数；`CENTER_RANGE` 中心越界；`SIZE_RANGE` 宽高越界；`FILE_READ` 文件读取或解码失败；`DIRECTORY_READ` 子目录扫描失败；`ENTRY_ACCESS` 目录项检查失败。

## 退出码

| 退出码 | 含义 |
| --- | --- |
| 0 | 扫描结束，无问题，报告写入成功 |
| 1 | 扫描结束，有标注或读取问题，报告写入成功 |
| 2 | 命令参数错误、根目录不可访问、报告位置不合法或写入失败；标准错误提供提示 |

## 模块

`validation.py` 负责单行校验；`scanner.py` 负责目录排除、遍历和统计；`reporting.py` 负责输出路径保护及 JSON/CSV 写入；`cli.py` 和 `__main__.py` 提供命令行入口。自动化测试使用标准库 `unittest`，临时测试文件只创建在本仓库内并自动清理。符号链接测试在系统不允许创建链接时会明确跳过。

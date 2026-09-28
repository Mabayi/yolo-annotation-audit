"""命令行参数和退出码。"""

import argparse
import sys
from pathlib import Path

from .reporting import validate_output, write_report
from .scanner import InputError, scan_labels, validate_exclude_dir


def exclude_directory(value: str) -> str:
    try:
        return validate_exclude_dir(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def positive_integer(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("类别数必须为正整数。") from exc
    if number <= 0:
        raise argparse.ArgumentTypeError("类别数必须为正整数。")
    return number


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="离线检查 YOLO 目标检测标注文本。")
    parser.add_argument("--labels", required=True, type=Path, help="标注根目录")
    parser.add_argument("--num-classes", required=True, type=positive_integer, help="正整数类别数")
    parser.add_argument("--output", required=True, type=Path, help="报告路径，父目录须已存在")
    parser.add_argument("--format", choices=("json", "csv"), default="json", help="报告格式，默认 json；不根据扩展名推断")
    parser.add_argument(
        "--exclude-dir", action="append", type=exclude_directory, default=[],
        metavar="RELATIVE_DIR", help="排除相对子目录及后代，以 / 分隔，可重复指定",
    )
    args = parser.parse_args(argv)
    try:
        validate_output(args.labels, args.output)
        report = scan_labels(args.labels, args.num_classes, args.exclude_dir)
        write_report(report, args.output, args.format)
    except (InputError, OSError, ValueError, RuntimeError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    print(
        f"扫描文件数：{report.scanned_files}；非空行数：{report.nonempty_lines}；"
        f"合法目标数：{report.valid_objects}；问题数：{len(report.issues)}。"
    )
    return 1 if report.issues else 0

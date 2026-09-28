"""输出位置校验与 JSON/CSV 报告写入。"""

import csv
import json
import os
import tempfile
from pathlib import Path

from .scanner import AuditReport


def validate_output(root: Path, output: Path) -> None:
    resolved_root = root.resolve()
    # 同时检查路径本身和符号链接目标，防止输入目录内的链接绕过保护。
    lexical_output = Path(os.path.abspath(output))
    parent_output = output.parent.resolve() / output.name
    for candidate in (lexical_output, parent_output, output.resolve()):
        if candidate == resolved_root or resolved_root in candidate.parents:
            raise ValueError("报告路径不能位于 labels 目录内。")
    if not output.parent.is_dir():
        raise ValueError("报告父目录必须已存在且为目录。")


def write_report(report: AuditReport, output: Path, report_format: str = "json") -> None:
    """同目录临时文件加原子替换，避免写入失败留下半份报告。"""
    if report_format not in ("json", "csv"):
        raise ValueError("报告格式必须为 json 或 csv。")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8-sig" if report_format == "csv" else "utf-8",
            newline="", dir=output.parent,
            prefix=".yolo_audit_", suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            if report_format == "json":
                json.dump(report.to_dict(), stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            else:
                writer = csv.writer(stream)
                writer.writerow(("path", "line", "code", "message"))
                for issue in report.issues:
                    writer.writerow((issue.path, issue.line, issue.code, issue.message))
        os.replace(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

"""递归扫描普通文件，不跟随符号链接。"""

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path, PureWindowsPath
from collections.abc import Sequence

from .validation import validate_line


class InputError(Exception):
    """输入根目录不可访问。"""


def validate_exclude_dir(value: str) -> str:
    """先校验原始字符串，避免路径规范化掩盖非法组件。"""
    if (
        not value or "\\" in value or PureWindowsPath(value).drive
        or any(part in ("", ".", "..") for part in value.split("/"))
    ):
        raise ValueError(
            "--exclude-dir 必须为以 / 分隔的相对子目录路径；"
            "不得为空、含盘符、绝对路径、反斜杠、空组件或 .、.. 组件。"
        )
    return value


@dataclass
class Issue:
    path: str
    line: int | None
    code: str
    message: str


@dataclass
class AuditReport:
    scanned_files: int = 0
    nonempty_lines: int = 0
    valid_objects: int = 0
    issues: list[Issue] = field(default_factory=list)
    class_counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "scanned_files": self.scanned_files,
            "nonempty_lines": self.nonempty_lines,
            "valid_objects": self.valid_objects,
            "issue_count": len(self.issues),
            "issues": [asdict(issue) for issue in self.issues],
            "class_counts": dict(sorted(
                self.class_counts.items(), key=lambda item: (len(item[0]), item[0]),
            )),
        }


def scan_labels(
    root: Path, num_classes: int, exclude_dirs: Sequence[str] = (),
) -> AuditReport:
    excluded = {tuple(validate_exclude_dir(value).split("/")) for value in exclude_dirs}
    if num_classes <= 0:
        raise ValueError("num_classes 必须为正整数。")
    if root.is_symlink():
        raise InputError("labels 根目录不能是符号链接。")
    report = AuditReport()
    files: list[Path] = []
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    path = Path(entry.path)
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            # 精确匹配组件；剪枝后无需再检查该目录的后代。
                            if path.relative_to(root).parts not in excluded:
                                pending.append(path)
                        elif entry.is_file(follow_symlinks=False) and path.suffix == ".txt":
                            files.append(path)
                    except OSError as exc:
                        report.issues.append(Issue(
                            path.relative_to(root).as_posix(), None,
                            "ENTRY_ACCESS", f"无法检查目录项：{exc}",
                        ))
        except OSError as exc:
            if directory == root:
                raise InputError(f"无法访问 labels 根目录：{exc}") from exc
            report.issues.append(Issue(
                directory.relative_to(root).as_posix(), None,
                "DIRECTORY_READ", f"无法扫描子目录：{exc}",
            ))

    for path in sorted(files, key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        report.scanned_files += 1
        try:
            content = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            report.issues.append(Issue(relative, None, "FILE_READ", f"无法读取 UTF-8 标注：{exc}"))
            continue
        for line_number, line in enumerate(content.split("\n"), start=1):
            if not line.strip():
                continue
            report.nonempty_lines += 1
            problem = validate_line(line, num_classes)
            if problem is None:
                report.valid_objects += 1
                class_id = line.split()[0].lstrip("0") or "0"
                report.class_counts[class_id] = report.class_counts.get(class_id, 0) + 1
            else:
                code, message = problem
                report.issues.append(Issue(relative, line_number, code, message))
    report.issues.sort(key=lambda issue: (issue.path, issue.line or 0))
    return report

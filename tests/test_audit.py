import json
import csv
import io
from contextlib import redirect_stderr
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from yolo_audit.cli import main
from yolo_audit.reporting import validate_output, write_report
from yolo_audit.scanner import AuditReport, InputError, Issue, scan_labels
from yolo_audit.validation import validate_line


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ValidationTests(unittest.TestCase):
    def test_valid(self) -> None:
        for line in ("0 0.5 0.5 0.2 0.3", "01\t0 1 1 1", "0 1e-1 0 1 0.1"):
            with self.subTest(line=line):
                self.assertIsNone(validate_line(line, 2))

    def test_invalid(self) -> None:
        cases = {
            "-1 .5 .5 .1 .1": "CLASS_FORMAT",
            "１ .5 .5 .1 .1": "CLASS_FORMAT",
            "+1 .5 .5 .1 .1": "CLASS_FORMAT",
            "1.0 .5 .5 .1 .1": "CLASS_FORMAT",
            "2 .5 .5 .1 .1": "CLASS_RANGE",
            "9" * 5000 + " .5 .5 .1 .1": "CLASS_RANGE",
            "0 .5 .5 .1": "FIELD_COUNT",
            "0 .5 .5 .1 .1 extra": "FIELD_COUNT",
            "0 text .5 .1 .1": "NUMBER_FORMAT",
            "0 nan .5 .1 .1": "NON_FINITE",
            "0 .5 inf .1 .1": "NON_FINITE",
            "0 .5 .5 -inf .1": "NON_FINITE",
            "0 .5 .5 .1 1e999": "NON_FINITE",
            "0 -.01 .5 .1 .1": "CENTER_RANGE",
            "0 .5 1.01 .1 .1": "CENTER_RANGE",
            "0 .5 .5 0 .1": "SIZE_RANGE",
            "0 .5 .5 .1 -0.1": "SIZE_RANGE",
            "0 .5 .5 1.01 .1": "SIZE_RANGE",
            "0 .5 .5 .1 1.01": "SIZE_RANGE",
        }
        for line, code in cases.items():
            with self.subTest(line=line[:80]):
                result = validate_line(line, 2)
                self.assertIsNotNone(result)
                self.assertEqual(result[0], code)  # type: ignore[index]


class FilesystemTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(dir=PROJECT_ROOT)
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.labels = self.base / "labels"
        self.labels.mkdir()

    def test_recursive_bom_blank_and_order(self) -> None:
        nested = self.labels / "nested"
        nested.mkdir()
        (nested / "bad.txt").write_text("\nwrong\n0 .5 .5 .1 .1\nwrong\n", encoding="utf-8")
        (self.labels / "empty.txt").write_bytes(b"")
        (self.labels / "blank.txt").write_text(" \n\t\n", encoding="utf-8")
        (self.labels / "valid.txt").write_text("0 0 1 1 1\r\n", encoding="utf-8-sig")
        (self.labels / "a.txt").write_bytes(b"\xff")
        (self.labels / "ignored.csv").write_text("bad", encoding="utf-8")
        report = scan_labels(self.labels, 2)
        self.assertEqual((report.scanned_files, report.nonempty_lines, report.valid_objects), (5, 4, 2))
        self.assertEqual([(issue.path, issue.line) for issue in report.issues], [
            ("a.txt", None), ("nested/bad.txt", 2), ("nested/bad.txt", 4),
        ])
        self.assertEqual(report.to_dict()["issue_count"], 3)

    def test_empty_annotations(self) -> None:
        (self.labels / "empty.txt").write_bytes(b"")
        report = scan_labels(self.labels, 1)
        self.assertEqual(report.to_dict(), {
            "scanned_files": 1, "nonempty_lines": 0, "valid_objects": 0,
            "issue_count": 0, "issues": [], "class_counts": {},
        })

    def test_unreadable_file_continues(self) -> None:
        (self.labels / "a.txt").touch()
        (self.labels / "b.txt").touch()
        with patch.object(Path, "read_text", side_effect=[PermissionError("拒绝访问"), "0 .5 .5 .1 .1"]):
            report = scan_labels(self.labels, 1)
        self.assertEqual(report.valid_objects, 1)
        self.assertEqual(report.issues[0].code, "FILE_READ")
        self.assertIsNone(report.issues[0].line)

    def test_root_inaccessible(self) -> None:
        with patch("yolo_audit.scanner.os.scandir", side_effect=PermissionError("拒绝访问")):
            with self.assertRaises(InputError):
                scan_labels(self.labels, 1)

    def test_symlinks_skipped_and_output_protected(self) -> None:
        outside = self.base / "outside"
        outside.mkdir()
        (outside / "bad.txt").write_text("bad", encoding="utf-8")
        try:
            (self.labels / "link.txt").symlink_to(outside / "bad.txt")
            (self.labels / "linked_dir").symlink_to(outside, target_is_directory=True)
            (self.base / "alias").symlink_to(self.labels, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"此环境无法创建符号链接：{exc}")
        self.assertEqual(scan_labels(self.labels, 1).scanned_files, 0)
        with self.assertRaises(ValueError):
            validate_output(self.labels, self.base / "alias" / "report.json")

    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "yolo_audit", *arguments],
            cwd=PROJECT_ROOT, capture_output=True, text=True, encoding="utf-8",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            check=False,
        )

    def test_cli_end_to_end(self) -> None:
        source = self.labels / "目标.txt"
        source.write_text("0 .5 .5 .1 .1\n", encoding="utf-8")
        output = self.base / "report.json"
        arguments = ["--labels", str(self.labels), "--num-classes", "1", "--output", str(output)]
        result = self.run_cli(*arguments)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["valid_objects"], 1)
        source.write_text("wrong\n0 .5 .5 .1 .1\n", encoding="utf-8")
        before = source.read_bytes()
        result = self.run_cli(*arguments)
        self.assertEqual(result.returncode, 1, result.stderr)
        raw = output.read_text(encoding="utf-8")
        self.assertIn("目标.txt", raw)
        self.assertIn("应有", raw)
        self.assertEqual(json.loads(raw)["issue_count"], 1)
        self.assertEqual(source.read_bytes(), before)

    def test_cli_errors(self) -> None:
        cases = [
            (self.labels, "0", self.base / "report.json"),
            (self.labels, "abc", self.base / "report.json"),
            (self.base / "missing", "1", self.base / "report.json"),
            (self.labels, "1", self.labels / "report.txt"),
            (self.labels, "1", self.base / "missing" / "report.json"),
            (self.labels, "1", self.base),
        ]
        for labels, count, output in cases:
            with self.subTest(labels=labels, count=count, output=output):
                result = self.run_cli("--labels", str(labels), "--num-classes", count, "--output", str(output))
                self.assertEqual(result.returncode, 2)
                self.assertTrue(result.stderr.strip())
        self.assertFalse((self.labels / "report.txt").exists())
        self.assertFalse(list(self.base.glob(".yolo_audit_*.tmp")))

    def test_exclusions_and_class_counts(self) -> None:
        contents = {
            "cache/deep/bad.txt": "bad\n0 .5 .5 .1 .1",
            "nested/archive/deeper/bad.txt": "bad\n1 .5 .5 .1 .1",
            "cache2/keep.txt": "10 .5 .5 .1 .1\n2 .5 .5 .1 .1",
            "nested/archive2/keep.txt": "02 .5 .5 .1 .1\n0 .5 .5 .1 .1",
            "nested/cache/keep.txt": "1 .5 .5 .1 .1\n2 nan .5 .1 .1",
        }
        for relative, content in contents.items():
            path = self.labels / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        excluded = ["cache", "nested/archive", "does/not/exist", "cache"]
        with patch("yolo_audit.scanner.os.scandir", wraps=os.scandir) as scandir:
            report = scan_labels(self.labels, 11, excluded)
        visited = {call.args[0].relative_to(self.labels).as_posix() for call in scandir.call_args_list}
        self.assertFalse(any(path == "cache" or path.startswith("cache/") for path in visited))
        self.assertNotIn("nested/archive", visited)
        self.assertEqual((report.scanned_files, report.nonempty_lines, report.valid_objects), (3, 6, 5))
        self.assertEqual(report.class_counts, {"0": 1, "1": 1, "2": 2, "10": 1})
        self.assertEqual(sum(report.class_counts.values()), report.valid_objects)
        self.assertEqual(list(report.to_dict()["class_counts"]), ["0", "1", "2", "10"])
        self.assertEqual(len(report.issues), 1)
        output = self.base / "excluded.json"
        args = ["--labels", str(self.labels), "--num-classes", "11", "--output", str(output)]
        for value in excluded:
            args.extend(("--exclude-dir", value))
        result = self.run_cli(*args)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(json.loads(output.read_text(encoding="utf-8")), report.to_dict())

    def test_nonexistent_exclusion_is_noop(self) -> None:
        (self.labels / "a.txt").write_text("0 .5 .5 .1 .1", encoding="utf-8")
        self.assertEqual(
            scan_labels(self.labels, 1).to_dict(),
            scan_labels(self.labels, 1, ["missing/deep"]).to_dict(),
        )

    def test_invalid_exclusions_rejected_before_scan(self) -> None:
        values = ["", "/cache", "C:/cache", "C:cache", "\\cache", "a\\b", "a//b", "a/", ".", "..", "a/./b", "a/../b", "//server/share"]
        for value in values:
            with self.subTest(value=value):
                error = io.StringIO()
                with patch("yolo_audit.cli.scan_labels") as scan, redirect_stderr(error):
                    with self.assertRaises(SystemExit) as result:
                        main([
                            "--labels", str(self.labels), "--num-classes", "1",
                            "--output", str(self.base / "out.json"), "--exclude-dir", value,
                        ])
                self.assertEqual(result.exception.code, 2)
                self.assertIn("--exclude-dir", error.getvalue())
                self.assertIn("相对子目录", error.getvalue())
                scan.assert_not_called()
        self.assertFalse((self.base / "out.json").exists())

    def test_csv_special_characters_and_file_level_line(self) -> None:
        report = AuditReport(issues=[
            Issue('目录/a,"b\n.txt', None, "FILE_READ", '无法读取,含"引号"\r\n下一行'),
            Issue("z.txt", 2, "FIELD_COUNT", "字段数量错误"),
        ])
        output = self.base / "special.csv"
        write_report(report, output, "csv")
        self.assertTrue(output.read_bytes().startswith(b"\xef\xbb\xbf"))
        with output.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.reader(stream))
        self.assertEqual(rows, [
            ["path", "line", "code", "message"],
            ['目录/a,"b\n.txt', "", "FILE_READ", '无法读取,含"引号"\r\n下一行'],
            ["z.txt", "2", "FIELD_COUNT", "字段数量错误"],
        ])

    def test_cli_csv_and_default_json(self) -> None:
        source = self.labels / "a.txt"
        source.write_text("wrong\n0 .5 .5 .1 .1", encoding="utf-8")
        (self.labels / "b.txt").write_bytes(b"\xff")
        json_output = self.base / "default.csv"
        csv_output = self.base / "explicit.json"
        args = ["--labels", str(self.labels), "--num-classes", "1"]
        result = self.run_cli(*args, "--output", str(json_output))
        self.assertEqual(result.returncode, 1, result.stderr)
        data = json.loads(json_output.read_text(encoding="utf-8"))
        self.assertEqual(set(data), {"scanned_files", "nonempty_lines", "valid_objects", "issue_count", "issues", "class_counts"})
        self.assertEqual((data["scanned_files"], data["nonempty_lines"], data["valid_objects"], data["issue_count"]), (2, 2, 1, 2))
        self.assertEqual(data["class_counts"], {"0": 1})
        result = self.run_cli(*args, "--output", str(csv_output), "--format", "csv")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("合法目标数：1", result.stdout)
        with csv_output.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(rows, [
            {**issue, "line": "" if issue["line"] is None else str(issue["line"])}
            for issue in data["issues"]
        ])
        source.write_text("0 .5 .5 .1 .1", encoding="utf-8")
        (self.labels / "b.txt").unlink()
        result = self.run_cli(*args, "--output", str(csv_output), "--format", "csv")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(csv_output.read_bytes(), b"\xef\xbb\xbfpath,line,code,message\r\n")

    def test_csv_output_errors_and_invalid_format(self) -> None:
        args = ["--labels", str(self.labels), "--num-classes", "1"]
        for output in (self.labels / "out.csv", self.base / "missing" / "out.csv", self.base):
            with self.subTest(output=output):
                result = self.run_cli(*args, "--format", "csv", "--output", str(output))
                self.assertEqual(result.returncode, 2)
                self.assertTrue(result.stderr.strip())
        result = self.run_cli(*args, "--format", "xml", "--output", str(self.base / "out.xml"))
        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.base / "out.xml").exists())
        self.assertFalse((self.labels / "out.csv").exists())
        self.assertFalse(list(self.base.glob(".yolo_audit_*.tmp")))


if __name__ == "__main__":
    unittest.main()

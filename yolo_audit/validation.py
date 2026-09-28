"""单行格式及数值校验。"""

import math


def validate_line(line: str, num_classes: int) -> tuple[str, str] | None:
    """返回首个可核实的问题；调用者应跳过空白行。"""
    fields = line.split()
    if len(fields) != 5:
        return "FIELD_COUNT", f"应有 5 个字段，实际为 {len(fields)} 个。"
    class_id = fields[0]
    if not class_id or any(char not in "0123456789" for char in class_id):
        return "CLASS_FORMAT", "class_id 必须仅由 ASCII 数字组成。"
    # 用十进制字符串比较，避免超长类别编号触发整数转换限制。
    normalized = class_id.lstrip("0") or "0"
    limit = str(num_classes)
    if len(normalized) > len(limit) or (
        len(normalized) == len(limit) and normalized >= limit
    ):
        return "CLASS_RANGE", f"class_id 必须满足 0 <= class_id < {num_classes}。"
    for name, raw in zip(("x_center", "y_center", "width", "height"), fields[1:]):
        try:
            value = float(raw)
        except (ValueError, OverflowError):
            return "NUMBER_FORMAT", f"{name} 无法解析为浮点数。"
        if not math.isfinite(value):
            return "NON_FINITE", f"{name} 必须是有限浮点数。"
        if name in ("x_center", "y_center"):
            if not 0 <= value <= 1:
                return "CENTER_RANGE", f"{name} 必须在 [0,1] 范围内。"
        elif not 0 < value <= 1:
            return "SIZE_RANGE", f"{name} 必须在 (0,1] 范围内。"
    return None

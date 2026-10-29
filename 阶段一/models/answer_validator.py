
import math


def validate_answer(question, value):
    """验证一道题的答案，合法时返回 None，否则返回错误信息。"""

    required = question.get("required", False)
    question_type = question.get("type")
    validation = question.get("validation", {})

    # 必答题不能留空
    if value is None or value == "":
        if required:
            return "本题为必答题，不能为空"
        return None

    # 单选题：答案必须来自有效选项
    if question_type == "single_choice":
        if not isinstance(value, str):
            return "单选题答案必须是字符串"

        valid_values = {
            option["value"]
            for option in question.get("options", [])
        }

        if value not in valid_values:
            return "单选题答案不属于有效选项"

    # 多选题：检查答案类型、选项合法性和选择数量
    elif question_type == "multiple_choice":
        if not isinstance(value, list):
            return "多选题答案必须是数组"

        if not value:
            if required:
                return "本题为必答题，至少选择一个选项"
            return None

        if not all(isinstance(item, str) for item in value):
            return "多选题的每个答案都必须是字符串"

        if len(value) != len(set(value)):
            return "多选题不能重复选择同一个选项"

        valid_values = {
            option["value"]
            for option in question.get("options", [])
        }

        if not set(value).issubset(valid_values):
            return "多选题包含无效选项"

        minimum = validation.get("minSelections", 0)
        maximum = validation.get(
            "maxSelections",
            len(valid_values)
        )

        if len(value) < minimum:
            return f"本题至少需要选择 {minimum} 个选项"

        if len(value) > maximum:
            return f"本题最多只能选择 {maximum} 个选项"

    # 文本填空题：检查类型和字符长度
    elif question_type == "text":
        if not isinstance(value, str):
            return "文本填空答案必须是字符串"

        if not value.strip() and required:
            return "本题为必答题，不能为空"

        if not value.strip():
            return None

        minimum = validation.get("minLength", 0)
        maximum = validation.get("maxLength", 1000)

        if len(value) < minimum:
            return f"答案至少需要 {minimum} 个字符"

        if len(value) > maximum:
            return f"答案最多只能有 {maximum} 个字符"

    # 数字填空题：检查数字类型、范围和整数限制
    elif question_type == "number":
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
        ):
            return "答案必须是数字"

        if isinstance(value, float) and not math.isfinite(value):
            return "答案必须是有限数字"

        # BSON 整数只能保存有符号 64 位值，避免入库时出现 OverflowError。
        if isinstance(value, int) and not -(2 ** 63) <= value < 2 ** 63:
            return "整数超出数据库可保存的范围"

        minimum = validation.get("min")
        maximum = validation.get("max")
        integer_only = validation.get("integerOnly", False)

        if minimum is not None and value < minimum:
            return f"答案不能小于 {minimum}"

        if maximum is not None and value > maximum:
            return f"答案不能大于 {maximum}"

        if integer_only and isinstance(value, float) and not value.is_integer():
            return "答案必须是整数"

    else:
        return "不支持的题目类型"

    return None


from models.answer_validator import validate_answer


single_question = {
    "type": "single_choice",
    "required": True,
    "options": [
        {"value": "online", "label": "线上学习"},
        {"value": "offline", "label": "线下学习"}
    ]
}

multiple_question = {
    "type": "multiple_choice",
    "required": True,
    "options": [
        {"value": "video", "label": "教学视频"},
        {"value": "book", "label": "教材"},
        {"value": "practice", "label": "练习"}
    ],
    "validation": {
        "minSelections": 2,
        "maxSelections": 3
    }
}

text_question = {
    "type": "text",
    "required": True,
    "validation": {
        "minLength": 5,
        "maxLength": 10
    }
}

number_question = {
    "type": "number",
    "required": True,
    "validation": {
        "min": 0,
        "max": 120,
        "integerOnly": True
    }
}


def check(name, question, value, should_pass):
    error = validate_answer(question, value)
    passed = error is None

    if passed == should_pass:
        print(f"PASS：{name}")
    else:
        raise AssertionError(f"FAIL：{name}，实际错误：{error}")


def main():
    check("单选有效选项", single_question, "online", True)
    check("单选无效选项", single_question, "unknown", False)
    check("必答题为空", single_question, "", False)

    check(
        "多选选择两个选项",
        multiple_question,
        ["video", "book"],
        True
    )
    check(
        "多选选择一个选项",
        multiple_question,
        ["video"],
        False
    )
    check(
        "多选重复选择",
        multiple_question,
        ["video", "video"],
        False
    )

    check("文本长度合法", text_question, "喜欢线上学习", True)
    check("文本长度不足", text_question, "好", False)

    check("年龄为整数", number_question, 18, True)
    check("年龄为小数", number_question, 18.5, False)
    check("年龄超过上限", number_question, 150, False)
    check("布尔值不能作为数字", number_question, True, False)


if __name__ == "__main__":
    main()

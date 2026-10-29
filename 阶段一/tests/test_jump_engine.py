
from models.jump_engine import (
    evaluate_condition,
    get_next_question
)


q1 = {
    "_id": "q1",
    "type": "single_choice",
    "order": 1,
    "jumpRules": [
        {
            "condition": {
                "operator": "equals",
                "value": "yes"
            },
            "targetQuestionId": "q3"
        }
    ]
}

q2 = {
    "_id": "q2",
    "type": "text",
    "order": 2,
    "jumpRules": []
}

q3 = {
    "_id": "q3",
    "type": "number",
    "order": 3,
    "jumpRules": [
        {
            "condition": {
                "operator": "gt",
                "value": 18
            },
            "targetQuestionId": "q5"
        }
    ]
}

q4 = {
    "_id": "q4",
    "type": "text",
    "order": 4,
    "jumpRules": []
}

q5 = {
    "_id": "q5",
    "type": "text",
    "order": 5,
    "jumpRules": []
}

survey = {
    "questions": [q1, q2, q3, q4, q5]
}


def check(name, condition):
    if condition:
        print(f"PASS：{name}")
    else:
        raise AssertionError(f"FAIL：{name}")


def main():
    check(
        "单选条件匹配",
        evaluate_condition("equals", "yes", "yes")
    )

    check(
        "单选条件不匹配",
        not evaluate_condition("equals", "no", "yes")
    )

    check(
        "多选包含指定选项",
        evaluate_condition(
            "contains", ["video", "book"], "video"
        )
    )

    check(
        "数字大于条件",
        evaluate_condition("gt", 20, 18)
    )

    check(
        "数字小于条件",
        evaluate_condition("lt", 16, 18)
    )

    check(
        "布尔值不能用于数字比较",
        not evaluate_condition("gt", True, 18)
    )

    check(
        "匹配规则后跳到 q3",
        get_next_question(survey, q1, "yes") == q3
    )

    check(
        "无匹配规则时进入下一题",
        get_next_question(survey, q1, "no") == q2
    )

    check(
        "数字答案满足条件时跳到 q5",
        get_next_question(survey, q3, 20) == q5
    )

    check(
        "数字答案不满足条件时进入 q4",
        get_next_question(survey, q3, 16) == q4
    )

    check(
        "最后一道题之后结束问卷",
        get_next_question(survey, q5, "完成") is None
    )


if __name__ == "__main__":
    main()


from bson import ObjectId


def evaluate_condition(operator, answer, expected):
    """判断一道题的答案是否满足指定条件。"""

    if operator == "equals":
        return answer == expected

    if operator == "contains":
        return (
            isinstance(answer, list)
            and expected in answer
        )

    if operator in {"gt", "gte", "lt", "lte"}:
        # 数字比较只接受数字，不接受布尔值
        if (
            not isinstance(answer, (int, float))
            or isinstance(answer, bool)
            or not isinstance(expected, (int, float))
            or isinstance(expected, bool)
        ):
            return False

        if operator == "gt":
            return answer > expected

        if operator == "gte":
            return answer >= expected

        if operator == "lt":
            return answer < expected

        if operator == "lte":
            return answer <= expected

    return False


def get_next_question(survey, current_question, answer):
    """
    根据当前答案确定下一道题。

    返回题目文档；问卷结束时返回 None。
    """

    questions = sorted(
        survey.get("questions", []),
        key=lambda question: question["order"]
    )

    current_id = current_question["_id"]
    current_order = current_question["order"]

    # 只允许跳转到本问卷中位于当前题之后的题目
    later_questions = [
        question for question in questions
        if question["order"] > current_order
    ]

    question_by_id = {
        str(question["_id"]): question
        for question in questions
    }

    for rule in current_question.get("jumpRules", []):
        condition = rule.get("condition", {})
        operator = condition.get("operator")
        expected = condition.get("value")

        if not evaluate_condition(operator, answer, expected):
            continue

        target_id = rule.get("targetQuestionId")
        target = question_by_id.get(str(target_id))

        # 目标必须存在，并且位于当前题之后
        if target is not None and target["order"] > current_order:
            return target

    # 没有规则匹配时，按顺序进入下一题
    if later_questions:
        return later_questions[0]

    # 已经是最后一道题
    return None

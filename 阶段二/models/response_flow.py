"""逐题填写和最终提交共用的状态检查与答题路径校验。"""
from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId

from models.answer_validator import validate_answer
from models.jump_engine import get_next_question


class ResponseFlowError(ValueError):
    def __init__(self, message, status=400, **details):
        super().__init__(message)
        self.status = status
        self.payload = {"error": message, **details}


def check_fillable(survey, now=None):
    if survey is None or survey.get("status") != "published":
        raise ResponseFlowError("问卷不存在、尚未发布或已关闭", 404)
    now = now or datetime.now(timezone.utc)
    deadline = survey.get("deadline")
    if deadline is not None:
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        if now >= deadline:
            raise ResponseFlowError("问卷已截止")


def walk_response_path(survey, answers, partial=False):
    """从第一题重算路径。逐题模式下缺少键表示尚未作答，null 表示主动跳过。"""
    if not isinstance(answers, dict):
        raise ResponseFlowError("answers 必须是以题目 ID 为键的 JSON 对象")
    questions = sorted(survey.get("questions", []), key=lambda q: q["order"])
    if not questions:
        raise ResponseFlowError("问卷没有题目")
    by_id = {str(q["_id"]): q for q in questions}
    for question_id in answers:
        try:
            ObjectId(question_id)
        except (InvalidId, TypeError):
            raise ResponseFlowError(f"题目 ID 无效：{question_id}")
        if question_id not in by_id:
            raise ResponseFlowError(f"题目不属于该问卷：{question_id}")

    visited = []
    saved = []
    current = questions[0]
    while current is not None:
        question_id = str(current["_id"])
        if question_id in visited:
            raise ResponseFlowError("问卷跳转配置存在循环")
        if partial and question_id not in answers:
            break
        value = answers.get(question_id)
        error = validate_answer(current, value)
        if error:
            raise ResponseFlowError(error, questionId=question_id)
        visited.append(question_id)
        # 允许跳过的空值不计入有效回答数量或统计。
        empty = (value is None or value == "" or value == []
                 or (isinstance(value, str) and not value.strip()))
        if not empty:
            item = {"questionId": current["_id"], "value": value}
            if current.get("sourceQuestionId") and current.get("sourceVersionId"):
                item.update({key: current[key] for key in ("sourceQuestionId", "sourceVersionId")})
            saved.append(item)
        current = get_next_question(survey, current, value)

    extra = set(answers) - set(visited)
    if extra:
        raise ResponseFlowError(
            "提交中包含按照跳转规则不应回答或尚未到达的题目",
            questionIds=sorted(extra)
        )
    return {"nextQuestion": current, "visitedQuestionIds": visited, "answers": saved}

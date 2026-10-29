"""Owner-scoped usage/statistics and immutable, CAS-selected compatibility events."""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import math

from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from models.database import db
from models.library_model import LibraryError, oid, text, version_content
from models.version_model import owned, revision, token, version_for
from models.answer_validator import validate_answer


METRICS = {"choiceDistribution": {"single_choice", "multiple_choice"},
           "numericMean": {"number"}, "numericDistribution": {"number"},
           "textResponses": {"text"}}


def candidates(user, qid, vid=None):
    match = {"sourceQuestionId": qid}
    if vid is not None:
        match["sourceVersionId"] = vid
    return list(db.surveys.find({"ownerId": user, "questions": {"$elemMatch": match}}))


def scope(user_id, question_id, version_id=None):
    user, qid = oid(user_id), oid(question_id)
    vid = oid(version_id) if version_id is not None else None
    question = db.questions.find_one({"_id": qid, "status": {"$in": ["active", "archived"]}})
    if question is None:
        raise LibraryError("题目不存在或无权统计", 404)
    surveys = candidates(user, qid, vid)
    live = question["ownerId"] == user or (question["status"] == "active" and bool(
        db.question_shares.find_one({"questionId": qid, "ownerId": question["ownerId"],
                                     "recipientUserId": user, "status": "active"})))
    # Existing own snapshots authorize only their historical statistics, never new reuse.
    if not live and not surveys:
        raise LibraryError("题目不存在或无权统计", 404)
    used = {q.get("sourceVersionId") for s in surveys for q in s["questions"]
            if q.get("sourceQuestionId") == qid and (vid is None or q.get("sourceVersionId") == vid)}
    query = {"questionId": qid}
    if vid is not None:
        query["_id"] = vid
    elif not live:
        query["_id"] = {"$in": list(used)}
    versions = list(db.question_versions.find(query).sort("versionNumber", 1))
    if vid is not None and (not versions or (not live and vid not in used)):
        raise LibraryError("版本不存在或无权统计", 404)
    return question, surveys, versions


def snapshot_matches(instance, version):
    content = version_content(instance)
    expected = deepcopy(version["content"])
    # required is the documented per-survey override; other content must be identical.
    content.pop("required", None)
    expected.pop("required", None)
    for key in ("unit", "semanticDescription"):
        content.setdefault(key, "")
    return content == expected


def instances_for(survey, qid, versions):
    return [q for q in survey["questions"] if q.get("sourceQuestionId") == qid
            and q.get("sourceVersionId") in versions
            and snapshot_matches(q, versions[q["sourceVersionId"]])]


def usage(user_id, question_id, version_id=None, limit="50", before=None):
    question, surveys, versions = scope(user_id, question_id, version_id)
    try:
        size = int(limit)
    except (ValueError, TypeError):
        raise LibraryError("limit 必须是1至100的整数")
    if str(size) != str(limit) or not 1 <= size <= 100:
        raise LibraryError("limit 必须是1至100的整数")
    cursor = oid(before) if before is not None else None
    by_id = {v["_id"]: v for v in versions}
    items = []
    for survey in surveys:
        instances = instances_for(survey, question["_id"], by_id)
        if instances:
            items.append({"surveyId": str(survey["_id"]), "title": survey["title"],
                          "status": survey["status"], "instances": [
                              {"instanceId": str(q["_id"]), "versionId": str(q["sourceVersionId"])}
                              for q in instances]})
    items.sort(key=lambda s: s["surveyId"], reverse=True)
    page = [s for s in items if cursor is None or s["surveyId"] < str(cursor)]
    return {"scope": "ownedSurveys", "surveyCount": len(items),
            "instanceCount": sum(len(s["instances"]) for s in items), "surveys": page[:size],
            "hasMore": len(page) > size,
            "nextBefore": page[size - 1]["surveyId"] if len(page) > size else None}


def accepted_events(question):
    """Only the pointer-reachable immutable chain is committed audit history."""
    event_id = question.get("statisticsEventId")
    while event_id is not None:
        event = db.question_statistics_events.find_one({"_id": event_id, "questionId": question["_id"]})
        if event is None:
            raise LibraryError("统计配置审计链不完整，请检查数据库", 500)
        yield event
        event_id = event["previousEventId"]


def public_event(event):
    return {"id": str(event["_id"]), "revision": event["revision"],
            "operationId": event["operationId"], "groups": deepcopy(event["groups"]),
            "confirmedBy": str(event["actorId"]), "confirmedAt": event["createdAt"].isoformat(),
            "reason": event["reason"], "warnings": event["warnings"]}


def configuration(user_id, question_id):
    question = owned(user_id, question_id)
    return {"revision": question.get("statisticsRevision", 0),
            "events": [public_event(e) for e in accepted_events(question)],
            "default": "每个版本独立；只合并当前配置明确确认的指标分组"}


def inspect_groups(qid, groups):
    if not isinstance(groups, list) or len(groups) > 100:
        raise LibraryError("groups 必须是数组，最多100组")
    result, warnings, seen, labels = [], [], set(), set()
    for group in groups:
        if not isinstance(group, dict) or set(group) != {"metric", "groupId", "versionIds"}:
            raise LibraryError("每组必须且只能包含 metric、groupId、versionIds")
        metric = group["metric"]
        if not isinstance(metric, str) or metric not in METRICS:
            raise LibraryError("不支持的统计指标")
        label = text(group["groupId"], "groupId", 100, empty=False)
        if (metric, label) in labels:
            raise LibraryError("同一指标的 groupId 不能重复")
        labels.add((metric, label))
        ids = group["versionIds"]
        if not isinstance(ids, list) or not 2 <= len(ids) <= 100:
            raise LibraryError("每个兼容组须包含2至100个不同版本")
        ids = [oid(v) for v in ids]
        if len(ids) != len(set(ids)) or any((metric, v) in seen for v in ids):
            raise LibraryError("同一指标中一个版本只能属于一个组")
        seen.update((metric, v) for v in ids)
        versions = [version_for(qid, v) for v in ids]
        contents = [v["content"] for v in versions]
        first = contents[0]
        if any(c["type"] not in METRICS[metric] or c["type"] != first["type"] for c in contents):
            raise LibraryError("题型与指标不兼容，不能合并")
        # Hard structural gates cannot be waived by the confirmation checkbox.
        keys = ["unit"]
        if metric == "choiceDistribution":
            keys += ["options"]
        elif metric.startswith("numeric"):
            keys += ["validation"]
            if any(not c.get("unit", "").strip() or not c.get("semanticDescription", "").strip()
                   for c in contents):
                raise LibraryError("数字跨版本合并必须填写单位和统计语义")
        if any(any(c.get(k) != first.get(k) for k in keys) for c in contents):
            raise LibraryError("选项标识/语义、单位或数字有效范围不一致，须分组统计")
        changed = [key for key in ("title", "semanticDescription", "required", "validation")
                   if any(c.get(key) != first.get(key) for c in contents)]
        if changed:
            warnings.append({"metric": metric, "groupId": label, "changedFields": changed})
        result.append({"metric": metric, "groupId": label, "versionIds": sorted(str(v) for v in ids)})
    result.sort(key=lambda g: (g["metric"], g["groupId"]))
    return result, warnings


def preview(user_id, question_id, data):
    question = owned(user_id, question_id)
    groups, warnings = inspect_groups(question["_id"], data.get("groups"))
    return {"groups": groups, "warnings": warnings, "requiresOwnerConfirmation": True,
            "revision": question.get("statisticsRevision", 0)}


def configure(user_id, question_id, data):
    question = owned(user_id, question_id)
    operation, expected = token(data.get("operationId")), revision(data.get("expectedRevision"))
    if data.get("confirmed") is not True:
        raise LibraryError("必须由所有者明确 confirmed=true 确认兼容性")
    reason = text(data.get("reason"), "reason", 2000, empty=False)
    groups, warnings = inspect_groups(question["_id"], data.get("groups"))
    event = db.question_statistics_events.find_one({"questionId": question["_id"], "operationId": operation})
    if event is None:
        if question.get("statisticsRevision", 0) != expected:
            raise LibraryError("统计配置已变化，请刷新后使用新的 operationId", 409)
        event = {"_id": ObjectId(), "questionId": question["_id"], "operationId": operation,
                 "actorId": oid(user_id), "createdAt": datetime.now(timezone.utc),
                 "revision": expected + 1, "expectedRevision": expected,
                 "previousEventId": question.get("statisticsEventId"), "groups": groups,
                 "reason": reason, "warnings": warnings}
        try:
            db.question_statistics_events.insert_one(deepcopy(event))
        except DuplicateKeyError:
            event = db.question_statistics_events.find_one({"questionId": question["_id"], "operationId": operation})
    if (event["groups"], event["reason"], event["expectedRevision"], event["actorId"]) != (
            groups, reason, expected, oid(user_id)):
        raise LibraryError("operationId 已绑定其他配置，不能改变重试内容", 409)
    question = owned(user_id, question_id)
    if any(e["_id"] == event["_id"] for e in accepted_events(question)):
        return {"event": public_event(event), "replayed": True}
    match = {"_id": question["_id"], "ownerId": oid(user_id), "status": {"$in": ["active", "archived"]},
             "statisticsEventId": event["previousEventId"]}
    if expected == 0:
        match["$or"] = [{"statisticsRevision": 0}, {"statisticsRevision": {"$exists": False}}]
    else:
        match["statisticsRevision"] = expected
    result = db.questions.update_one(match, {"$set": {"statisticsRevision": expected + 1,
                                                       "statisticsEventId": event["_id"]}})
    if not result.matched_count:
        # Another retry of this very event may have won concurrently.
        if any(e["_id"] == event["_id"] for e in accepted_events(owned(user_id, question_id))):
            return {"event": public_event(event), "replayed": True}
        raise LibraryError("统计配置已变化，本次配置未生效，请刷新后使用新的 operationId", 409)
    return {"event": public_event(event), "replayed": False}


def boundaries(values):
    if values is None:
        return None
    if (not isinstance(values, list) or not 2 <= len(values) <= 101
            or any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in values)):
        raise LibraryError("bins 必须包含2至101个有限递增数字")
    try:
        valid = all(math.isfinite(x) for x in values) and all(a < b for a, b in zip(values, values[1:]))
    except OverflowError:
        valid = False
    if not valid:
        raise LibraryError("bins 必须包含2至101个有限递增数字")
    return values


def summarize(content, values, bins):
    result = {"answerCount": len(values)}
    kind = content["type"]
    if kind in ("single_choice", "multiple_choice"):
        counts = Counter(v for value in values for v in (value if kind == "multiple_choice" else [value]))
        result["options"] = [{**o, "count": counts[o["value"]]} for o in content["options"]]
        result["selectionCount"] = sum(counts.values())
    elif kind == "number":
        # Scale before summing to avoid overflow of otherwise finite large samples.
        scale = max((abs(v) for v in values), default=0)
        result["mean"] = (math.fsum((v / scale) / len(values) for v in values) * scale
                          if scale else (0 if values else None))
        result["min"] = min(values) if values else None
        result["max"] = max(values) if values else None
        if bins is not None:
            counts = [0] * (len(bins) - 1)
            under = over = 0
            for value in values:
                if value < bins[0]:
                    under += 1
                elif value > bins[-1]:
                    over += 1
                else:
                    for i, (low, high) in enumerate(zip(bins, bins[1:])):
                        if low <= value < high or (i == len(counts) - 1 and value == high):
                            counts[i] += 1
                            break
            result["distribution"] = {"bins": bins, "counts": counts, "underflow": under, "overflow": over,
                                      "intervalRule": "[low,high); 最后一段包含右端点"}
        else:
            frequencies = sorted(Counter(values).items())
            result["distribution"] = {"frequencies": [{"value": v, "count": n} for v, n in frequencies[:100]],
                                      "truncated": len(frequencies) > 100,
                                      "remainingAnswerCount": sum(n for _, n in frequencies[100:])}
    else:
        result["texts"] = values[:100]
        result["textsTruncated"] = len(values) > 100
    return result


def statistics(user_id, question_id, version_id=None, bins=None):
    bins = boundaries(bins)
    question, surveys, versions = scope(user_id, question_id, version_id)
    by_id = {v["_id"]: v for v in versions}
    values = {vid: [] for vid in by_id}
    submitted = {vid: set() for vid in by_id}
    survey_sets = {vid: set() for vid in by_id}
    instance_counts = Counter()
    all_submissions, all_surveys = set(), set()
    excluded = Counter()
    for survey in surveys:
        instances = instances_for(survey, question["_id"], by_id)
        mapping = {q["_id"]: q for q in instances}
        vids = {q["sourceVersionId"] for q in instances}
        if not instances:
            continue
        all_surveys.add(survey["_id"])
        for q in instances:
            survey_sets[q["sourceVersionId"]].add(survey["_id"])
            instance_counts[q["sourceVersionId"]] += 1
        for response in db.responses.find({"surveyId": survey["_id"]}):
            all_submissions.add(response["_id"])
            for vid in vids:
                submitted[vid].add(response["_id"])
            # Corrupt duplicate items must not increase the answer count.
            duplicates = Counter(a["questionId"] for a in response["answers"])
            for answer in response["answers"]:
                instance = mapping.get(answer["questionId"])
                if instance is None:
                    continue
                vid = instance["sourceVersionId"]
                if (answer.get("sourceQuestionId") != question["_id"]
                        or answer.get("sourceVersionId") != vid):
                    excluded["unmappedOrMismatched"] += 1
                    continue
                value = answer["value"]
                if value is None or value == "" or value == [] or (isinstance(value, str) and not value.strip()):
                    excluded["empty"] += 1
                elif duplicates[answer["questionId"]] != 1 or validate_answer(instance, value):
                    excluded["invalid"] += 1
                else:
                    values[vid].append(value)
    current_event = next(accepted_events(question), None)
    config = current_event["groups"] if current_event else []
    groups = {}
    for version in versions:
        vid, content = version["_id"], version["content"]
        for metric, types in METRICS.items():
            if content["type"] not in types:
                continue
            configured = next((g for g in config if g["metric"] == metric and str(vid) in g["versionIds"]), None)
            # Include group kind to avoid a custom group ID colliding with a version ID.
            key = (metric, "confirmed" if configured else "version", configured["groupId"] if configured else str(vid))
            group = groups.setdefault(key, {"metric": metric, "groupId": key[2], "confirmed": bool(configured),
                                            "versionIds": [], "values": [], "content": content})
            group["versionIds"].append(str(vid))
            group["values"].extend(values[vid])
    overall = []
    for group in groups.values():
        summary = summarize(group.pop("content"), group.pop("values"), bins)
        if group["metric"] == "numericMean":
            summary.pop("distribution", None)
        elif group["metric"] == "numericDistribution":
            summary.pop("mean", None)
        elif group["metric"] == "textResponses":
            # Text excerpts remain exclusively in per-version details.
            summary = {"answerCount": summary["answerCount"]}
        overall.append({**group, **summary})
    return {"scope": "ownedSurveys", "questionId": str(question["_id"]),
            "surveyCount": len(all_surveys), "instanceCount": sum(instance_counts.values()),
            "submissionCount": len(all_submissions), "answerCount": sum(len(v) for v in values.values()),
            "independentPeopleAvailable": False,
            "independentPeopleReason": "匿名及重复提交不能可靠去重；不从参与记录反查匿名身份",
            "configurationRevision": question.get("statisticsRevision", 0), "excludedAnswers": dict(excluded),
            "overall": overall, "versions": [
                {"versionId": str(v["_id"]), "versionNumber": v["versionNumber"], "type": v["content"]["type"],
                 "surveyCount": len(survey_sets[v["_id"]]), "instanceCount": instance_counts[v["_id"]],
                 "submissionCount": len(submitted[v["_id"]]),
                 **summarize(v["content"], values[v["_id"]], bins)} for v in versions]}

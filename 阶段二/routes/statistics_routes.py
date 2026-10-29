"""Cross-survey statistics: source identity never grants access to another owner's data."""
import json

from flask import Blueprint, jsonify, request, session

from models import statistics_model as statistics
from models.library_model import LibraryError
from routes.library_routes import endpoint, body


statistics_bp = Blueprint("question_statistics", __name__, url_prefix="/api/questions")


@statistics_bp.get("/<question_id>/usage")
@endpoint
def usage(question_id):
    return jsonify(statistics.usage(session["user_id"], question_id, request.args.get("versionId"),
                                    request.args.get("limit", "50"), request.args.get("before")))


@statistics_bp.get("/<question_id>/statistics")
@endpoint
def summary(question_id):
    bins = None
    if "bins" in request.args:
        try:
            bins = json.loads(request.args["bins"])
        except (ValueError, TypeError):
            raise LibraryError("bins 必须是 JSON 数字数组")
        if bins is None:
            raise LibraryError("bins 必须是 JSON 数字数组")
    return jsonify(statistics.statistics(session["user_id"], question_id, request.args.get("versionId"), bins))


@statistics_bp.route("/<question_id>/statistics-configuration", methods=["GET", "PUT"])
@endpoint
def configuration(question_id):
    if request.method == "GET":
        return jsonify(statistics.configuration(session["user_id"], question_id))
    return jsonify(statistics.configure(session["user_id"], question_id, body()))


@statistics_bp.post("/<question_id>/statistics-configuration/preview")
@endpoint
def preview(question_id):
    return jsonify(statistics.preview(session["user_id"], question_id, body()))

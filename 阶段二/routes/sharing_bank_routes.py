"""Batch-4 share authorization and private bank APIs."""
from flask import Blueprint, jsonify, request, session

from models import sharing_bank_model as model
from models.library_model import LibraryError
from routes.library_routes import endpoint, body


sharing_bank_bp = Blueprint("sharing_banks", __name__, url_prefix="/api")


def paging():
    try:
        limit = int(request.args.get("limit", "50"))
    except ValueError:
        raise LibraryError("limit 必须为整数")
    return limit, request.args.get("before")


@sharing_bank_bp.route("/questions/<question_id>/shares", methods=["GET", "POST"])
@endpoint
def shares(question_id):
    if request.method == "POST":
        result, status = model.grant(session["user_id"], question_id, body())
        return jsonify(result), status
    limit, before = paging()
    return jsonify(model.share_history(session["user_id"], question_id, request.args.get("status"), limit, before))


@sharing_bank_bp.route("/questions/<question_id>/shares/<share_id>", methods=["DELETE"])
@endpoint
def revoke_share(question_id, share_id):
    return jsonify(model.revoke(session["user_id"], question_id, share_id))


@sharing_bank_bp.route("/shared-questions", methods=["GET"])
@endpoint
def received_shares():
    return jsonify(model.received(session["user_id"], *paging()))


@sharing_bank_bp.route("/question-banks", methods=["GET", "POST"])
@endpoint
def banks():
    if request.method == "POST":
        return jsonify(model.create_bank(session["user_id"], body())), 201
    return jsonify(model.list_banks(session["user_id"], *paging()))


@sharing_bank_bp.route("/question-banks/<bank_id>", methods=["GET", "PATCH", "DELETE"])
@endpoint
def bank(bank_id):
    user = session["user_id"]
    if request.method == "PATCH":
        return jsonify(model.update_bank(user, bank_id, body()))
    if request.method == "DELETE":
        return jsonify(model.delete_bank(user, bank_id))
    return jsonify({"bank": model.bank_json(model.bank_for(user, bank_id))})


@sharing_bank_bp.route("/question-banks/<bank_id>/items", methods=["GET", "POST"])
@endpoint
def items(bank_id):
    if request.method == "POST":
        return jsonify(model.add_item(session["user_id"], bank_id, body())), 201
    return jsonify(model.list_items(session["user_id"], bank_id, *paging()))


@sharing_bank_bp.route("/question-banks/<bank_id>/items/<item_id>", methods=["PUT", "DELETE"])
@endpoint
def item(bank_id, item_id):
    if request.method == "DELETE":
        return jsonify(model.remove_item(session["user_id"], bank_id, item_id))
    return jsonify(model.update_item(session["user_id"], bank_id, item_id, body()))


@sharing_bank_bp.route("/question-banks/<bank_id>/items/<item_id>/select", methods=["POST"])
@endpoint
def select_item(bank_id, item_id):
    return jsonify(model.select_item(session["user_id"], bank_id, item_id, body())), 201

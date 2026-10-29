from functools import wraps
from urllib.parse import urlsplit

from flask import Blueprint, redirect, render_template, request, session, url_for


pages_bp = Blueprint("pages", __name__)


def protected(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("pages.login_page", next=request.path))
        return view(*args, **kwargs)
    return wrapper


def safe_next():
    target = request.args.get("next", "/dashboard")
    parts = urlsplit(target)
    return target if target.startswith("/") and not target.startswith("//") and not parts.netloc and not parts.scheme and "\\" not in target else "/dashboard"


@pages_bp.route("/")
def home():
    return redirect("/dashboard" if session.get("user_id") else "/login")


@pages_bp.route("/login")
def login_page():
    return render_template("auth.html", page="login", title="欢迎回来", next_path=safe_next())


@pages_bp.route("/register")
def register_page():
    return render_template("auth.html", page="register", title="创建账号", next_path=safe_next())


@pages_bp.route("/dashboard")
@protected
def dashboard():
    return render_template("dashboard.html", page="dashboard", title="我的问卷")


@pages_bp.route("/surveys/new")
@protected
def create_page():
    return render_template("editor.html", page="editor", title="创建问卷", survey_id="")


@pages_bp.route("/surveys/<survey_id>/edit")
@protected
def editor(survey_id):
    return render_template("editor.html", page="editor", title="配置问卷", survey_id=survey_id)


@pages_bp.route("/survey/<survey_id>")
@protected
def fill(survey_id):
    return render_template("fill.html", page="fill", title="填写问卷", survey_id=survey_id)


@pages_bp.route("/surveys/<survey_id>/statistics")
@protected
def statistics(survey_id):
    return render_template("statistics.html", page="statistics", title="问卷统计", survey_id=survey_id)


@pages_bp.route("/library")
@protected
def library():
    return render_template("library.html", page="library", title="题目库")


@pages_bp.route("/question-banks")
@protected
def banks():
    return render_template("banks.html", page="banks", title="我的题库")


@pages_bp.route("/questions/<question_id>")
@protected
def question_detail(question_id):
    return render_template("question_detail.html", page="question", title="题目详情", question_id=question_id)


@pages_bp.route("/questions/<question_id>/statistics")
@protected
def question_statistics(question_id):
    return render_template("question_statistics.html", page="questionStats", title="跨问卷统计", question_id=question_id)

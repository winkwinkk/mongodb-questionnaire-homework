
import os

from flask import Flask, jsonify

from routes.auth_routes import auth_bp

from routes.survey_routes import survey_bp

from routes.question_routes import question_bp

from routes.jump_routes import jump_bp

from routes.response_routes import response_bp
from routes.page_routes import pages_bp
from routes.library_routes import library_bp
from routes.sharing_bank_routes import sharing_bank_bp
from routes.statistics_routes import statistics_bp

def create_app():
    app = Flask(__name__)

    # 必须在启动正式服务前设置安全的随机密钥
    app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY")

    if not app.config["SECRET_KEY"]:
        raise RuntimeError(
            "请先设置 FLASK_SECRET_KEY 环境变量"
        )

    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    app.register_blueprint(auth_bp)
    app.register_blueprint(survey_bp)
    app.register_blueprint(question_bp)
    app.register_blueprint(jump_bp)
    app.register_blueprint(response_bp)
    app.register_blueprint(pages_bp)
    app.register_blueprint(library_bp)
    app.register_blueprint(sharing_bank_bp)
    app.register_blueprint(statistics_bp)

    @app.route("/api/health")
    def index():
        return jsonify({
            "message": "问卷系统后端运行正常"
        })

    return app


if __name__ == "__main__":
    application = create_app()
    application.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")),
                    debug=os.environ.get("FLASK_DEBUG") == "1", use_reloader=False)

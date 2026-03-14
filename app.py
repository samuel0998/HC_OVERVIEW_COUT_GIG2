from flask import Flask

from config import Config
from models import db
from routes.hc import hc_bp


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)

    with app.app_context():
        from models.hc_gig2 import HCGig2  # noqa: F401
        db.create_all()

    app.register_blueprint(hc_bp)
    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

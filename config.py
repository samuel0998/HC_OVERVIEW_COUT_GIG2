import os


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "hc-gig2-secret-key")
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:WxmwezugggdaTwTvKsTiQrymIRkDAAvk@tramway.proxy.rlwy.net:41111/railway",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

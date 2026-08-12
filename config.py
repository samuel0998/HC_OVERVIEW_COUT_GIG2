import os


def _build_fc_databases():
    databases = {
        "GIG2": {
            "label": "GIG2",
            "uri": os.getenv(
                "DATABASE_URL_GIG2",
                os.getenv(
                    "DATABASE_URL",
                    "postgresql://postgres:WxmwezugggdaTwTvKsTiQrymIRkDAAvk@tramway.proxy.rlwy.net:41111/railway",
                ),
            ),
        },
        "CNF2": {
            "label": "CNF2",
            "uri": os.getenv(
                "DATABASE_URL_CNF2",
                "postgresql://postgres:AeBVwsTaDRTwwpkWJZHaiNFNvkIDKEEM@centerbeam.proxy.rlwy.net:29864/railway",
            ),
        },
        "CWB1": {
            "label": "CWB1",
            "uri": os.getenv(
                "DATABASE_URL_CWB1",
                "postgresql://postgres:QkVRaLlNIxaMFPJcghGxgWewwDSughzm@yamabiko.proxy.rlwy.net:30053/railway",
            ),
        },
    }

    databases["IXD_CNF2"] = {
        "label": "IXD - CNF2",
        "uri": os.getenv(
            "DATABASE_URL_IXD_CNF2",
            "postgresql://postgres:zSeySxWQzrZPWknNRoMfoxxdIYXfpSBp@sakura.proxy.rlwy.net:37193/railway?connect_timeout=5",
        ),
        # O IXD e inicializado sob demanda para nao bloquear o login caso
        # esse banco esteja temporariamente indisponivel.
        "bootstrap_on_startup": False,
    }

    return databases


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "hc-gig2-secret-key")
    FC_DATABASES = _build_fc_databases()
    SQLALCHEMY_DATABASE_URI = FC_DATABASES["GIG2"]["uri"]
    SQLALCHEMY_BINDS = {key: item["uri"] for key, item in FC_DATABASES.items()}
    DEFAULT_FC = os.getenv("DEFAULT_FC", "GIG2")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

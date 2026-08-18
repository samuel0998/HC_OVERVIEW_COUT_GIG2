import os


def _postgres_uri(env_name, fallback):
    """Retorna somente URLs PostgreSQL validas; referencias nao resolvidas usam o fallback."""
    value = (os.getenv(env_name) or "").strip().strip('"').strip("'")

    if value.startswith("postgres://"):
        value = "postgresql://" + value[len("postgres://"):]

    if value.startswith(("postgresql://", "postgresql+psycopg2://")):
        return value

    return fallback


def _build_fc_databases():
    databases = {
        "GIG2": {
            "label": "GIG2",
            "logo": "lion_logo.png",
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
            "logo": "bbb_logo.png",
            "uri": os.getenv(
                "DATABASE_URL_CNF2",
                "postgresql://postgres:AeBVwsTaDRTwwpkWJZHaiNFNvkIDKEEM@centerbeam.proxy.rlwy.net:29864/railway",
            ),
        },
        "CWB1": {
            "label": "CWB1",
            "logo": "lion_logo.png",
            "uri": os.getenv(
                "DATABASE_URL_CWB1",
                "postgresql://postgres:QkVRaLlNIxaMFPJcghGxgWewwDSughzm@yamabiko.proxy.rlwy.net:30053/railway",
            ),
        },
    }

    databases["IXD_CNF2"] = {
        "label": "IXD - CNF2",
        # Instancia IXD do mesmo FC fisico do CNF2 -> usa a mesma logo (bbb).
        "logo": "bbb_logo.png",
        "uri": _postgres_uri(
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

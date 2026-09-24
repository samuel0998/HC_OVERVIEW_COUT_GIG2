import os


def _forcar_driver_psycopg2(url):
    """Garante 'postgresql+psycopg2://' explicito em toda URL de conexao.

    Sem driver explicito, 'postgresql://' cai no dialeto padrao que o
    SQLAlchemy instalado resolver - e isso pode mudar sozinho entre builds
    (dependencia transitiva, sem pin de versao). Foi exatamente isso que
    derrubou o boot do gunicorn no Railway: um build resolveu 'postgresql://'
    para o dialeto psycopg (v3), que nao esta instalado (so' psycopg2-binary
    esta no requirements.txt) -> ModuleNotFoundError: No module named
    'psycopg'. Forcando o driver aqui, a escolha nunca mais fica implicita.
    """
    if not url:
        return url
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg2://" + url[len("postgresql://"):]
    return url


def _postgres_uri(env_name, fallback):
    """Retorna somente URLs PostgreSQL validas (com driver psycopg2 forcado);
    referencias nao resolvidas usam o fallback."""
    value = (os.getenv(env_name) or "").strip().strip('"').strip("'")

    if value.startswith("postgres://"):
        value = "postgresql://" + value[len("postgres://"):]

    if not value.startswith(("postgresql://", "postgresql+psycopg2://")):
        value = fallback

    return _forcar_driver_psycopg2(value)


def _optional_postgres_uri(env_name):
    """Retorna uma URL PostgreSQL configurada (com driver psycopg2 forcado), ou
    None quando a integração é opcional."""
    value = (os.getenv(env_name) or "").strip().strip('"').strip("'")
    if value.startswith("postgres://"):
        value = "postgresql://" + value[len("postgres://"):]
    if not value.startswith(("postgresql://", "postgresql+psycopg2://")):
        return None
    return _forcar_driver_psycopg2(value)


def _build_fc_databases():
    databases = {
        "GIG2": {
            "label": "GIG2",
            "logo": "lion_logo.png",
            "uri": _forcar_driver_psycopg2(os.getenv(
                "DATABASE_URL_GIG2",
                os.getenv(
                    "DATABASE_URL",
                    "postgresql://postgres:WxmwezugggdaTwTvKsTiQrymIRkDAAvk@tramway.proxy.rlwy.net:41111/railway",
                ),
            )),
        },
        "CNF2": {
            "label": "CNF2",
            "logo": "bbb_logo.png",
            "uri": _forcar_driver_psycopg2(os.getenv(
                "DATABASE_URL_CNF2",
                "postgresql://postgres:AeBVwsTaDRTwwpkWJZHaiNFNvkIDKEEM@centerbeam.proxy.rlwy.net:29864/railway",
            )),
        },
        "CWB1": {
            "label": "CWB1",
            "logo": "gralha_logo.jpg",
            "uri": _forcar_driver_psycopg2(os.getenv(
                "DATABASE_URL_CWB1",
                "postgresql://postgres:QkVRaLlNIxaMFPJcghGxgWewwDSughzm@yamabiko.proxy.rlwy.net:30053/railway",
            )),
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
    # Os tickets do Ariel LA Planning ficam em uma base separada. A integração é
    # opcional para manter o HC funcionando enquanto a variável ainda não foi criada.
    ARIEL_PLANNING_DATABASE_URL = _optional_postgres_uri("ARIEL_PLANNING_DATABASE_URL")
    SQLALCHEMY_BINDS = {
        **{key: item["uri"] for key, item in FC_DATABASES.items()},
        **({"ARIEL_PLANNING": ARIEL_PLANNING_DATABASE_URL} if ARIEL_PLANNING_DATABASE_URL else {}),
    }
    DEFAULT_FC = os.getenv("DEFAULT_FC", "GIG2")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

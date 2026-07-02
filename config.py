import os


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "hc-gig2-secret-key")
    FC_DATABASES = {
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
    SQLALCHEMY_DATABASE_URI = FC_DATABASES["GIG2"]["uri"]
    SQLALCHEMY_BINDS = {
        "GIG2": FC_DATABASES["GIG2"]["uri"],
        "CNF2": FC_DATABASES["CNF2"]["uri"],
        "CWB1": FC_DATABASES["CWB1"]["uri"],
    }
    DEFAULT_FC = os.getenv("DEFAULT_FC", "GIG2")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
#sdasd
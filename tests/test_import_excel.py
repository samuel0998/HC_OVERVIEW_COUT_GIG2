import io
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
from flask import Flask

from models import db
from models.hc_gig2 import HCGig2
from routes.hc import hc_bp


class ImportarExcelTest(unittest.TestCase):
    """A importação de colaboradores (botão "Importar CSV/Excel" no LIST) agora
    também aceita .xlsx, além de .csv (ver routes.hc._read_colaboradores_upload)."""

    def setUp(self):
        app = Flask(__name__)
        app.config.update(
            TESTING=True,
            LOGIN_DISABLED=True,
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        )
        db.init_app(app)
        app.register_blueprint(hc_bp)
        self.context = app.app_context()
        self.context.push()
        self.addCleanup(self.context.pop)
        self.addCleanup(db.session.remove)
        HCGig2.__table__.create(db.engine)
        self.client = app.test_client()
        user = patch("routes.hc.current_user", SimpleNamespace(is_authenticated=True))
        user.start()
        self.addCleanup(user.stop)

    @staticmethod
    def _xlsx_bytes(df):
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            df.to_excel(writer, index=False)
        buffer.seek(0)
        return buffer

    def test_importa_xlsx_com_cabecalho_padrao(self):
        df = pd.DataFrame([
            {"Nome Completo": "Fulano de Tal", "Login": "fdetal", "Cargo": "PIT",
             "Area": "OUTBOUND", "Turno": "RED NIGHT", "Status": "Operacional"},
        ])
        arquivo = self._xlsx_bytes(df)

        response = self.client.post(
            "/api/hc/import-csv",
            data={"arquivo": (arquivo, "colaboradores.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        data = response.get_json()
        self.assertEqual(data["inseridos"], 1)

        colaborador = HCGig2.query.filter_by(login="fdetal").first()
        self.assertIsNotNone(colaborador)
        self.assertEqual(colaborador.nome_completo, "Fulano de Tal")
        self.assertEqual(colaborador.cargo, "PIT")

    def test_importa_xlsx_exportado_do_sharepoint_com_coluna_title(self):
        # Mesmo formato da captura enviada: cabeçalho "Title" em vez de "Nome Completo".
        df = pd.DataFrame([
            {"ID": 1, "Title": "Abias Jonathas Paulino Da Silva", "Login": "abiasxjo",
             "Cargo": "PIT", "Area": "OUTBOUND", "Turno": "RED NIGHT", "STATUS": "Operacional",
             "Tipo de Item": "Item", "Caminho": "personal/x/Lists/HC"},
        ])
        arquivo = self._xlsx_bytes(df)

        response = self.client.post(
            "/api/hc/import-csv",
            data={"arquivo": (arquivo, "HC GIG2 LABOR.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        colaborador = HCGig2.query.filter_by(login="abiasxjo").first()
        self.assertIsNotNone(colaborador)
        self.assertEqual(colaborador.nome_completo, "Abias Jonathas Paulino Da Silva")

    def test_csv_continua_funcionando(self):
        csv_bytes = io.BytesIO(
            "Nome Completo,Login,Cargo,Area,Turno,Status\n"
            "Ciclana de Tal,cdetal,Associado,INBOUND,BLUE DAY,Operacional\n".encode("utf-8-sig")
        )
        response = self.client.post(
            "/api/hc/import-csv",
            data={"arquivo": (csv_bytes, "colaboradores.csv")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertIsNotNone(HCGig2.query.filter_by(login="cdetal").first())


if __name__ == "__main__":
    unittest.main()

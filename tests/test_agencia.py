import io
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
from flask import Flask

from models import db
from models.hc_gig2 import HCGig2
from models.lc_atual import LCAtual
from models.registro_atividade import RegistroAtividade
from routes.hc import hc_bp


class AgenciaTest(unittest.TestCase):
    """Coluna Agência no LIST: edição manual, import em massa (login -> agência)
    e filtro no Dashboard (ver routes.hc.importar_agencias / dashboard_data)."""

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
        LCAtual.__table__.create(db.engine)
        self.client = app.test_client()
        self.user = patch("routes.hc.current_user", SimpleNamespace(
            is_authenticated=True, login="tester", nome="Testador", can_edit=True,
        ))
        self.user.start()
        self.addCleanup(self.user.stop)
        history = patch("routes.hc._registrar")
        history.start()
        self.addCleanup(history.stop)

    def _colaborador(self, **kwargs):
        colaborador = HCGig2(**kwargs)
        db.session.add(colaborador)
        db.session.commit()
        return colaborador

    @staticmethod
    def _xlsx_bytes(df):
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            df.to_excel(writer, index=False)
        buffer.seek(0)
        return buffer

    def test_edicao_manual_grava_agencia(self):
        colaborador = self._colaborador(nome_completo="Fulano", cargo="Associado", status="OPERACIONAL")
        response = self.client.put(f"/api/hc/{colaborador.id}", json={
            "agencia": "Agência Alfa", "status": "OPERACIONAL",
        })
        self.assertEqual(response.status_code, 200)
        db.session.refresh(colaborador)
        self.assertEqual(colaborador.agencia, "Agência Alfa")

        item = response.get_json()["item"]
        self.assertEqual(item["agencia"], "Agência Alfa")

    def test_import_agencias_atualiza_por_login_com_cabecalho(self):
        a = self._colaborador(nome_completo="A", login="loginA", cargo="Associado", status="OPERACIONAL")
        b = self._colaborador(nome_completo="B", login="loginB", cargo="Associado", status="OPERACIONAL")

        df = pd.DataFrame([
            {"Login": "loginA", "Agência": "Agência Alfa"},
            {"Login": "loginB", "Agência": "Agência Beta"},
            {"Login": "naoexiste", "Agência": "Agência Gama"},
        ])
        arquivo = self._xlsx_bytes(df)

        response = self.client.post(
            "/api/hc/import-agencias",
            data={"arquivo": (arquivo, "agencias.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        data = response.get_json()
        self.assertEqual(data["atualizados"], 2)
        self.assertEqual(data["total_nao_encontrados"], 1)
        self.assertIn("naoexiste", data["nao_encontrados"])

        db.session.refresh(a)
        db.session.refresh(b)
        self.assertEqual(a.agencia, "Agência Alfa")
        self.assertEqual(b.agencia, "Agência Beta")

    def test_import_agencias_funciona_sem_cabecalho_reconhecivel_por_posicao(self):
        colaborador = self._colaborador(nome_completo="C", login="loginc", cargo="Associado", status="OPERACIONAL")
        # Cabeçalhos genéricos (coluna A = login, coluna B = agência, como pedido).
        df = pd.DataFrame([{"Coluna1": "loginc", "Coluna2": "Agência Delta"}])
        arquivo = self._xlsx_bytes(df)

        response = self.client.post(
            "/api/hc/import-agencias",
            data={"arquivo": (arquivo, "agencias.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        db.session.refresh(colaborador)
        self.assertEqual(colaborador.agencia, "Agência Delta")

    def test_import_agencias_nao_mexe_em_quem_nao_esta_na_planilha(self):
        intacto = self._colaborador(nome_completo="Intacto", login="intacto1", cargo="Associado", agencia="Original", status="OPERACIONAL")
        df = pd.DataFrame([{"Login": "outrologin", "Agência": "Nova"}])
        arquivo = self._xlsx_bytes(df)

        self.client.post(
            "/api/hc/import-agencias",
            data={"arquivo": (arquivo, "agencias.xlsx")},
            content_type="multipart/form-data",
        )
        db.session.refresh(intacto)
        self.assertEqual(intacto.agencia, "Original")

    def test_import_agencias_exige_permissao(self):
        with patch("routes.hc.current_user", SimpleNamespace(is_authenticated=True, login="x", nome="X", can_edit=False)):
            response = self.client.post("/api/hc/import-agencias", data={}, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 403)

    def test_dashboard_filtra_por_agencia_e_lista_disponiveis(self):
        self._colaborador(nome_completo="X1", cargo="Associado", status="OPERACIONAL", agencia="Agência Alfa")
        self._colaborador(nome_completo="X2", cargo="Associado", status="OPERACIONAL", agencia="Agência Beta")

        resposta = self.client.get("/api/hc/dashboard?agencia=Agência Alfa").get_json()
        self.assertEqual(resposta["cards"]["hc_total"], 1)
        self.assertIn("Agência Alfa", resposta["filtros_disponiveis"]["agencias"])
        self.assertIn("Agência Beta", resposta["filtros_disponiveis"]["agencias"])

    def test_export_inclui_coluna_agencia_e_filtra(self):
        self._colaborador(nome_completo="Export1", cargo="Associado", status="OPERACIONAL", agencia="Agência Alfa")
        self._colaborador(nome_completo="Export2", cargo="Associado", status="OPERACIONAL", agencia="Agência Beta")

        import openpyxl
        response = self.client.get("/api/hc/export?agencia=Agência Alfa")
        self.assertEqual(response.status_code, 200)
        wb = openpyxl.load_workbook(io.BytesIO(response.data))
        linhas = list(wb.active.iter_rows(values_only=True))
        cabecalho = linhas[0]
        self.assertIn("Agência", cabecalho)
        self.assertEqual(len(linhas) - 1, 1)


class AgenciaHistoricoTest(unittest.TestCase):
    """Troca de agência fica registrada no Histórico, igual setor/turno/cargo."""

    def setUp(self):
        app = Flask(__name__)
        app.config.update(TESTING=True, LOGIN_DISABLED=True, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
        db.init_app(app)
        app.register_blueprint(hc_bp)
        self.context = app.app_context()
        self.context.push()
        self.addCleanup(self.context.pop)
        self.addCleanup(db.session.remove)
        HCGig2.__table__.create(db.engine)
        RegistroAtividade.__table__.create(db.engine)
        self.client = app.test_client()
        user = patch("routes.hc.current_user", SimpleNamespace(is_authenticated=True, login="t", nome="T", can_edit=True))
        user.start()
        self.addCleanup(user.stop)

    def test_troca_de_agencia_aparece_na_descricao_do_historico(self):
        colaborador = HCGig2(nome_completo="Teste Hist", cargo="Associado", status="OPERACIONAL", agencia="Agência Antiga")
        db.session.add(colaborador)
        db.session.commit()

        response = self.client.put(f"/api/hc/{colaborador.id}", json={
            "agencia": "Agência Nova", "status": "OPERACIONAL",
        })
        self.assertEqual(response.status_code, 200)

        registro = RegistroAtividade.query.filter_by(operador_id=colaborador.id).first()
        self.assertIn("agência: Agência Antiga → Agência Nova", registro.descricao)

        alteracoes = registro.to_dict()["alteracoes"]
        agencia_alteracao = next(a for a in alteracoes if a["campo"] == "Agência")
        self.assertEqual(agencia_alteracao["de"], "Agência Antiga")
        self.assertEqual(agencia_alteracao["para"], "Agência Nova")


if __name__ == "__main__":
    unittest.main()

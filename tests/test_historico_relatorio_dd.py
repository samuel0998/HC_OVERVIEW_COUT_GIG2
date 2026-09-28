import unittest
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import openpyxl
from flask import Flask

from models import db
from models.hc_gig2 import HCGig2
from models.registro_atividade import RegistroAtividade
from routes.hc import hc_bp


class HistoricoRelatorioDDTest(unittest.TestCase):
    """Filtros novos do Registro de Atividades (cargo/setor/turno/status atuais
    + período) e a exportação em Excel pro relatório de DD (ver
    routes.hc._historico_query / listar_historico / exportar_historico)."""

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
        RegistroAtividade.__table__.create(db.engine)
        self.client = app.test_client()
        self.user = patch("routes.hc.current_user", SimpleNamespace(
            is_authenticated=True, login="tester", nome="Testador", can_historico=True,
        ))
        self.user.start()
        self.addCleanup(self.user.stop)

    def _colaborador(self, **kwargs):
        colaborador = HCGig2(**kwargs)
        db.session.add(colaborador)
        db.session.commit()
        return colaborador

    def _registro(self, operador, tipo="edicao", timestamp=None):
        reg = RegistroAtividade(
            tipo=tipo,
            operador_id=operador.id if operador else None,
            operador_login=operador.login if operador else None,
            operador_nome=operador.nome_completo if operador else "Fantasma",
            usuario_login="tester",
            usuario_nome="Testador",
            descricao=f"Evento de teste ({tipo})",
            timestamp=timestamp or datetime.utcnow(),
        )
        db.session.add(reg)
        db.session.commit()
        return reg

    def test_filtra_por_cargo_setor_turno_status_atual(self):
        pit = self._colaborador(nome_completo="PIT Um", login="pit1", cargo="PIT", area="INBOUND", turno="BLUE DAY", status="OPERACIONAL")
        aa = self._colaborador(nome_completo="AA Um", login="aa1", cargo="Associado", area="OUTBOUND", turno="RED NIGHT", status="OPERACIONAL")
        self._registro(pit)
        self._registro(aa)

        response = self.client.get("/api/hc/historico?cargo=PIT")
        self.assertEqual(response.status_code, 200)
        itens = response.get_json()
        self.assertEqual(len(itens), 1)
        self.assertEqual(itens[0]["operador_login"], "pit1")
        self.assertEqual(itens[0]["cargo_atual"], "PIT")
        self.assertEqual(itens[0]["area_atual"], "INBOUND")
        self.assertEqual(itens[0]["turno_atual"], "BLUE DAY")
        self.assertEqual(itens[0]["status_atual"], "OPERACIONAL")

        response2 = self.client.get("/api/hc/historico?area=OUTBOUND&turno=RED NIGHT&status=OPERACIONAL")
        itens2 = response2.get_json()
        self.assertEqual(len(itens2), 1)
        self.assertEqual(itens2[0]["operador_login"], "aa1")

    def test_registro_de_colaborador_excluido_some_so_com_filtro_atual(self):
        fantasma = self._colaborador(nome_completo="Vai Sumir", login="sumiu1", cargo="PIT", area="INBOUND", turno="BLUE DAY", status="OPERACIONAL")
        self._registro(fantasma, tipo="exclusao")
        db.session.delete(fantasma)
        db.session.commit()

        sem_filtro = self.client.get("/api/hc/historico").get_json()
        self.assertEqual(len(sem_filtro), 1)
        self.assertEqual(sem_filtro[0]["cargo_atual"], "")

        com_filtro_cargo = self.client.get("/api/hc/historico?cargo=PIT").get_json()
        self.assertEqual(len(com_filtro_cargo), 0)

    def test_filtra_por_periodo(self):
        colaborador = self._colaborador(nome_completo="Teste Periodo", login="periodo1", cargo="PIT", status="OPERACIONAL")
        self._registro(colaborador, timestamp=datetime(2026, 1, 10))
        self._registro(colaborador, timestamp=datetime(2026, 6, 15))

        resposta = self.client.get("/api/hc/historico?data_de=2026-06-01&data_ate=2026-06-30").get_json()
        self.assertEqual(len(resposta), 1)

    def test_export_gera_xlsx_com_filtros_aplicados(self):
        pit = self._colaborador(nome_completo="PIT Export", login="pitexp", cargo="PIT", area="INBOUND", turno="BLUE DAY", status="OPERACIONAL")
        aa = self._colaborador(nome_completo="AA Export", login="aaexp", cargo="Associado", area="OUTBOUND", turno="RED NIGHT", status="OPERACIONAL")
        self._registro(pit)
        self._registro(aa)

        response = self.client.get("/api/hc/historico/export?cargo=PIT")
        self.assertEqual(response.status_code, 200)
        self.assertIn("spreadsheetml", response.content_type)

        import io
        wb = openpyxl.load_workbook(io.BytesIO(response.data))
        ws = wb.active
        linhas = list(ws.iter_rows(values_only=True))
        cabecalho = linhas[0]
        self.assertIn("Cargo atual", cabecalho)
        self.assertEqual(len(linhas) - 1, 1)  # só o PIT, filtrado
        idx_cargo = cabecalho.index("Cargo atual")
        self.assertEqual(linhas[1][idx_cargo], "PIT")

    def test_export_exige_permissao_de_historico(self):
        with patch("routes.hc.current_user", SimpleNamespace(
            is_authenticated=True, login="x", nome="X", can_historico=False,
        )):
            response = self.client.get("/api/hc/historico/export")
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()

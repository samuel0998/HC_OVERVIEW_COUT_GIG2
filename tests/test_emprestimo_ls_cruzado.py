import unittest
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask
from sqlalchemy.orm import sessionmaker

from models import db
from models.hc_gig2 import HCGig2
from models.registro_atividade import RegistroAtividade
from models.turno_config import HCTurnoConfig
from routes.hc import hc_bp


class EmprestimoLSCruzadoTest(unittest.TestCase):
    """Empréstimo (LS) TEMPORÁRIO entre os bancos-irmãos CNF2 e IXD - CNF2: mesma
    regra do LS normal (retorna na data marcada, ou 24h depois se for hoje), só
    que o colaborador migra fisicamente pro banco do site de destino enquanto
    dura o empréstimo (ver routes.hc.emprestimo_ls_cruzado)."""

    def setUp(self):
        app = Flask(__name__)
        app.config.update(
            TESTING=True,
            LOGIN_DISABLED=True,
            SECRET_KEY="teste",
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            SQLALCHEMY_BINDS={
                "CNF2": "sqlite:///:memory:",
                "IXD_CNF2": "sqlite:///:memory:",
            },
            FC_DATABASES={
                "CNF2": {"label": "CNF2"},
                "IXD_CNF2": {"label": "IXD - CNF2"},
            },
        )
        db.init_app(app)
        app.register_blueprint(hc_bp)
        self.context = app.app_context()
        self.context.push()
        self.addCleanup(self.context.pop)
        self.addCleanup(db.session.remove)

        for fc in ("CNF2", "IXD_CNF2"):
            HCGig2.__table__.create(bind=db.engines[fc])
            RegistroAtividade.__table__.create(bind=db.engines[fc])
            HCTurnoConfig.__table__.create(bind=db.engines[fc])

        self.client = app.test_client()

        migrar = patch("routes.hc._ensure_destino_migrado")
        migrar.start()
        self.addCleanup(migrar.stop)

        user = patch("routes.hc.current_user", SimpleNamespace(
            can_edit=True, is_authenticated=True, login="tester", nome="Testador",
        ))
        user.start()
        self.addCleanup(user.stop)

    def _com_fc(self, fc):
        with self.client.session_transaction() as sess:
            sess["fc"] = fc

    @staticmethod
    def _criar_em(fc, **kwargs):
        sessao = sessionmaker(bind=db.engines[fc])()
        colaborador = HCGig2(**kwargs)
        sessao.add(colaborador)
        sessao.commit()
        item_id = colaborador.id
        sessao.close()
        return item_id

    def test_emprestimo_move_para_o_outro_banco_com_status_ls(self):
        self._com_fc("CNF2")
        item_id = self._criar_em(
            "CNF2", nome_completo="Fulano", login="fulano1", cargo="Associado",
            area="OUTBOUND", turno="RED NIGHT", status="OPERACIONAL",
        )

        retorno = date.today() + timedelta(days=5)
        response = self.client.post(f"/api/hc/{item_id}/emprestimo-site", json={
            "destino_fc": "IXD_CNF2",
            "area_destino": "INBOUND",
            "ls_retorno_data": retorno.isoformat(),
        })
        self.assertEqual(response.status_code, 200, response.get_json())

        CNFSession = sessionmaker(bind=db.engines["CNF2"])()
        IXDSession = sessionmaker(bind=db.engines["IXD_CNF2"])()
        try:
            self.assertIsNone(CNFSession.get(HCGig2, item_id))

            novo = IXDSession.query(HCGig2).filter_by(login="fulano1").first()
            self.assertIsNotNone(novo)
            self.assertEqual(novo.status, "LS")
            self.assertEqual(novo.area, "INBOUND")
            self.assertEqual(novo.turno, "RED NIGHT")
            self.assertEqual(novo.ls_area_origem, "OUTBOUND")
            self.assertEqual(novo.ls_turno_origem, "RED NIGHT")
            self.assertEqual(novo.ls_site_origem, "CNF2")
            self.assertEqual(novo.ls_retorno_data, retorno)

            self.assertIsNotNone(IXDSession.query(RegistroAtividade).filter_by(tipo="agendamento_ls").first())
            self.assertIsNotNone(CNFSession.query(RegistroAtividade).filter_by(tipo="agendamento_ls").first())
        finally:
            CNFSession.close()
            IXDSession.close()

    def test_retorno_automatico_quando_prazo_vence(self):
        self._com_fc("CNF2")
        item_id = self._criar_em(
            "CNF2", nome_completo="Ciclana", login="ciclana1", cargo="PIT",
            area="OUTBOUND", turno="BLUE DAY", status="OPERACIONAL",
        )
        self.client.post(f"/api/hc/{item_id}/emprestimo-site", json={
            "destino_fc": "IXD_CNF2",
            "area_destino": "INBOUND",
            "ls_retorno_data": (date.today() + timedelta(days=3)).isoformat(),
        })

        # Simula o prazo já vencido, como o retorno automático veria depois.
        IXDSession = sessionmaker(bind=db.engines["IXD_CNF2"])()
        emprestado = IXDSession.query(HCGig2).filter_by(login="ciclana1").first()
        emprestado_id = emprestado.id
        emprestado.ls_retorno_data = date.today() - timedelta(days=1)
        emprestado.ls_retorno_em = None
        IXDSession.commit()
        IXDSession.close()

        # Qualquer carregamento normal do LIST em quem está com o registro
        # (agora IXD_CNF2) já dispara o retorno automático (_aplicar_regra_hc_atual).
        self._com_fc("IXD_CNF2")
        response = self.client.get("/api/hc")
        self.assertEqual(response.status_code, 200)

        CNFSession = sessionmaker(bind=db.engines["CNF2"])()
        IXDSession3 = sessionmaker(bind=db.engines["IXD_CNF2"])()
        try:
            self.assertIsNone(IXDSession3.get(HCGig2, emprestado_id))
            volta = CNFSession.query(HCGig2).filter_by(login="ciclana1").first()
            self.assertIsNotNone(volta)
            self.assertEqual(volta.status, "OPERACIONAL")
            self.assertEqual(volta.area, "OUTBOUND")
            self.assertEqual(volta.turno, "BLUE DAY")
            self.assertIsNone(volta.ls_site_origem)
        finally:
            CNFSession.close()
            IXDSession3.close()

    def test_retornar_agora_funciona_no_lado_do_emprestimo_cruzado(self):
        self._com_fc("CNF2")
        item_id = self._criar_em(
            "CNF2", nome_completo="Beltrano", login="beltrano1", cargo="Associado",
            area="OUTBOUND", turno="RED DAY", status="OPERACIONAL",
        )
        self.client.post(f"/api/hc/{item_id}/emprestimo-site", json={
            "destino_fc": "IXD_CNF2",
            "area_destino": "INBOUND",
            "ls_retorno_data": (date.today() + timedelta(days=10)).isoformat(),
        })

        IXDSession = sessionmaker(bind=db.engines["IXD_CNF2"])()
        emprestado = IXDSession.query(HCGig2).filter_by(login="beltrano1").first()
        emprestado_id = emprestado.id
        IXDSession.close()

        self._com_fc("IXD_CNF2")
        response = self.client.post(f"/api/hc/{emprestado_id}/retornar-ls")
        self.assertEqual(response.status_code, 200, response.get_json())

        CNFSession = sessionmaker(bind=db.engines["CNF2"])()
        IXDSession2 = sessionmaker(bind=db.engines["IXD_CNF2"])()
        try:
            self.assertIsNone(IXDSession2.get(HCGig2, emprestado_id))
            volta = CNFSession.query(HCGig2).filter_by(login="beltrano1").first()
            self.assertIsNotNone(volta)
            self.assertEqual(volta.status, "OPERACIONAL")
            self.assertEqual(volta.area, "OUTBOUND")
            self.assertEqual(volta.turno, "RED DAY")
        finally:
            CNFSession.close()
            IXDSession2.close()

    def test_edicao_generica_bloqueia_saida_de_emprestimo_cruzado(self):
        self._com_fc("CNF2")
        item_id = self._criar_em(
            "CNF2", nome_completo="Sicrano", login="sicrano1", cargo="Associado",
            area="OUTBOUND", turno="RED DAY", status="OPERACIONAL",
        )
        self.client.post(f"/api/hc/{item_id}/emprestimo-site", json={
            "destino_fc": "IXD_CNF2",
            "area_destino": "INBOUND",
            "ls_retorno_data": (date.today() + timedelta(days=10)).isoformat(),
        })
        IXDSession = sessionmaker(bind=db.engines["IXD_CNF2"])()
        emprestado_id = IXDSession.query(HCGig2).filter_by(login="sicrano1").first().id
        IXDSession.close()

        self._com_fc("IXD_CNF2")
        response = self.client.put(f"/api/hc/{emprestado_id}", json={
            "area": "INBOUND", "turno": "RED DAY", "status": "OPERACIONAL",
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn("Retornar agora", response.get_json()["erro"])

    def test_rejeita_emprestimo_sem_data_de_retorno(self):
        self._com_fc("CNF2")
        item_id = self._criar_em(
            "CNF2", nome_completo="Fulano2", login="fulano2", cargo="Associado",
            area="OUTBOUND", turno="RED DAY", status="OPERACIONAL",
        )
        response = self.client.post(f"/api/hc/{item_id}/emprestimo-site", json={
            "destino_fc": "IXD_CNF2", "area_destino": "INBOUND",
        })
        self.assertEqual(response.status_code, 400)

    def test_rejeita_reemprestimo_de_quem_ja_esta_em_ls(self):
        self._com_fc("CNF2")
        item_id = self._criar_em(
            "CNF2", nome_completo="Fulano3", login="fulano3", cargo="Associado",
            area="OUTBOUND", turno="RED DAY", status="LS",
        )
        response = self.client.post(f"/api/hc/{item_id}/emprestimo-site", json={
            "destino_fc": "IXD_CNF2", "area_destino": "INBOUND",
            "ls_retorno_data": (date.today() + timedelta(days=1)).isoformat(),
        })
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()

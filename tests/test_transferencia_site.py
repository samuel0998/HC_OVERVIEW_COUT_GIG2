import unittest
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask
from sqlalchemy.orm import sessionmaker

from models import db
from models.hc_gig2 import HCGig2
from models.registro_atividade import RegistroAtividade
from routes.hc import hc_bp


class TransferenciaSiteTest(unittest.TestCase):
    """Transferência DEFINITIVA de cadastro entre os bancos-irmãos CNF2 e
    IXD - CNF2 (ver routes.hc.transferir_colaborador_site)."""

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
        """Insere direto no engine de um FC especifico. Fora de uma request, o
        db.session default nao sabe rotear pro bind certo (isso so acontece via
        FCRoutingSession dentro de uma request com session['fc'] setado)."""
        sessao = sessionmaker(bind=db.engines[fc])()
        colaborador = HCGig2(**kwargs)
        sessao.add(colaborador)
        sessao.commit()
        item_id = colaborador.id
        sessao.close()
        return item_id

    def test_transfere_de_cnf2_para_ixd_cnf2_sem_setor_e_cria_pendencia(self):
        self._com_fc("CNF2")
        item_id = self._criar_em(
            "CNF2",
            nome_completo="Fulano de Tal",
            login="fdetal",
            cargo="Associado",
            area="OUTBOUND",
            turno="RED NIGHT",
            status="OPERACIONAL",
        )

        response = self.client.post(f"/api/hc/{item_id}/transferencia-site", json={"destino_fc": "IXD_CNF2"})
        self.assertEqual(response.status_code, 200, response.get_json())

        CNFSession = sessionmaker(bind=db.engines["CNF2"])()
        IXDSession = sessionmaker(bind=db.engines["IXD_CNF2"])()
        try:
            # Some do banco de origem (CNF2).
            self.assertIsNone(CNFSession.get(HCGig2, item_id))

            # E aparece no banco de destino (IXD_CNF2) sem setor, marcado como pendência.
            novo = IXDSession.query(HCGig2).filter_by(login="fdetal").first()
            self.assertIsNotNone(novo)
            self.assertIsNone(novo.area)
            self.assertEqual(novo.turno, "RED NIGHT")
            self.assertEqual(novo.pendente_transferencia_origem, "CNF2")

            registro_destino = IXDSession.query(RegistroAtividade).filter_by(tipo="transferencia_operacao").first()
            self.assertIsNotNone(registro_destino)

            # E fica registrado no histórico da origem também.
            registro_origem = CNFSession.query(RegistroAtividade).filter_by(tipo="transferencia_operacao").first()
            self.assertIsNotNone(registro_origem)
        finally:
            CNFSession.close()
            IXDSession.close()

    def test_rejeita_destino_fora_do_par_cnf2_ixd_cnf2(self):
        self._com_fc("CNF2")
        item_id = self._criar_em("CNF2", nome_completo="Beltrano", cargo="Associado", status="OPERACIONAL")

        response = self.client.post(f"/api/hc/{item_id}/transferencia-site", json={"destino_fc": "GIG2"})
        self.assertEqual(response.status_code, 400)

    def test_bloqueado_fora_de_cnf2_ixd_cnf2(self):
        self._com_fc("GIG2")
        response = self.client.post("/api/hc/1/transferencia-site", json={"destino_fc": "CNF2"})
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()

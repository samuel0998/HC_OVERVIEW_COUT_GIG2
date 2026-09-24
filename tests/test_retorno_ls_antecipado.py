import unittest
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask

from models import db
from models.hc_gig2 import HCGig2
from routes.hc import hc_bp


class RetornoLSAntecipadoTest(unittest.TestCase):
    """Botão "Retornar agora" no LIST: quem emprestou consegue puxar de volta um
    colaborador em LS antes do prazo agendado (ver routes.hc.retornar_ls_antecipado)."""

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
        user = patch("routes.hc.current_user", SimpleNamespace(
            can_edit=True, is_authenticated=True, login="tester", nome="Testador",
        ))
        user.start()
        self.addCleanup(user.stop)
        history = patch("routes.hc._registrar")
        history.start()
        self.addCleanup(history.stop)

    def _colaborador_em_ls(self):
        colaborador = HCGig2(
            nome_completo="Teste LS",
            cargo="Associado",
            area="OUTBOUND",
            turno="RED NIGHT",
            status="LS",
            ls_retorno_data=date.today() + timedelta(days=5),
            ls_area_origem="INBOUND",
            ls_turno_origem="BLUE DAY",
            ls_ticket_id=None,
        )
        db.session.add(colaborador)
        db.session.commit()
        return colaborador

    def test_retorna_para_area_e_turno_de_origem_antes_do_prazo(self):
        colaborador = self._colaborador_em_ls()

        response = self.client.post(f"/api/hc/{colaborador.id}/retornar-ls")
        self.assertEqual(response.status_code, 200, response.get_json())

        db.session.refresh(colaborador)
        self.assertEqual(colaborador.status, "OPERACIONAL")
        self.assertEqual(colaborador.area, "INBOUND")
        self.assertEqual(colaborador.turno, "BLUE DAY")
        self.assertIsNone(colaborador.ls_retorno_data)
        self.assertIsNone(colaborador.ls_area_origem)

    def test_rejeita_quem_nao_esta_em_ls(self):
        colaborador = HCGig2(nome_completo="Não em LS", cargo="Associado", status="OPERACIONAL")
        db.session.add(colaborador)
        db.session.commit()

        response = self.client.post(f"/api/hc/{colaborador.id}/retornar-ls")
        self.assertEqual(response.status_code, 400)

    def test_edicao_manual_para_operacional_tambem_restaura_origem(self):
        """Mesmo sem usar o botão dedicado, encerrar o LS pelo dropdown de status
        (deixando área/turno como veio pré-preenchido, que é o destino do LS) tem
        que devolver pra origem - não travar a pessoa no setor emprestado."""
        colaborador = self._colaborador_em_ls()

        response = self.client.put(f"/api/hc/{colaborador.id}", json={
            "area": colaborador.area,    # como o form reenvia o que já estava preenchido
            "turno": colaborador.turno,  # (destino do LS, não a origem)
            "status": "OPERACIONAL",
        })
        self.assertEqual(response.status_code, 200, response.get_json())

        db.session.refresh(colaborador)
        self.assertEqual(colaborador.status, "OPERACIONAL")
        self.assertEqual(colaborador.area, "INBOUND")
        self.assertEqual(colaborador.turno, "BLUE DAY")


if __name__ == "__main__":
    unittest.main()

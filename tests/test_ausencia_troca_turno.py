import unittest
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from flask import Flask

from models import db
from models.hc_gig2 import HCGig2
from models.registro_atividade import RegistroAtividade
from models.turno_config import HCTurnoConfig, ensure_default_turno_config
from routes.hc import hc_bp

SP = ZoneInfo("America/Sao_Paulo")


class AusenciaVoltaNaTrocaDeTurnoTest(unittest.TestCase):
    """Ausência volta pra OPERACIONAL na PRÓXIMA troca de turno (não precisa
    esperar o dia seguinte): quem é marcado ausente no Blue Day já volta no
    Blue Night (ver routes.hc._reset_chamada_por_virada_de_turno)."""

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
        HCTurnoConfig.__table__.create(db.engine)
        RegistroAtividade.__table__.create(db.engine)
        ensure_default_turno_config()
        db.session.commit()
        self.client = app.test_client()
        user = patch("routes.hc.current_user", SimpleNamespace(is_authenticated=True, login="t", nome="T"))
        user.start()
        self.addCleanup(user.stop)

    def _ausente(self, turno="BLUE DAY"):
        colaborador = HCGig2(
            nome_completo="Faltante Teste", cargo="Associado", area="OUTBOUND",
            turno=turno, status="Ausência", data_inicio_ausencia=date.today(),
        )
        db.session.add(colaborador)
        db.session.commit()
        return colaborador

    def _marcar_reset_ja_vencido(self, turno):
        """Configura o reset desse turno pra 2 minutos atrás e nunca processado
        hoje - fica "devido" na próxima checagem, sem depender de mockar relógio."""
        passado = (datetime.now(SP) - timedelta(minutes=2)).strftime("%H:%M")
        config = db.session.get(HCTurnoConfig, turno)
        config.hora_reset = passado
        config.last_reset_key = None
        db.session.commit()

    def test_ausencia_volta_operacional_na_troca_de_turno(self):
        colaborador = self._ausente("BLUE DAY")
        self._marcar_reset_ja_vencido("BLUE NIGHT")

        response = self.client.get("/api/hc")
        self.assertEqual(response.status_code, 200)

        db.session.refresh(colaborador)
        self.assertEqual(colaborador.status, "OPERACIONAL")
        self.assertIsNone(colaborador.data_inicio_ausencia)

        registro = RegistroAtividade.query.filter_by(operador_id=colaborador.id).first()
        self.assertIsNotNone(registro)
        self.assertIn("troca de turno", registro.descricao.lower())

    def test_ausencia_nao_mexe_antes_de_qualquer_virada_de_turno(self):
        colaborador = self._ausente("BLUE DAY")

        # Marca todos os resets como já processados hoje (com o hora_reset
        # atual de cada um), então nenhum fica "devido" - determinístico, sem
        # depender de que horas o teste realmente roda.
        hoje = datetime.now(SP).date().isoformat()
        for config in HCTurnoConfig.query.all():
            config.last_reset_key = f"{hoje}:{config.turno}:{config.hora_reset}"
        db.session.commit()

        self.client.get("/api/hc")
        db.session.refresh(colaborador)
        self.assertEqual(colaborador.status, "Ausência")

    def test_so_afeta_quem_esta_em_ausencia(self):
        operacional = HCGig2(nome_completo="Normal", cargo="Associado", turno="BLUE DAY", status="OPERACIONAL")
        db.session.add(operacional)
        db.session.commit()
        self._marcar_reset_ja_vencido("BLUE DAY")

        self.client.get("/api/hc")
        db.session.refresh(operacional)
        self.assertEqual(operacional.status, "OPERACIONAL")


if __name__ == "__main__":
    unittest.main()

import unittest
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from flask import Flask

from models import db
from models.hc_gig2 import HCGig2
from models.turno_config import HCTurnoConfig, ensure_default_turno_config
from routes.hc import _calcular_ls_retorno_em, hc_bp

SP = ZoneInfo("America/Sao_Paulo")
UTC = ZoneInfo("UTC")


class CalcularLSRetornoEmTest(unittest.TestCase):
    """Unidade: LS retorna no PRÓXIMO horário de virada do turno de origem
    (Configuração de Shifts em /usuarios), não 24h corridas nem meia-noite
    fixa. Ex. do pedido: sxmoraes é RED DAY (reseta 20:00) - emprestado hoje
    antes das 20:00, volta hoje às 20:00; emprestado depois das 20:00, só
    volta amanhã às 20:00 ("próximo turno")."""

    def setUp(self):
        app = Flask(__name__)
        app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
        db.init_app(app)
        self.context = app.app_context()
        self.context.push()
        self.addCleanup(self.context.pop)
        self.addCleanup(db.session.remove)
        HCTurnoConfig.__table__.create(db.engine)
        ensure_default_turno_config()
        db.session.commit()

    def test_emprestado_hoje_antes_do_reset_volta_hoje_no_reset(self):
        # RED DAY reseta 20:00 por padrão (ver DEFAULT_TURNO_RESET).
        agora_sp = datetime(2026, 9, 29, 14, 0, tzinfo=SP)  # 14h, antes das 20h
        resultado = _calcular_ls_retorno_em(date(2026, 9, 29), "RED DAY", agora_sp=agora_sp)
        esperado = datetime(2026, 9, 29, 20, 0, tzinfo=SP).astimezone(UTC).replace(tzinfo=None)
        self.assertEqual(resultado, esperado)

    def test_emprestado_hoje_depois_do_reset_volta_amanha_no_proximo_turno(self):
        agora_sp = datetime(2026, 9, 29, 21, 30, tzinfo=SP)  # já passou das 20h
        resultado = _calcular_ls_retorno_em(date(2026, 9, 29), "RED DAY", agora_sp=agora_sp)
        esperado = datetime(2026, 9, 30, 20, 0, tzinfo=SP).astimezone(UTC).replace(tzinfo=None)
        self.assertEqual(resultado, esperado)

    def test_data_futura_cai_no_reset_daquele_dia(self):
        agora_sp = datetime(2026, 9, 29, 10, 0, tzinfo=SP)
        resultado = _calcular_ls_retorno_em(date(2026, 10, 5), "RED NIGHT", agora_sp=agora_sp)
        esperado = datetime(2026, 10, 5, 8, 0, tzinfo=SP).astimezone(UTC).replace(tzinfo=None)  # RED NIGHT reseta 08:00
        self.assertEqual(resultado, esperado)

    def test_turno_desconhecido_cai_na_meia_noite(self):
        agora_sp = datetime(2026, 9, 29, 10, 0, tzinfo=SP)
        resultado = _calcular_ls_retorno_em(date(2026, 9, 29), "TURNO-QUE-NAO-EXISTE", agora_sp=agora_sp)
        esperado = datetime(2026, 9, 30, 0, 0, tzinfo=SP).astimezone(UTC).replace(tzinfo=None)
        self.assertEqual(resultado, esperado)

    def test_respeita_horario_customizado_pelo_admin(self):
        config = db.session.get(HCTurnoConfig, "BLUE DAY")
        config.hora_reset = "19:30"
        db.session.commit()

        agora_sp = datetime(2026, 9, 29, 10, 0, tzinfo=SP)
        resultado = _calcular_ls_retorno_em(date(2026, 9, 29), "BLUE DAY", agora_sp=agora_sp)
        esperado = datetime(2026, 9, 29, 19, 30, tzinfo=SP).astimezone(UTC).replace(tzinfo=None)
        self.assertEqual(resultado, esperado)


class LSRetornoIntegradoTest(unittest.TestCase):
    """O fluxo completo de abrir um LS usa o retorno baseado em shift."""

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
        ensure_default_turno_config()
        db.session.commit()
        self.client = app.test_client()
        user = patch("routes.hc.current_user", SimpleNamespace(is_authenticated=True, login="t", nome="T"))
        user.start()
        self.addCleanup(user.stop)
        history = patch("routes.hc._registrar")
        history.start()
        self.addCleanup(history.stop)

    def test_ls_aberto_hoje_agenda_retorno_no_reset_do_turno_de_origem(self):
        colaborador = HCGig2(
            nome_completo="Sxmoraes Teste", cargo="Analista", area="OUTBOUND",
            turno="RED DAY", status="OPERACIONAL",
        )
        db.session.add(colaborador)
        db.session.commit()

        response = self.client.put(f"/api/hc/{colaborador.id}", json={
            "status": "LS",
            "ls_area_destino": "INBOUND",
            "ls_retorno_data": date.today().isoformat(),
        })
        self.assertEqual(response.status_code, 200, response.get_json())

        db.session.refresh(colaborador)
        config = db.session.get(HCTurnoConfig, "RED DAY")
        hora, minuto = [int(p) for p in config.hora_reset.split(":")]
        esperado_hoje = datetime.combine(date.today(), datetime.min.time(), tzinfo=SP).replace(hour=hora, minute=minuto)
        esperado_amanha = esperado_hoje + timedelta(days=1)
        # Dependendo de que horas o teste roda, o retorno é hoje ou amanhã no
        # reset - nunca "agora + 24h corridas" nem meia-noite.
        self.assertIn(
            colaborador.ls_retorno_em,
            (esperado_hoje.astimezone(UTC).replace(tzinfo=None), esperado_amanha.astimezone(UTC).replace(tzinfo=None)),
        )
        # E cai exatamente no minuto do reset (segundos/microssegundos zerados).
        self.assertEqual(colaborador.ls_retorno_em.second, 0)
        self.assertEqual(colaborador.ls_retorno_em.microsecond, 0)


if __name__ == "__main__":
    unittest.main()

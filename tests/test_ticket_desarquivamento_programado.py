import unittest
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from flask import Flask

from models import db
from models.hc_gig2 import HCGig2
from models.registro_atividade import RegistroAtividade
from models.ticket import Ticket
from routes.hc import hc_bp

SP = ZoneInfo("America/Sao_Paulo")


class DesarquivamentoProgramadoTest(unittest.TestCase):
    """Planning programa dia/hora pro ticket voltar sozinho a ficar ativo pro
    shift, sem precisar desarquivar manualmente (ver
    routes.hc.programar_desarquivamento_ticket / _processar_desarquivamentos_programados)."""

    def setUp(self):
        app = Flask(__name__)
        app.config.update(TESTING=True, LOGIN_DISABLED=True, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
        db.init_app(app)
        app.register_blueprint(hc_bp)
        self.context = app.app_context()
        self.context.push()
        self.addCleanup(self.context.pop)
        self.addCleanup(db.session.remove)
        Ticket.__table__.create(db.engine)
        RegistroAtividade.__table__.create(db.engine)
        HCGig2.__table__.create(db.engine)
        self.client = app.test_client()
        self.planning = SimpleNamespace(
            is_authenticated=True, login="planner1", nome="Planner", can_edit=True,
            is_admin=True, is_hard_expert=True,
        )
        self.user = patch("routes.hc.current_user", self.planning)
        self.user.start()
        self.addCleanup(self.user.stop)

    def _criar_ticket_arquivado(self, premise_id=7001, **extra):
        campos = dict(
            premise_id=premise_id,
            premise_type="LS",
            premise_name="Labor Share (LS)",
            setor="OUTBOUND",
            cargo="Associado",
            _amount=1,
            work_date=date.today(),
            source_responsible_login="shiftlead1",
            created_at=datetime.utcnow() - timedelta(days=1),
            hcview_arquivado=True,
            hcview_arquivado_por="planner1",
            hcview_arquivado_em=datetime.utcnow() - timedelta(hours=1),
        )
        campos.update(extra)
        ticket = Ticket(**campos)
        db.session.add(ticket)
        db.session.commit()
        return ticket

    def test_programa_desarquivamento_futuro(self):
        ticket = self._criar_ticket_arquivado()
        em_sp = datetime.now(SP) + timedelta(hours=3)
        response = self.client.post(f"/api/hc/tickets/{ticket.premise_id}/programar-desarquivamento", json={
            "em": em_sp.strftime("%Y-%m-%dT%H:%M"),
        })
        self.assertEqual(response.status_code, 200, response.get_json())

        db.session.refresh(ticket)
        self.assertIsNotNone(ticket.hcview_desarquivar_em)
        self.assertEqual(ticket.hcview_desarquivar_agendado_por, "planner1")
        # Grava em UTC; reconvertendo pra SP bate com o horário pedido (minuto a minuto).
        de_volta_sp = ticket.hcview_desarquivar_em.replace(tzinfo=ZoneInfo("UTC")).astimezone(SP)
        self.assertEqual(de_volta_sp.strftime("%Y-%m-%d %H:%M"), em_sp.strftime("%Y-%m-%d %H:%M"))

    def test_rejeita_data_no_passado(self):
        ticket = self._criar_ticket_arquivado()
        passado = (datetime.now(SP) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
        response = self.client.post(f"/api/hc/tickets/{ticket.premise_id}/programar-desarquivamento", json={"em": passado})
        self.assertEqual(response.status_code, 400)

    def test_rejeita_quando_ticket_nao_esta_arquivado(self):
        ticket = self._criar_ticket_arquivado(premise_id=7002, hcview_arquivado=False, hcview_arquivado_por=None, hcview_arquivado_em=None)
        futuro = (datetime.now(SP) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
        response = self.client.post(f"/api/hc/tickets/{ticket.premise_id}/programar-desarquivamento", json={"em": futuro})
        self.assertEqual(response.status_code, 400)

    def test_exige_hard_expert(self):
        with patch("routes.hc.current_user", SimpleNamespace(
            is_authenticated=True, login="x", nome="X", can_edit=True, is_admin=False, is_hard_expert=False,
        )):
            ticket = self._criar_ticket_arquivado(premise_id=7003)
            futuro = (datetime.now(SP) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
            response = self.client.post(f"/api/hc/tickets/{ticket.premise_id}/programar-desarquivamento", json={"em": futuro})
        self.assertEqual(response.status_code, 403)

    def test_cancelar_agendamento(self):
        ticket = self._criar_ticket_arquivado(
            premise_id=7004,
            hcview_desarquivar_em=datetime.utcnow() + timedelta(hours=2),
            hcview_desarquivar_agendado_por="planner1",
        )
        response = self.client.post(f"/api/hc/tickets/{ticket.premise_id}/programar-desarquivamento", json={"em": ""})
        self.assertEqual(response.status_code, 200)
        db.session.refresh(ticket)
        self.assertIsNone(ticket.hcview_desarquivar_em)
        self.assertIsNone(ticket.hcview_desarquivar_agendado_por)

    def test_auto_desarquiva_quando_horario_chega(self):
        ticket = self._criar_ticket_arquivado(
            premise_id=7005,
            hcview_desarquivar_em=datetime.utcnow() - timedelta(minutes=1),
            hcview_desarquivar_agendado_por="planner1",
        )
        response = self.client.get("/api/hc/tickets-pendentes?arquivados=1")
        self.assertEqual(response.status_code, 200)

        db.session.refresh(ticket)
        self.assertFalse(ticket.hcview_arquivado)
        self.assertIsNone(ticket.hcview_arquivado_por)
        self.assertIsNone(ticket.hcview_desarquivar_em)
        self.assertIsNone(ticket.hcview_desarquivar_agendado_por)

        # E já aparece na listagem de tickets ativos (não arquivados).
        ativos = self.client.get("/api/hc/tickets-pendentes").get_json()
        ids_ativos = [t["premise_id"] for t in ativos["tickets"]]
        self.assertIn(ticket.premise_id, ids_ativos)

    def test_nao_desarquiva_antes_do_horario(self):
        ticket = self._criar_ticket_arquivado(
            premise_id=7006,
            hcview_desarquivar_em=datetime.utcnow() + timedelta(hours=5),
            hcview_desarquivar_agendado_por="planner1",
        )
        self.client.get("/api/hc/tickets-pendentes?arquivados=1")
        db.session.refresh(ticket)
        self.assertTrue(ticket.hcview_arquivado)
        self.assertIsNotNone(ticket.hcview_desarquivar_em)

    def test_arquivar_de_novo_limpa_agendamento_antigo(self):
        ticket = self._criar_ticket_arquivado(
            premise_id=7007,
            hcview_arquivado=False, hcview_arquivado_por=None, hcview_arquivado_em=None,
            hcview_desarquivar_em=datetime.utcnow() + timedelta(hours=5),
            hcview_desarquivar_agendado_por="planner1",
        )
        response = self.client.post(f"/api/hc/tickets/{ticket.premise_id}/arquivar", json={"arquivar": True})
        self.assertEqual(response.status_code, 200)
        db.session.refresh(ticket)
        self.assertTrue(ticket.hcview_arquivado)
        self.assertIsNone(ticket.hcview_desarquivar_em)
        self.assertIsNone(ticket.hcview_desarquivar_agendado_por)


if __name__ == "__main__":
    unittest.main()

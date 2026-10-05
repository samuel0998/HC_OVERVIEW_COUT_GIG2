import json
import unittest
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask

from models import db
from models.registro_atividade import RegistroAtividade
from models.ticket import Ticket
from routes.hc import hc_bp


class TicketLSSemEndDateTest(unittest.TestCase):
    """Ticket de LS sem data de retorno pré-definida (comum: quem resolve é quem
    decide/define o retorno no cadastro, não o ticket) precisa validar/resolver
    normalmente - antes bloqueava sempre (ver _concluir_ticket_se_validado /
    resolver_ticket)."""

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
        self.client = app.test_client()
        self.user = patch("routes.hc.current_user", SimpleNamespace(
            is_authenticated=True, login="shiftlead1", nome="Shift Lead", can_edit=True, is_admin=False,
        ))
        self.user.start()
        self.addCleanup(self.user.stop)

    def _criar_ticket_ls(self, premise_id=5001, end_date=None, work_date=None):
        ticket = Ticket(
            premise_id=premise_id,
            premise_type="LS",
            premise_name="Labor Share (LS)",
            setor="OUTBOUND",
            escala="RED",
            turno="Day",
            setor_origem="INBOUND",
            escala_origem="RED",
            turno_origem="Day",
            cargo="Associado",
            _amount=1,
            work_date=work_date or date.today(),
            end_date=end_date,
            source_responsible_login="shiftlead1",
            created_at=datetime.utcnow() - timedelta(minutes=10),
        )
        db.session.add(ticket)
        db.session.commit()
        return ticket

    def _registrar_acao_ls(self, ls_retorno_data):
        """Simula a edição que o shift fez no LIST: tirou o AA de INBOUND/RED DAY
        e colocou em OUTBOUND/RED DAY, status LS, com uma data de retorno
        ESCOLHIDA PELO PRÓPRIO USUÁRIO (o ticket não tem end_date)."""
        antes = {"cargo": "Associado", "area": "INBOUND", "turno": "RED DAY", "status": "OPERACIONAL"}
        depois = {
            "cargo": "Associado", "area": "OUTBOUND", "turno": "RED DAY", "status": "LS",
            "ls_retorno_data": ls_retorno_data.isoformat(), "ls_area_origem": "INBOUND", "ls_turno_origem": "RED DAY",
        }
        registro = RegistroAtividade(
            tipo="edicao_status",
            operador_id=1,
            operador_login="colaborador1",
            operador_nome="Colaborador Teste",
            usuario_login="shiftlead1",
            usuario_nome="Shift Lead",
            descricao="Colaborador atualizado (status: OPERACIONAL → LS)",
            dados_anteriores=json.dumps(antes),
            dados_novos=json.dumps(depois),
            timestamp=datetime.utcnow(),
        )
        db.session.add(registro)
        db.session.commit()
        return registro

    def test_resolve_ls_sem_end_date_usando_retorno_escolhido_pelo_usuario(self):
        ticket = self._criar_ticket_ls(end_date=None)
        self._registrar_acao_ls(ls_retorno_data=date.today() + timedelta(days=7))

        response = self.client.post(f"/api/hc/tickets/{ticket.premise_id}/resolver")
        self.assertEqual(response.status_code, 200, response.get_json())

        db.session.refresh(ticket)
        self.assertTrue(ticket.hcview_resolvido)

    def test_ainda_rejeita_end_date_anterior_a_data_solicitada(self):
        # Esse caso continua inválido: o ticket PEDIU uma data de retorno, e ela
        # é incoerente (antes da própria data da solicitação).
        hoje = date.today()
        ticket = self._criar_ticket_ls(end_date=hoje - timedelta(days=1), work_date=hoje)
        self._registrar_acao_ls(ls_retorno_data=hoje + timedelta(days=7))

        response = self.client.post(f"/api/hc/tickets/{ticket.premise_id}/resolver")
        self.assertEqual(response.status_code, 422)

        db.session.refresh(ticket)
        self.assertFalse(ticket.hcview_resolvido)

    def test_sem_acao_correspondente_continua_pendente(self):
        ticket = self._criar_ticket_ls(end_date=None)
        # Nenhuma ação registrada ainda.
        response = self.client.post(f"/api/hc/tickets/{ticket.premise_id}/resolver")
        self.assertEqual(response.status_code, 409)
        db.session.refresh(ticket)
        self.assertFalse(ticket.hcview_resolvido)


if __name__ == "__main__":
    unittest.main()

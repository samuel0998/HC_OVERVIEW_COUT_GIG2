import unittest
from datetime import date, timedelta

from flask import Flask

from models import db
from models.hc_gig2 import HCGig2
from models.registro_atividade import RegistroAtividade
from routes.hc import _aplicar_regra_hc_atual, hc_bp


class HistoricoAutomaticoTest(unittest.TestCase):
    """As viradas automáticas de status (Ausência, Licença/Férias, Treinamento,
    agendamentos) precisam ficar no histórico mesmo quando disparadas pelo uso
    normal do app (_aplicar_regra_hc_atual, chamada a cada carregamento do
    LIST/Pendências) - não só quando o boot roda processar_status_automatico
    (app.py), que na prática raramente acontece em produção."""

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

    def test_retorno_automatico_de_ausencia_fica_no_historico(self):
        colaborador = HCGig2(
            nome_completo="Teste Ausência",
            cargo="Associado",
            area="OUTBOUND",
            turno="RED NIGHT",
            status="Ausência",
            data_inicio_ausencia=date(2026, 9, 20),
        )
        db.session.add(colaborador)
        db.session.commit()

        alterou = _aplicar_regra_hc_atual([colaborador], hoje=date(2026, 9, 21))
        self.assertTrue(alterou)
        self.assertEqual(colaborador.status, "OPERACIONAL")

        registro = RegistroAtividade.query.filter_by(tipo="edicao_status").first()
        self.assertIsNotNone(registro)
        self.assertIn("ausência", registro.descricao.lower())
        self.assertEqual(registro.usuario_login, "sistema")

    def test_retorno_automatico_de_licenca_fica_no_historico(self):
        colaborador = HCGig2(
            nome_completo="Teste Licença",
            cargo="Associado",
            status="Licença",
            data_inicio_licenca=date(2026, 9, 1),
            data_fim_licenca=date(2026, 9, 20),
        )
        db.session.add(colaborador)
        db.session.commit()

        _aplicar_regra_hc_atual([colaborador], hoje=date(2026, 9, 21))
        self.assertEqual(colaborador.status, "OPERACIONAL")

        registro = RegistroAtividade.query.filter_by(tipo="edicao_status").first()
        self.assertIsNotNone(registro)
        self.assertIn("licença", registro.descricao.lower())


if __name__ == "__main__":
    unittest.main()

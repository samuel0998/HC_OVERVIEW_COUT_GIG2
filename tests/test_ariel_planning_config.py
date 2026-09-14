import importlib
import os
import unittest
from unittest.mock import patch

from flask import Flask, session

from models import db
from models.ticket import Ticket

class ArielPlanningConfigTest(unittest.TestCase):
    def test_adiciona_bind_quando_url_do_ariel_eh_configurada(self):
        with patch.dict(os.environ, {
            "ARIEL_PLANNING_DATABASE_URL": "postgres://usuario:senha@ariel.internal:5432/railway",
        }, clear=False):
            import config
            config = importlib.reload(config)
            self.assertEqual(
                config.Config.SQLALCHEMY_BINDS["ARIEL_PLANNING"],
                "postgresql://usuario:senha@ariel.internal:5432/railway",
            )

    def test_nao_adiciona_bind_com_valor_invalido(self):
        with patch.dict(os.environ, {"ARIEL_PLANNING_DATABASE_URL": "valor-invalido"}, clear=False):
            import config
            config = importlib.reload(config)
            self.assertNotIn("ARIEL_PLANNING", config.Config.SQLALCHEMY_BINDS)

    def test_ticket_do_gig2_usa_o_bind_do_ariel(self):
        app = Flask(__name__)
        app.config.update(
            SECRET_KEY="teste",
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            SQLALCHEMY_BINDS={"ARIEL_PLANNING": "sqlite:///:memory:"},
        )
        db.init_app(app)
        with app.test_request_context("/"):
            session["fc"] = "GIG2"
            Ticket.__table__.create(db.engines["ARIEL_PLANNING"])
            db.session.add(Ticket(premise_id=9001, premise_type="ON"))
            db.session.commit()
            self.assertIsNotNone(Ticket.query.get(9001))
            with self.assertRaises(Exception):
                db.session.execute(Ticket.__table__.select(), bind_arguments={"bind": db.engine}).all()
            db.session.remove()

    def test_ticket_nao_consulta_coluna_ausente_no_ariel(self):
        self.assertNotIn("associado_id", Ticket.__table__.columns)


if __name__ == "__main__":
    unittest.main()

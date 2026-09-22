import unittest
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask

from models import db
from models.hc_gig2 import HCGig2
from routes.hc import CARGOS, CARGOS_CADASTRO, _formatar_cargo, hc_bp


class PITTraineeCargoTest(unittest.TestCase):
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
        user = patch("routes.hc.current_user", SimpleNamespace(can_add_colaborador=True))
        user.start()
        self.addCleanup(user.stop)
        history = patch("routes.hc._registrar")
        history.start()
        self.addCleanup(history.stop)

    def test_pit_trainee_e_selecionavel_no_cadastro_mas_nao_no_filtro(self):
        self.assertIn("PIT Trainee", CARGOS_CADASTRO)
        self.assertNotIn("PIT Trainee", CARGOS)

    def test_formatar_cargo_normaliza_pit_trainee_para_pit(self):
        for variante in ("PIT Trainee", "pit trainee", "  PIT TRAINEE  "):
            with self.subTest(variante=variante):
                self.assertEqual(_formatar_cargo(variante), "PIT")

    def test_cadastro_com_pit_trainee_grava_cargo_pit(self):
        response = self.client.post("/api/hc", json={
            "nome_completo": "Novo PIT Trainee",
            "cargo": "PIT Trainee",
            "area": "INBOUND",
            "turno": "BLUE DAY",
        })
        self.assertEqual(response.status_code, 201)
        item = response.get_json()["item"]
        self.assertEqual(item["cargo"], "PIT")
        self.assertEqual(item["status"], "Treinamento")


if __name__ == "__main__":
    unittest.main()

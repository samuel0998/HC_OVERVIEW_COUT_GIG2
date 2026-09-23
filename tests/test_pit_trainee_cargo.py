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
        # No banco/para outras ferramentas (tickets, capacidade) o cargo é "PIT" puro.
        self.assertEqual(item["cargo"], "PIT")
        self.assertEqual(item["status"], "Treinamento")
        # No front (LIST/Dashboard) precisa aparecer como "PIT Trainee".
        self.assertTrue(item["pit_trainee"])
        self.assertEqual(item["cargo_exibicao"], "PIT Trainee")

    def test_edicao_alterna_rotulo_pit_trainee_sem_mudar_cargo_gravado(self):
        response = self.client.post("/api/hc", json={
            "nome_completo": "Colaborador PIT",
            "cargo": "PIT",
            "area": "INBOUND",
            "turno": "BLUE DAY",
        })
        item_id = response.get_json()["item"]["id"]
        colaborador = db.session.get(HCGig2, item_id)
        self.assertFalse(colaborador.pit_trainee)
        self.assertEqual(colaborador.cargo_exibicao(), "PIT")

        # Marca como PIT Trainee na edição.
        resp = self.client.put(f"/api/hc/{item_id}", json={
            "cargo": "PIT Trainee", "area": "INBOUND", "turno": "BLUE DAY", "status": "OPERACIONAL",
        })
        self.assertEqual(resp.status_code, 200)
        item = resp.get_json()["item"]
        self.assertEqual(item["cargo"], "PIT")
        self.assertTrue(item["pit_trainee"])
        self.assertEqual(item["cargo_exibicao"], "PIT Trainee")

        # "Graduação": volta pra PIT puro numa edição seguinte.
        resp2 = self.client.put(f"/api/hc/{item_id}", json={
            "cargo": "PIT", "area": "INBOUND", "turno": "BLUE DAY", "status": "OPERACIONAL",
        })
        item2 = resp2.get_json()["item"]
        self.assertFalse(item2["pit_trainee"])
        self.assertEqual(item2["cargo_exibicao"], "PIT")


if __name__ == "__main__":
    unittest.main()

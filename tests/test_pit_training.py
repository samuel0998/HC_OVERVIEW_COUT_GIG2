import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask

from models import db
from models.hc_gig2 import HCGig2
from routes.hc import hc_bp


class PITTrainingTest(unittest.TestCase):
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

    def test_cadastro_e_fim_do_treinamento_preservam_turno(self):
        for turno in ("BLUE DAY", "BLUE NIGHT", "RED DAY", "RED NIGHT", "ADM"):
            with self.subTest(turno=turno):
                response = self.client.post("/api/hc", json={
                    "nome_completo": "Teste PIT",
                    "cargo": "PIT",
                    "area": "INBOUND",
                    "turno": turno,
                })
                self.assertEqual(response.status_code, 201)
                item = response.get_json()["item"]
                self.assertEqual(item["status"], "Treinamento")
                self.assertEqual(item["turno"], turno)

                colaborador = db.session.get(HCGig2, item["id"])
                cadastro = colaborador.created_at.date()
                colaborador.aplicar_status_por_data(hoje=cadastro + timedelta(days=4))
                self.assertEqual(colaborador.status, "Treinamento")
                self.assertEqual(colaborador.turno, turno)
                colaborador.aplicar_status_por_data(hoje=cadastro + timedelta(days=5))
                self.assertEqual(colaborador.status, "OPERACIONAL")
                self.assertEqual(colaborador.turno, turno)

    def test_edicao_permite_realocar_pit_legado_durante_treinamento(self):
        colaborador = HCGig2(
            nome_completo="Teste PIT legado",
            cargo="PIT",
            area="INBOUND",
            turno="ADM",
            status="Treinamento",
            created_at=datetime.utcnow(),
        )
        db.session.add(colaborador)
        db.session.commit()

        response = self.client.put(f"/api/hc/{colaborador.id}", json={
            "area": "INBOUND",
            "turno": "RED NIGHT",
            "status": "Treinamento",
        })
        self.assertEqual(response.status_code, 200)
        db.session.refresh(colaborador)
        self.assertEqual(colaborador.status, "Treinamento")
        self.assertEqual(colaborador.turno, "RED NIGHT")

    def test_edicao_move_associado_antigo_de_operacional_para_treinamento(self):
        """Bug relatado: editar um AA/Associado já operacional (cadastrado há
        muito mais de 2 dias) pra Treinamento não pegava - a rotina automática
        (aplicar_status_por_data, chamada no fim do PUT) via os dias contados
        desde created_at e revertia pra OPERACIONAL na mesma edição."""
        colaborador = HCGig2(
            nome_completo="Teste AA antigo",
            cargo="Associado",
            area="OUTBOUND",
            turno="RED NIGHT",
            status="OPERACIONAL",
            created_at=datetime.utcnow() - timedelta(days=120),
        )
        db.session.add(colaborador)
        db.session.commit()

        response = self.client.put(f"/api/hc/{colaborador.id}", json={
            "area": "OUTBOUND",
            "turno": "RED NIGHT",
            "status": "Treinamento",
        })
        self.assertEqual(response.status_code, 200)
        db.session.refresh(colaborador)
        self.assertEqual(colaborador.status, "Treinamento")
        self.assertIsNotNone(colaborador.treinamento_inicio_em)

        # E continua em Treinamento até completar os dias a partir do REINÍCIO
        # (não do cadastro original, que já teria estourado o prazo há muito).
        colaborador.aplicar_status_por_data(hoje=colaborador.treinamento_inicio_em + timedelta(days=1))
        self.assertEqual(colaborador.status, "Treinamento")
        colaborador.aplicar_status_por_data(hoje=colaborador.treinamento_inicio_em + timedelta(days=2))
        self.assertEqual(colaborador.status, "OPERACIONAL")


if __name__ == "__main__":
    unittest.main()

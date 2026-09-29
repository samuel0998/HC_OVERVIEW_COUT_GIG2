import unittest
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask

from models import db
from models.hc_gig2 import HCGig2
from models.registro_atividade import RegistroAtividade
from routes.hc import hc_bp


class PromocaoHistoricoTest(unittest.TestCase):
    """Troca de cargo (ex.: Associado -> PIT, Associado -> PIT Trainee) vira um
    tipo de atividade próprio ("promocao"), filtrável no Histórico (ver
    routes.hc.atualizar_colaborador / TIPO_ATIVIDADE_LABELS)."""

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
        self.client = app.test_client()
        user = patch("routes.hc.current_user", SimpleNamespace(
            is_authenticated=True, login="tester", nome="Testador",
        ))
        user.start()
        self.addCleanup(user.stop)

    def _colaborador(self, **kwargs):
        colaborador = HCGig2(**kwargs)
        db.session.add(colaborador)
        db.session.commit()
        return colaborador

    def test_promocao_para_pit_e_registrada_com_tipo_promocao(self):
        colaborador = self._colaborador(
            nome_completo="Fulano", cargo="Associado", area="OUTBOUND",
            turno="RED NIGHT", status="OPERACIONAL",
        )
        response = self.client.put(f"/api/hc/{colaborador.id}", json={
            "cargo": "PIT", "area": "OUTBOUND", "turno": "RED NIGHT", "status": "OPERACIONAL",
        })
        self.assertEqual(response.status_code, 200)

        registro = RegistroAtividade.query.filter_by(operador_id=colaborador.id).first()
        self.assertEqual(registro.tipo, "promocao")
        self.assertIn("cargo: Associado → PIT", registro.descricao)

    def test_promocao_para_pit_trainee_distingue_do_pit_puro_no_historico(self):
        colaborador = self._colaborador(
            nome_completo="Ciclana", cargo="Associado", area="OUTBOUND",
            turno="RED NIGHT", status="OPERACIONAL",
        )
        response = self.client.put(f"/api/hc/{colaborador.id}", json={
            "cargo": "PIT Trainee", "area": "OUTBOUND", "turno": "RED NIGHT", "status": "OPERACIONAL",
        })
        self.assertEqual(response.status_code, 200)
        # No banco o cargo grava como PIT puro (conta capacidade normal).
        db.session.refresh(colaborador)
        self.assertEqual(colaborador.cargo, "PIT")
        self.assertTrue(colaborador.pit_trainee)

        registro = RegistroAtividade.query.filter_by(operador_id=colaborador.id).first()
        self.assertEqual(registro.tipo, "promocao")
        self.assertIn("cargo: Associado → PIT Trainee", registro.descricao)

        alteracoes = registro.to_dict()["alteracoes"]
        cargo_alteracao = next(a for a in alteracoes if a["campo"] == "Cargo")
        self.assertEqual(cargo_alteracao["de"], "Associado")
        self.assertEqual(cargo_alteracao["para"], "PIT Trainee")

    def test_edicao_sem_trocar_cargo_nao_vira_promocao(self):
        colaborador = self._colaborador(
            nome_completo="Beltrano", cargo="PIT", area="OUTBOUND",
            turno="RED NIGHT", status="OPERACIONAL",
        )
        response = self.client.put(f"/api/hc/{colaborador.id}", json={
            "cargo": "PIT", "area": "INBOUND", "turno": "RED NIGHT", "status": "OPERACIONAL",
        })
        self.assertEqual(response.status_code, 200)
        registro = RegistroAtividade.query.filter_by(operador_id=colaborador.id).first()
        self.assertNotEqual(registro.tipo, "promocao")

    def test_filtro_de_historico_por_tipo_promocao(self):
        colaborador = self._colaborador(nome_completo="Sicrano", cargo="Associado", status="OPERACIONAL")
        self.client.put(f"/api/hc/{colaborador.id}", json={"cargo": "Analista", "status": "OPERACIONAL"})
        outro = self._colaborador(nome_completo="Outro", cargo="PIT", status="OPERACIONAL")
        self.client.put(f"/api/hc/{outro.id}", json={"cargo": "PIT", "area": "INBOUND", "status": "OPERACIONAL"})

        resposta = self.client.get("/api/hc/historico?tipo=promocao").get_json()
        self.assertEqual(len(resposta), 1)
        self.assertEqual(resposta[0]["operador_nome"], "Sicrano")


if __name__ == "__main__":
    unittest.main()

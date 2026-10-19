"""Aba Tree: visualização em árvore (setor -> colaboradores) com drag-and-drop,
pedida como equivalente ao board do LaborDash, só que usando o HC já cadastrado
na própria HC Overview. O "mover" reaproveita o PUT /api/hc/<id> já existente
(routes.hc.atualizar_colaborador) - não há endpoint de mutação novo, só a tela
e o endpoint de leitura /api/hc/tree que agrupa por área/turno."""
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask

from models import db
from models.hc_gig2 import HCGig2
from models.registro_atividade import RegistroAtividade
from routes.auth import auth_bp
from routes.hc import hc_bp

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"


class TreeTestBase(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__, template_folder=str(TEMPLATE_DIR))
        app.config.update(TESTING=True, LOGIN_DISABLED=True, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
        db.init_app(app)
        app.register_blueprint(hc_bp)
        # base.html referencia url_for('auth.logout') / 'auth.usuarios_page' -
        # só precisa existir no url map, nenhuma dessas rotas é chamada aqui.
        app.register_blueprint(auth_bp)

        @app.context_processor
        def _inject_fc_context():
            # Réplica mínima do context_processor real (ver app.py) - só o
            # suficiente pra base.html renderizar sem erro neste app de teste.
            # current_user é lido dinamicamente de routes.hc (onde self._como()
            # faz o patch) - em produção isso vem do próprio flask_login.
            import routes.hc as hc_module
            return {
                "active_fc_logo": "lion_logo.png", "active_fc_label": "GIG2", "active_fc": "GIG2",
                "current_user": hc_module.current_user,
            }

        self.context = app.app_context()
        self.context.push()
        self.addCleanup(self.context.pop)
        self.addCleanup(db.session.remove)
        HCGig2.__table__.create(db.engine)
        RegistroAtividade.__table__.create(db.engine)
        self.client = app.test_client()

    def _como(self, can_dashboard=True, can_edit=True):
        return patch("routes.hc.current_user", SimpleNamespace(
            is_authenticated=True, login="tester", nome="Testador",
            can_dashboard=can_dashboard, can_edit=can_edit,
        ))

    def _colaborador(self, **kwargs):
        kwargs.setdefault("status", "OPERACIONAL")
        colaborador = HCGig2(**kwargs)
        db.session.add(colaborador)
        db.session.commit()
        return colaborador


class TreePaginaTest(TreeTestBase):
    def test_pagina_tree_acessivel_pra_quem_tem_dashboard(self):
        with self._como():
            resposta = self.client.get("/tree")
        self.assertEqual(resposta.status_code, 200)

    def test_pagina_tree_bloqueada_sem_permissao_de_dashboard(self):
        with self._como(can_dashboard=False):
            resposta = self.client.get("/tree")
        self.assertEqual(resposta.status_code, 403)


class TreeDadosTest(TreeTestBase):
    def test_agrupa_por_area_e_so_traz_quem_esta_na_operacao(self):
        self._colaborador(nome_completo="Op1", cargo="Associado", area="INBOUND", turno="BLUE DAY", status="OPERACIONAL")
        self._colaborador(nome_completo="Trein1", cargo="PIT", area="INBOUND", turno="BLUE DAY", status="Treinamento")
        self._colaborador(nome_completo="Aus1", cargo="Associado", area="OUTBOUND", turno="BLUE DAY", status="Ausência")
        self._colaborador(nome_completo="Ferias1", cargo="Associado", area="OUTBOUND", turno="BLUE DAY", status="Férias")
        self._colaborador(nome_completo="Deslig1", cargo="Associado", area="ICQA", turno="BLUE DAY", status="Desligado")

        with self._como():
            resposta = self.client.get("/api/hc/tree?turno=BLUE DAY")
        self.assertEqual(resposta.status_code, 200)
        data = resposta.get_json()

        self.assertEqual(data["total"], 3)  # Op1 + Trein1 + Aus1 (não conta Férias nem Desligado)
        self.assertIn("INBOUND", data["areas"])
        self.assertIn("OUTBOUND", data["areas"])
        self.assertNotIn("ICQA", data["areas"])  # só tinha o desligado -> coluna some
        nomes_inbound = {item["nome_completo"] for item in data["areas"]["INBOUND"]}
        self.assertEqual(nomes_inbound, {"Op1", "Trein1"})

    def test_turno_adm_aparece_em_qualquer_turno_selecionado(self):
        self._colaborador(nome_completo="AdmSempre", cargo="Analista", area="RME", turno="ADM", status="OPERACIONAL")
        with self._como():
            resposta = self.client.get("/api/hc/tree?turno=RED NIGHT").get_json()
        nomes = {item["nome_completo"] for item in resposta["areas"].get("RME", [])}
        self.assertIn("AdmSempre", nomes)

    def test_turno_invalido_cai_pro_padrao_blue_day(self):
        self._colaborador(nome_completo="X", cargo="Associado", area="INBOUND", turno="BLUE DAY")
        with self._como():
            resposta = self.client.get("/api/hc/tree?turno=lixo-invalido").get_json()
        self.assertEqual(resposta["turno"], "BLUE DAY")

    def test_sem_area_cai_num_balde_proprio(self):
        self._colaborador(nome_completo="Perdido", cargo="Associado", area=None, turno="BLUE DAY")
        with self._como():
            resposta = self.client.get("/api/hc/tree?turno=BLUE DAY").get_json()
        self.assertIn("SEM ÁREA", resposta["areas"])
        self.assertEqual(resposta["areas"]["SEM ÁREA"][0]["nome_completo"], "Perdido")

    def test_pode_mover_reflete_can_edit(self):
        with self._como(can_edit=True):
            self.assertTrue(self.client.get("/api/hc/tree").get_json()["pode_mover"])
        with self._como(can_edit=False):
            self.assertFalse(self.client.get("/api/hc/tree").get_json()["pode_mover"])

    def test_api_bloqueada_sem_permissao_de_dashboard(self):
        with self._como(can_dashboard=False):
            resposta = self.client.get("/api/hc/tree")
        self.assertEqual(resposta.status_code, 403)


class TreeMoverViaPutTest(TreeTestBase):
    """O drag-and-drop da Tree chama o MESMO PUT /api/hc/<id> que o modal de
    edição do LIST usa - confirma que o payload mínimo que o front manda
    (area + turno, só isso) move corretamente sem perder o turno. _registrar
    não é mockado aqui de propósito, pra conferir o texto gravado no histórico."""

    def test_mover_area_preserva_turno_e_demais_campos(self):
        colaborador = self._colaborador(
            nome_completo="Movido", login="movido1", cargo="Associado",
            area="INBOUND", turno="BLUE DAY", status="OPERACIONAL", agencia="Agência X",
        )
        with self._como():
            resposta = self.client.put(f"/api/hc/{colaborador.id}", json={"area": "OUTBOUND", "turno": "BLUE DAY"})
        self.assertEqual(resposta.status_code, 200)

        db.session.refresh(colaborador)
        self.assertEqual(colaborador.area, "OUTBOUND")
        self.assertEqual(colaborador.turno, "BLUE DAY")  # não foi apagado
        self.assertEqual(colaborador.status, "OPERACIONAL")
        self.assertEqual(colaborador.nome_completo, "Movido")
        self.assertEqual(colaborador.login, "movido1")
        self.assertEqual(colaborador.agencia, "Agência X")

    def test_mover_area_sem_mandar_turno_apaga_o_turno(self):
        """Documenta um comportamento já existente do PUT genérico (não é bug
        introduzido pela Tree): omitir 'turno' no payload zera o campo. Por
        isso o front da Tree SEMPRE manda o turno atual junto - ver tree.html."""
        colaborador = self._colaborador(
            nome_completo="SemTurno", cargo="Associado", area="INBOUND", turno="BLUE DAY", status="OPERACIONAL",
        )
        with self._como():
            self.client.put(f"/api/hc/{colaborador.id}", json={"area": "OUTBOUND"})
        db.session.refresh(colaborador)
        self.assertIsNone(colaborador.turno)

    def test_mover_area_fica_registrado_no_historico(self):
        colaborador = self._colaborador(nome_completo="Audit1", cargo="Associado", area="INBOUND", turno="BLUE DAY")
        with self._como():
            self.client.put(f"/api/hc/{colaborador.id}", json={"area": "ICQA", "turno": "BLUE DAY"})

        registro = RegistroAtividade.query.filter_by(operador_id=colaborador.id).first()
        self.assertIsNotNone(registro)
        self.assertIn("setor: INBOUND → ICQA", registro.descricao)


if __name__ == "__main__":
    unittest.main()

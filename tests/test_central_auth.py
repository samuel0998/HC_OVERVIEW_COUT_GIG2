import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask

from models import db
from models.central_auth import AcessoAplicacao, Aplicacao, AuditoriaCentral, ChaveAplicacao
from models.operadores import Operadores
from routes.central import central_bp


class CentralAuthTestBase(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.config.update(
            TESTING=True,
            LOGIN_DISABLED=True,
            SECRET_KEY="teste",
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            SQLALCHEMY_BINDS={"GIG2": "sqlite:///:memory:"},
        )
        db.init_app(app)
        app.register_blueprint(central_bp)
        self.context = app.app_context()
        self.context.push()
        self.addCleanup(self.context.pop)
        self.addCleanup(db.session.remove)
        for model in (Operadores, Aplicacao, ChaveAplicacao, AcessoAplicacao, AuditoriaCentral):
            model.__table__.create(bind=db.engines["GIG2"])
        self.client = app.test_client()

    def _como(self, operador):
        return patch("routes.central.current_user", operador)

    def _admin(self, login="admin1"):
        return Operadores(login=login, nome="Admin", permission_hcview=True, permission_level_hcview="EXPERT")

    def _usuario_comum(self, login="comum1"):
        return Operadores(login=login, nome="Comum", permission_hcview=True, permission_level_hcview="LC3")

    def _criar_app(self, slug="labordash", nome="LaborDash"):
        aplicacao = Aplicacao(slug=slug, nome=nome, ativa=True)
        db.session.add(aplicacao)
        db.session.commit()
        return aplicacao

    def _criar_chave(self, aplicacao):
        chave, segredo = ChaveAplicacao.gerar(aplicacao.id, "teste", "admin1")
        db.session.add(chave)
        db.session.commit()
        return chave, segredo

    def _autorizar(self, segredo, usuario_login, permissao_necessaria=None):
        body = {"usuario_login": usuario_login}
        if permissao_necessaria:
            body["permissao_necessaria"] = permissao_necessaria
        return self.client.post(
            "/api/central/autorizar",
            json=body,
            headers={"Authorization": f"Bearer {segredo}"},
        )


class AutorizacaoCentralTest(CentralAuthTestBase):
    """Cenários 1, 2, 3, 4, 5, 6, 8, 9 (indisponibilidade cobre o contrato/
    middleware de exemplo - ver tests/test_central_auth_middleware_exemplo.py)."""

    def test_usuario_liberado_acessa_aplicacao_autorizada(self):
        usuario = Operadores(login="joao", nome="Joao")
        db.session.add(usuario)
        app1 = self._criar_app()
        chave, segredo = self._criar_chave(app1)
        acesso = AcessoAplicacao(usuario_login="joao", aplicacao_id=app1.id, perfil="GESTOR", concedido_por="admin1")
        db.session.add(acesso)
        db.session.commit()

        response = self._autorizar(segredo, "joao")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["autorizado"])
        self.assertEqual(data["motivo"], "ok")
        self.assertEqual(data["acesso"]["perfil"], "GESTOR")

    def test_usuario_sem_liberacao_recebe_403(self):
        db.session.add(Operadores(login="maria", nome="Maria"))
        app1 = self._criar_app()
        chave, segredo = self._criar_chave(app1)
        db.session.commit()

        response = self._autorizar(segredo, "maria")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["motivo"], "sem_liberacao")

    def test_credencial_invalida_recebe_401(self):
        response = self._autorizar("chave-que-nao-existe", "joao")
        self.assertEqual(response.status_code, 401)

    def test_credencial_expirada_recebe_401(self):
        app1 = self._criar_app()
        chave, segredo = self._criar_chave(app1)
        chave.expira_em = datetime.utcnow() - timedelta(days=1)
        db.session.commit()

        response = self._autorizar(segredo, "joao")
        self.assertEqual(response.status_code, 401)

    def test_usuario_bloqueado_perde_acesso_apesar_de_liberacao_ativa(self):
        db.session.add(Operadores(login="pedro", nome="Pedro", bloqueado_global=True))
        app1 = self._criar_app()
        chave, segredo = self._criar_chave(app1)
        db.session.add(AcessoAplicacao(usuario_login="pedro", aplicacao_id=app1.id, concedido_por="admin1"))
        db.session.commit()

        response = self._autorizar(segredo, "pedro")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["motivo"], "usuario_bloqueado")

    def test_revogacao_vale_na_proxima_requisicao(self):
        db.session.add(Operadores(login="ana", nome="Ana"))
        app1 = self._criar_app()
        chave, segredo = self._criar_chave(app1)
        db.session.add(AcessoAplicacao(usuario_login="ana", aplicacao_id=app1.id, concedido_por="admin1"))
        db.session.commit()

        primeira = self._autorizar(segredo, "ana")
        self.assertTrue(primeira.get_json()["autorizado"])

        with self._como(self._admin()):
            acesso = AcessoAplicacao.query.filter_by(usuario_login="ana", aplicacao_id=app1.id).first()
            resp_revogar = self.client.post(f"/api/central/usuarios/ana/acessos/{app1.id}/revogar")
            self.assertEqual(resp_revogar.status_code, 200)

        segunda = self._autorizar(segredo, "ana")
        self.assertEqual(segunda.status_code, 403)
        self.assertEqual(segunda.get_json()["motivo"], "liberacao_revogada")

    def test_liberacao_expirada_nega_acesso(self):
        db.session.add(Operadores(login="lucas", nome="Lucas"))
        app1 = self._criar_app()
        chave, segredo = self._criar_chave(app1)
        db.session.add(AcessoAplicacao(
            usuario_login="lucas", aplicacao_id=app1.id, concedido_por="admin1",
            expira_em=datetime.utcnow() - timedelta(hours=1),
        ))
        db.session.commit()

        response = self._autorizar(segredo, "lucas")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["motivo"], "liberacao_expirada")

    def test_liberacao_para_uma_app_nao_libera_outra(self):
        db.session.add(Operadores(login="rafa", nome="Rafa"))
        app_a = self._criar_app(slug="labordash", nome="LaborDash")
        app_b = self._criar_app(slug="dockview", nome="DockView")
        _, segredo_b = self._criar_chave(app_b)
        db.session.add(AcessoAplicacao(usuario_login="rafa", aplicacao_id=app_a.id, concedido_por="admin1"))
        db.session.commit()

        # Chave é da app B, mas o usuário só tem liberação pra app A.
        response = self._autorizar(segredo_b, "rafa")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["motivo"], "sem_liberacao")

    def test_chave_revogada_deixa_de_funcionar(self):
        db.session.add(Operadores(login="bia", nome="Bia"))
        app1 = self._criar_app()
        chave, segredo = self._criar_chave(app1)
        db.session.add(AcessoAplicacao(usuario_login="bia", aplicacao_id=app1.id, concedido_por="admin1"))
        db.session.commit()

        self.assertEqual(self._autorizar(segredo, "bia").status_code, 200)

        with self._como(self._admin()):
            self.client.post(f"/api/central/chaves/{chave.id}/revogar")

        response = self._autorizar(segredo, "bia")
        self.assertEqual(response.status_code, 401)

    def test_aplicacao_inativa_nega_mesmo_com_liberacao_ativa(self):
        db.session.add(Operadores(login="caio", nome="Caio"))
        app1 = self._criar_app()
        chave, segredo = self._criar_chave(app1)
        db.session.add(AcessoAplicacao(usuario_login="caio", aplicacao_id=app1.id, concedido_por="admin1"))
        db.session.commit()

        with self._como(self._admin()):
            self.client.patch(f"/api/central/aplicacoes/{app1.id}", json={"ativa": False})

        response = self._autorizar(segredo, "caio")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["motivo"], "aplicacao_inativa")

    def test_permissao_insuficiente_quando_exigida_e_nao_concedida(self):
        db.session.add(Operadores(login="dani", nome="Dani"))
        app1 = self._criar_app()
        chave, segredo = self._criar_chave(app1)
        db.session.add(AcessoAplicacao(usuario_login="dani", aplicacao_id=app1.id, permissoes='["ler"]', concedido_por="admin1"))
        db.session.commit()

        response = self._autorizar(segredo, "dani", permissao_necessaria="editar")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["motivo"], "permissao_insuficiente")


class AdministracaoCentralTest(CentralAuthTestBase):
    """Cenários 7 e 10: usuário comum não concede permissão; rotas protegidas
    exigem admin (não dá pra contornar escondendo botão no front)."""

    def test_usuario_comum_nao_consegue_conceder_acesso(self):
        app1 = self._criar_app()
        db.session.add(Operadores(login="comum1", nome="Comum"))
        db.session.commit()

        with self._como(self._usuario_comum()):
            response = self.client.put(
                f"/api/central/usuarios/comum1/acessos/{app1.id}",
                json={"perfil": "ADMIN"},
            )
        self.assertEqual(response.status_code, 403)
        self.assertIsNone(AcessoAplicacao.query.filter_by(usuario_login="comum1", aplicacao_id=app1.id).first())

    def test_usuario_comum_nao_consegue_criar_aplicacao_nem_chave(self):
        with self._como(self._usuario_comum()):
            r1 = self.client.post("/api/central/aplicacoes", json={"slug": "nova", "nome": "Nova"})
            self.assertEqual(r1.status_code, 403)

        app1 = self._criar_app()
        with self._como(self._usuario_comum()):
            r2 = self.client.post(f"/api/central/aplicacoes/{app1.id}/chaves", json={"nome": "x"})
            self.assertEqual(r2.status_code, 403)

    def test_usuario_comum_nao_consegue_bloquear_ninguem(self):
        db.session.add(Operadores(login="alvo1", nome="Alvo"))
        db.session.commit()
        with self._como(self._usuario_comum()):
            response = self.client.post("/api/central/usuarios/alvo1/bloquear", json={"bloquear": True})
        self.assertEqual(response.status_code, 403)

    def test_admin_pode_conceder_e_bloquear(self):
        app1 = self._criar_app()
        db.session.add(Operadores(login="fulano", nome="Fulano"))
        db.session.commit()

        with self._como(self._admin()):
            r1 = self.client.put(f"/api/central/usuarios/fulano/acessos/{app1.id}", json={
                "perfil": "GESTOR", "permissoes": ["ler", "editar"], "expira_em": "",
            })
            self.assertEqual(r1.status_code, 200)

            r2 = self.client.post("/api/central/usuarios/fulano/bloquear", json={"bloquear": True})
            self.assertEqual(r2.status_code, 200)

        operador = db.session.get(Operadores, "fulano")
        self.assertTrue(operador.bloqueado_global)

    def test_admin_nao_pode_bloquear_a_si_mesmo(self):
        admin = self._admin()
        db.session.add(admin)
        db.session.commit()
        with self._como(admin):
            response = self.client.post(f"/api/central/usuarios/{admin.login}/bloquear", json={"bloquear": True})
        self.assertEqual(response.status_code, 400)

    def test_perfil_invalido_para_a_aplicacao_e_rejeitado(self):
        app1 = Aplicacao(slug="restrita", nome="Restrita", perfis_disponiveis='["LEITURA","ADMIN"]')
        db.session.add(app1)
        db.session.add(Operadores(login="x1", nome="X1"))
        db.session.commit()
        with self._como(self._admin()):
            response = self.client.put(f"/api/central/usuarios/x1/acessos/{app1.id}", json={"perfil": "SUPERUSER"})
        self.assertEqual(response.status_code, 400)

    def test_auditoria_registra_concessao_e_revogacao(self):
        app1 = self._criar_app()
        db.session.add(Operadores(login="y1", nome="Y1"))
        db.session.commit()
        with self._como(self._admin()):
            self.client.put(f"/api/central/usuarios/y1/acessos/{app1.id}", json={"perfil": "GESTOR"})
            self.client.post(f"/api/central/usuarios/y1/acessos/{app1.id}/revogar")
            resposta = self.client.get("/api/central/usuarios/y1/auditoria")

        tipos = [item["tipo"] for item in resposta.get_json()]
        self.assertIn("acesso_concedido", tipos)
        self.assertIn("acesso_revogado", tipos)

    def test_segredo_so_aparece_na_criacao(self):
        app1 = self._criar_app()
        with self._como(self._admin()):
            criada = self.client.post(f"/api/central/aplicacoes/{app1.id}/chaves", json={"nome": "prod"})
            self.assertIn("segredo", criada.get_json()["item"])

            listagem = self.client.get(f"/api/central/aplicacoes/{app1.id}/chaves")
            for item in listagem.get_json():
                self.assertNotIn("segredo", item)
                self.assertNotIn("hash_segredo", item)

    def test_excluir_aplicacao_remove_chaves_e_acessos_em_cascata(self):
        """Exclusão (ex.: limpar cadastro de teste) tem que apagar tudo que
        depende da aplicação - senão a liberação continua "viva" pra outra
        aplicação que reaproveitasse o mesmo id, e a chave técnica continuaria
        existindo (hash) sem dono."""
        app1 = self._criar_app(slug="teste-app", nome="Teste App")
        chave, segredo = self._criar_chave(app1)
        db.session.add(Operadores(login="walter", nome="Walter"))
        db.session.add(AcessoAplicacao(usuario_login="walter", aplicacao_id=app1.id, concedido_por="admin1"))
        db.session.commit()
        app_id, chave_id = app1.id, chave.id  # captura antes do delete - os objetos ORM expiram apos o commit da rota

        with self._como(self._admin()):
            resposta = self.client.delete(f"/api/central/aplicacoes/{app_id}")
        self.assertEqual(resposta.status_code, 200)

        self.assertIsNone(Aplicacao.query.get(app_id))
        self.assertIsNone(ChaveAplicacao.query.get(chave_id))
        self.assertIsNone(AcessoAplicacao.query.filter_by(usuario_login="walter", aplicacao_id=app_id).first())

    def test_excluir_aplicacao_registra_auditoria(self):
        app1 = self._criar_app(slug="outra-teste", nome="Outra Teste")
        with self._como(self._admin()):
            self.client.delete(f"/api/central/aplicacoes/{app1.id}")
            registros = AuditoriaCentral.query.filter_by(tipo="aplicacao_excluida").all()
        self.assertEqual(len(registros), 1)
        self.assertIn("Outra Teste", registros[0].descricao)

    def test_usuario_comum_nao_consegue_excluir_aplicacao(self):
        app1 = self._criar_app()
        with self._como(self._usuario_comum()):
            resposta = self.client.delete(f"/api/central/aplicacoes/{app1.id}")
        self.assertEqual(resposta.status_code, 403)
        self.assertIsNotNone(Aplicacao.query.get(app1.id))

    def test_excluir_aplicacao_inexistente_404(self):
        with self._como(self._admin()):
            resposta = self.client.delete("/api/central/aplicacoes/9999")
        self.assertEqual(resposta.status_code, 404)


if __name__ == "__main__":
    unittest.main()

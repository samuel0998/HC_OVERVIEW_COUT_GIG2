"""Autenticação por chave de segurança (YubiKey): cada chave física tem um ID
público e ESTÁVEL nos 12 primeiros caracteres do OTP que ela "digita" (o
restante muda a cada toque). Esta entrega NÃO valida o OTP completo contra a
YubiCloud (simplificação deliberada, a pedido) - só confere o ID público
contra o que foi cadastrado pra cada usuário (ver models/central_auth.py).

Cobre:
  - extrair_yubikey_id: normalização/extração do ID a partir do OTP ou do
    próprio ID já isolado.
  - Cadastro/revogação da chave de um usuário (admin only), incluindo conflito
    quando a mesma chave já está ativa pra outro usuário, e reaproveitamento
    de uma chave revogada pra um novo dono.
  - /api/central/identificar-por-chave: outra aplicação resolve QUEM é o
    dono da chave (passo de IDENTIDADE, separado de AUTORIZAÇÃO).
  - Login da própria HC Overview por chave (routes/auth.py), e que o login
    (por chave ou por nome) agora fica "lembrado" (remember=True) em vez de
    pedir pra entrar de novo a cada atualização de página.
"""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from flask import Blueprint, Flask

from models import db
from models.central_auth import (
    Aplicacao,
    AuditoriaCentral,
    ChaveAplicacao,
    ChaveFisicaUsuario,
    extrair_yubikey_id,
)
from models.operadores import Operadores
from routes.central import central_bp

# OTPs de exemplo no formato real da YubiKey (44 caracteres, ModHex) - mesmo
# padrão usado pelo usuário: os 12 primeiros caracteres repetem entre toques
# da MESMA chave física; o resto varia.
OTP_CHAVE_A_1 = "eifjcbrifgtbcfvitktebehdknbjbkhrigvfrtggfbku"[:44]
OTP_CHAVE_A_2 = "eifjcbrifgtbhbcuuvlerrhnnhldjbfejctiecrilhkf"[:44]
OTP_CHAVE_B_1 = "cccccblivbubbcvvfchdjldngdifhfiifrkcrnnfleiv"[:44]


class ExtrairYubikeyIdTest(unittest.TestCase):
    def test_extrai_12_primeiros_caracteres_de_um_otp_completo(self):
        self.assertEqual(extrair_yubikey_id(OTP_CHAVE_A_1), "eifjcbrifgtb")
        self.assertEqual(extrair_yubikey_id(OTP_CHAVE_A_2), "eifjcbrifgtb")

    def test_toques_diferentes_da_mesma_chave_geram_o_mesmo_id(self):
        self.assertEqual(extrair_yubikey_id(OTP_CHAVE_A_1), extrair_yubikey_id(OTP_CHAVE_A_2))

    def test_chaves_fisicas_diferentes_geram_ids_diferentes(self):
        self.assertNotEqual(extrair_yubikey_id(OTP_CHAVE_A_1), extrair_yubikey_id(OTP_CHAVE_B_1))

    def test_aceita_o_id_ja_isolado_sem_o_otp_completo(self):
        self.assertEqual(extrair_yubikey_id("eifjcbrifgtb"), "eifjcbrifgtb")

    def test_normaliza_maiusculas_e_espacos(self):
        self.assertEqual(extrair_yubikey_id("  EIFJCBRIFGTB  "), "eifjcbrifgtb")

    def test_string_curta_demais_nao_tem_id(self):
        self.assertIsNone(extrair_yubikey_id("abc"))

    def test_vazio_ou_none_nao_tem_id(self):
        self.assertIsNone(extrair_yubikey_id(""))
        self.assertIsNone(extrair_yubikey_id(None))


class _CentralTestBase(unittest.TestCase):
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
        for model in (Operadores, Aplicacao, ChaveAplicacao, ChaveFisicaUsuario, AuditoriaCentral):
            model.__table__.create(bind=db.engines["GIG2"])
        self.client = app.test_client()

    def _como(self, operador):
        return patch("routes.central.current_user", operador)

    def _admin(self, login="admin1"):
        return Operadores(login=login, nome="Admin", permission_hcview=True, permission_level_hcview="EXPERT")

    def _usuario_comum(self, login="comum1"):
        return Operadores(login=login, nome="Comum", permission_hcview=True, permission_level_hcview="LC3")

    def _criar_app_e_chave(self, slug="maestro"):
        aplicacao = Aplicacao(slug=slug, nome=slug.title(), ativa=True)
        db.session.add(aplicacao)
        db.session.commit()
        chave, segredo = ChaveAplicacao.gerar(aplicacao.id, "teste", "admin1")
        db.session.add(chave)
        db.session.commit()
        return aplicacao, segredo


class CadastroChaveFisicaTest(_CentralTestBase):
    def test_admin_cadastra_chave_pro_usuario(self):
        db.session.add(Operadores(login="joao", nome="Joao"))
        db.session.commit()

        with self._como(self._admin()):
            resposta = self.client.post(
                "/api/central/usuarios/joao/chaves-fisicas",
                json={"otp_ou_id": OTP_CHAVE_A_1, "apelido": "YubiKey azul"},
            )
        self.assertEqual(resposta.status_code, 201)
        item = resposta.get_json()["item"]
        self.assertEqual(item["yubikey_id"], "eifjcbrifgtb")
        self.assertEqual(item["apelido"], "YubiKey azul")
        self.assertTrue(item["ativa"])

    def test_usuario_comum_nao_pode_cadastrar_chave(self):
        db.session.add(Operadores(login="joao", nome="Joao"))
        db.session.commit()
        with self._como(self._usuario_comum()):
            resposta = self.client.post(
                "/api/central/usuarios/joao/chaves-fisicas",
                json={"otp_ou_id": OTP_CHAVE_A_1},
            )
        self.assertEqual(resposta.status_code, 403)

    def test_otp_curto_demais_e_rejeitado(self):
        db.session.add(Operadores(login="joao", nome="Joao"))
        db.session.commit()
        with self._como(self._admin()):
            resposta = self.client.post(
                "/api/central/usuarios/joao/chaves-fisicas",
                json={"otp_ou_id": "abc"},
            )
        self.assertEqual(resposta.status_code, 400)

    def test_mesma_chave_ativa_nao_pode_ser_cadastrada_pra_outro_usuario(self):
        db.session.add(Operadores(login="joao", nome="Joao"))
        db.session.add(Operadores(login="maria", nome="Maria"))
        db.session.commit()

        with self._como(self._admin()):
            r1 = self.client.post("/api/central/usuarios/joao/chaves-fisicas", json={"otp_ou_id": OTP_CHAVE_A_1})
            self.assertEqual(r1.status_code, 201)

            r2 = self.client.post("/api/central/usuarios/maria/chaves-fisicas", json={"otp_ou_id": OTP_CHAVE_A_2})
            self.assertEqual(r2.status_code, 409)

    def test_revogar_libera_a_chave_pra_ser_recadastrada_em_outro_usuario(self):
        db.session.add(Operadores(login="joao", nome="Joao"))
        db.session.add(Operadores(login="maria", nome="Maria"))
        db.session.commit()

        with self._como(self._admin()):
            r1 = self.client.post("/api/central/usuarios/joao/chaves-fisicas", json={"otp_ou_id": OTP_CHAVE_A_1})
            chave_id = r1.get_json()["item"]["id"]

            r_revogar = self.client.post(f"/api/central/chaves-fisicas/{chave_id}/revogar")
            self.assertEqual(r_revogar.status_code, 200)

            r2 = self.client.post("/api/central/usuarios/maria/chaves-fisicas", json={"otp_ou_id": OTP_CHAVE_A_2})
            self.assertEqual(r2.status_code, 201)
            self.assertEqual(r2.get_json()["item"]["usuario_login"], "maria")

        # Mesma chave física (mesmo yubikey_id) -> a linha é reativada e
        # reatribuída à nova dona, em vez de criar uma segunda linha pro
        # mesmo ID público (evitaria duplicidade na unique constraint).
        chave_recadastrada = db.session.get(ChaveFisicaUsuario, chave_id)
        self.assertTrue(chave_recadastrada.ativa)
        self.assertEqual(chave_recadastrada.usuario_login, "maria")

    def test_chave_revogada_some_da_listagem_de_chaves_ativas_mas_fica_na_auditoria(self):
        db.session.add(Operadores(login="joao", nome="Joao"))
        db.session.commit()
        with self._como(self._admin()):
            r1 = self.client.post("/api/central/usuarios/joao/chaves-fisicas", json={"otp_ou_id": OTP_CHAVE_A_1})
            chave_id = r1.get_json()["item"]["id"]
            self.client.post(f"/api/central/chaves-fisicas/{chave_id}/revogar")

            listagem = self.client.get("/api/central/usuarios/joao/chaves-fisicas").get_json()
            auditoria = self.client.get("/api/central/usuarios/joao/auditoria").get_json()

        self.assertFalse(listagem[0]["ativa"])
        tipos = [a["tipo"] for a in auditoria]
        self.assertIn("chave_fisica_cadastrada", tipos)
        self.assertIn("chave_fisica_revogada", tipos)


class IdentificarPorChaveTest(_CentralTestBase):
    def test_app_identifica_o_dono_de_uma_chave_cadastrada(self):
        aplicacao, segredo = self._criar_app_e_chave()
        db.session.add(Operadores(login="joao", nome="Joao"))
        db.session.commit()
        with self._como(self._admin()):
            self.client.post("/api/central/usuarios/joao/chaves-fisicas", json={"otp_ou_id": OTP_CHAVE_A_1})

        resposta = self.client.post(
            "/api/central/identificar-por-chave",
            json={"otp_ou_id": OTP_CHAVE_A_2},  # outro toque da MESMA chave física
            headers={"Authorization": f"Bearer {segredo}"},
        )
        self.assertEqual(resposta.status_code, 200)
        data = resposta.get_json()
        self.assertTrue(data["identificado"])
        self.assertEqual(data["usuario_login"], "joao")

    def test_chave_nao_cadastrada_nao_identifica_ninguem(self):
        aplicacao, segredo = self._criar_app_e_chave()
        resposta = self.client.post(
            "/api/central/identificar-por-chave",
            json={"otp_ou_id": OTP_CHAVE_B_1},
            headers={"Authorization": f"Bearer {segredo}"},
        )
        self.assertEqual(resposta.status_code, 404)
        self.assertFalse(resposta.get_json()["identificado"])

    def test_credencial_de_aplicacao_invalida_recebe_401(self):
        resposta = self.client.post(
            "/api/central/identificar-por-chave",
            json={"otp_ou_id": OTP_CHAVE_A_1},
            headers={"Authorization": "Bearer chave-errada"},
        )
        self.assertEqual(resposta.status_code, 401)

    def test_usuario_bloqueado_nao_e_identificado_apesar_da_chave_valida(self):
        aplicacao, segredo = self._criar_app_e_chave()
        db.session.add(Operadores(login="pedro", nome="Pedro", bloqueado_global=True))
        db.session.commit()
        with self._como(self._admin()):
            self.client.post("/api/central/usuarios/pedro/chaves-fisicas", json={"otp_ou_id": OTP_CHAVE_A_1})

        resposta = self.client.post(
            "/api/central/identificar-por-chave",
            json={"otp_ou_id": OTP_CHAVE_A_1},
            headers={"Authorization": f"Bearer {segredo}"},
        )
        self.assertEqual(resposta.status_code, 403)
        self.assertFalse(resposta.get_json()["identificado"])


class LoginPorChaveETempoDeSessaoTest(unittest.TestCase):
    """Fim a fim na própria rota de login da HC Overview (routes/auth.py):
    login por chave resolve o usuário certo, e tanto esse login quanto o
    tradicional por nome agora usam remember=True (não pedem pra entrar de
    novo a cada atualização de página - ver config.py)."""

    def setUp(self):
        from pathlib import Path

        from flask_login import LoginManager

        from routes.auth import auth_bp

        template_dir = Path(__file__).resolve().parent.parent / "templates"
        app = Flask(__name__, template_folder=str(template_dir))
        app.config.update(
            TESTING=True,
            SECRET_KEY="teste",
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            SQLALCHEMY_BINDS={"GIG2": "sqlite:///:memory:"},
            FC_DATABASES={"GIG2": {"label": "GIG2", "bootstrap_on_startup": True}},
            DEFAULT_FC="GIG2",
            WTF_CSRF_ENABLED=False,
        )
        db.init_app(app)

        login_manager = LoginManager()
        login_manager.init_app(app)
        login_manager.login_view = "auth.login"

        @login_manager.user_loader
        def load_user(user_id):
            return db.session.get(Operadores, user_id)

        hc_fake = Blueprint("hc", __name__)

        @hc_fake.route("/home")
        def home():
            return "home", 200

        @app.context_processor
        def _inject_fc_context():
            # Réplica mínima do context_processor real (ver app.py) - só o
            # suficiente pra login.html renderizar sem erro neste app de teste.
            return {"active_fc_logo": "lion_logo.png", "active_fc_label": "GIG2", "active_fc": "GIG2"}

        app.register_blueprint(auth_bp)
        app.register_blueprint(hc_fake)

        self.context = app.app_context()
        self.context.push()
        self.addCleanup(self.context.pop)
        self.addCleanup(db.session.remove)
        Operadores.__table__.create(bind=db.engines["GIG2"])
        ChaveFisicaUsuario.__table__.create(bind=db.engines["GIG2"])
        self.client = app.test_client()

    def test_login_por_chave_de_seguranca_autentica_o_dono_certo(self):
        db.session.add(Operadores(login="joao", nome="Joao", permission_hcview=True, permission_level_hcview="LC3"))
        db.session.add(ChaveFisicaUsuario(usuario_login="joao", yubikey_id="eifjcbrifgtb", cadastrada_por="admin1"))
        db.session.commit()

        resposta = self.client.post("/login", data={"fc": "GIG2", "yubikey_otp": OTP_CHAVE_A_1}, follow_redirects=False)
        self.assertEqual(resposta.status_code, 302)
        self.assertIn("/home", resposta.headers["Location"])

        chave = ChaveFisicaUsuario.query.filter_by(yubikey_id="eifjcbrifgtb").first()
        self.assertIsNotNone(chave.ultimo_uso_em)

    def test_login_fica_lembrado_entre_atualizacoes_de_pagina(self):
        """remember=True grava o cookie remember_token - sem ele, um refresh
        que descarte o cookie de sessão simples jogaria o usuário pro login."""
        db.session.add(Operadores(login="joao", nome="Joao", permission_hcview=True, permission_level_hcview="LC3"))
        db.session.add(ChaveFisicaUsuario(usuario_login="joao", yubikey_id="eifjcbrifgtb", cadastrada_por="admin1"))
        db.session.commit()

        resposta = self.client.post("/login", data={"fc": "GIG2", "yubikey_otp": OTP_CHAVE_A_1})
        cookies = "; ".join(resposta.headers.get_all("Set-Cookie"))
        self.assertIn("remember_token", cookies)

    def test_login_tradicional_por_nome_tambem_fica_lembrado(self):
        db.session.add(Operadores(login="maria", nome="Maria", permission_hcview=True, permission_level_hcview="LC3"))
        db.session.commit()

        resposta = self.client.post("/login", data={"fc": "GIG2", "login": "maria"})
        self.assertEqual(resposta.status_code, 302)
        cookies = "; ".join(resposta.headers.get_all("Set-Cookie"))
        self.assertIn("remember_token", cookies)

    def test_chave_nao_cadastrada_mostra_erro_e_nao_autentica(self):
        resposta = self.client.post("/login", data={"fc": "GIG2", "yubikey_otp": OTP_CHAVE_B_1})
        self.assertEqual(resposta.status_code, 200)
        self.assertIn(b"Chave de seguran", resposta.data)

    def test_usuario_sem_permissao_hcview_nao_entra_mesmo_com_chave_valida(self):
        db.session.add(Operadores(login="semacesso", nome="Sem Acesso", permission_hcview=False))
        db.session.add(ChaveFisicaUsuario(usuario_login="semacesso", yubikey_id="eifjcbrifgtb", cadastrada_por="admin1"))
        db.session.commit()

        resposta = self.client.post("/login", data={"fc": "GIG2", "yubikey_otp": OTP_CHAVE_A_1})
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("Voce nao tem permissao".encode("latin-1"), resposta.data)


if __name__ == "__main__":
    unittest.main()

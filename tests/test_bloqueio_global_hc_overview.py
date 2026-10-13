"""O bloqueio global tem que valer também DENTRO da própria HC Overview, não só
nas aplicações externas - mesmo com uma sessão de login ainda válida (ver
app.py:_negar_bloqueado_global). Reproduz aqui o mesmo hook (poucas linhas,
copiadas fielmente) num app Flask mínimo, pra não precisar subir a aplicação
real (que se conectaria às bases de produção no boot)."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask, jsonify, redirect, request, session, url_for
from flask_login import LoginManager, UserMixin, current_user, login_required, login_user, logout_user


class _UsuarioFalso(UserMixin):
    def __init__(self, login, bloqueado_global=False):
        self.login = login
        self.bloqueado_global = bloqueado_global

    def get_id(self):
        return self.login


class BloqueioGlobalHCOverviewTest(unittest.TestCase):
    def setUp(self):
        self.usuarios = {}

        app = Flask(__name__)
        app.config.update(TESTING=True, SECRET_KEY="teste")

        login_manager = LoginManager()
        login_manager.init_app(app)
        login_manager.login_view = "login"

        @login_manager.user_loader
        def load_user(user_id):
            # Recarrega do "banco" (dict) a cada requisição - reflete bloqueio
            # feito por um admin entre uma requisição e outra, sem cache.
            return self.usuarios.get(user_id)

        @app.route("/login")
        def login():
            return "login", 200

        @app.route("/entrar/<login_val>")
        def entrar(login_val):
            login_user(self.usuarios[login_val])
            return "ok"

        @app.before_request
        def _negar_bloqueado_global():
            if current_user.is_authenticated and getattr(current_user, "bloqueado_global", False):
                logout_user()
                session.pop("fc", None)
                if request.is_json or request.path.startswith("/api/"):
                    return jsonify({"erro": "Acesso bloqueado pelo administrador."}), 403
                return redirect(url_for("login"))

        @app.route("/api/protegida")
        @login_required
        def protegida():
            return jsonify({"conteudo": "DADOS SENSIVEIS"})

        self.app = app
        self.client = app.test_client()

    def test_usuario_bloqueado_perde_acesso_mesmo_com_sessao_valida(self):
        self.usuarios["joao"] = _UsuarioFalso("joao", bloqueado_global=False)
        self.client.get("/entrar/joao")

        # Com a sessão ativa, acessa normalmente.
        r1 = self.client.get("/api/protegida")
        self.assertEqual(r1.status_code, 200)
        self.assertIn(b"DADOS SENSIVEIS", r1.data)

        # Um admin bloqueia o usuário "no banco" - sem o cliente fazer logout.
        self.usuarios["joao"].bloqueado_global = True

        r2 = self.client.get("/api/protegida")
        self.assertEqual(r2.status_code, 403)
        self.assertNotIn(b"DADOS SENSIVEIS", r2.data)

    def test_usuario_nao_bloqueado_continua_acessando(self):
        self.usuarios["ana"] = _UsuarioFalso("ana", bloqueado_global=False)
        self.client.get("/entrar/ana")
        r = self.client.get("/api/protegida")
        self.assertEqual(r.status_code, 200)


if __name__ == "__main__":
    unittest.main()

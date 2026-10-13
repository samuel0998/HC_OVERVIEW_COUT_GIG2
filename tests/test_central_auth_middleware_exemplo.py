"""Prova executável de que o middleware de exemplo (docs/integracao_central/
middleware_flask_exemplo.py) é fail-closed: indisponibilidade da central NUNCA
libera acesso, e rotas protegidas não respondem sem a checagem central (ver
seções 7 e 9/10 do pedido - "Validar a implementação")."""
import importlib.util
import os
import sys
import unittest
from pathlib import Path

import requests

os.environ.setdefault("HC_CENTRAL_URL", "https://hcoverview.teste.local")
os.environ.setdefault("HC_APP_SLUG", "app-teste")
os.environ.setdefault("HC_APP_API_KEY", "chave-de-teste")

_CAMINHO = Path(__file__).resolve().parent.parent / "docs" / "integracao_central" / "middleware_flask_exemplo.py"
_SPEC = importlib.util.spec_from_file_location("middleware_flask_exemplo", _CAMINHO)
middleware = importlib.util.module_from_spec(_SPEC)
sys.modules["middleware_flask_exemplo"] = middleware
_SPEC.loader.exec_module(middleware)


class _RespostaFalsa:
    def __init__(self, status_code, corpo):
        self.status_code = status_code
        self._corpo = corpo
        self.text = str(corpo)

    def json(self):
        return self._corpo


class _SessaoFalsa:
    """Substitui requests pra controlar exatamente o que a central "responde"
    sem bater numa rede de verdade."""
    def __init__(self, comportamento):
        self.comportamento = comportamento  # callable(url, json, headers, timeout) -> _RespostaFalsa | Exception

    def post(self, url, json=None, headers=None, timeout=None):
        resultado = self.comportamento(url, json, headers, timeout)
        if isinstance(resultado, Exception):
            raise resultado
        return resultado


class ConsultarAutorizacaoCentralTest(unittest.TestCase):
    def test_timeout_levanta_indisponivel_sem_autorizar(self):
        sessao = _SessaoFalsa(lambda *a, **k: requests.exceptions.Timeout("timeout"))
        with self.assertRaises(middleware.AutorizacaoCentralIndisponivel):
            middleware.consultar_autorizacao_central("joao", sessao_http=sessao)

    def test_erro_de_conexao_levanta_indisponivel_sem_autorizar(self):
        sessao = _SessaoFalsa(lambda *a, **k: requests.exceptions.ConnectionError("recusada"))
        with self.assertRaises(middleware.AutorizacaoCentralIndisponivel):
            middleware.consultar_autorizacao_central("joao", sessao_http=sessao)

    def test_credencial_da_app_invalida_levanta_indisponivel_sem_autorizar(self):
        sessao = _SessaoFalsa(lambda *a, **k: _RespostaFalsa(401, {"erro": "credencial invalida"}))
        with self.assertRaises(middleware.AutorizacaoCentralIndisponivel):
            middleware.consultar_autorizacao_central("joao", sessao_http=sessao)

    def test_central_nega_devolve_autorizado_false(self):
        sessao = _SessaoFalsa(lambda *a, **k: _RespostaFalsa(403, {"autorizado": False, "motivo": "sem_liberacao"}))
        resultado = middleware.consultar_autorizacao_central("joao", sessao_http=sessao)
        self.assertFalse(resultado["autorizado"])

    def test_central_autoriza(self):
        sessao = _SessaoFalsa(lambda *a, **k: _RespostaFalsa(200, {"autorizado": True, "motivo": "ok", "acesso": {"perfil": "GESTOR"}}))
        resultado = middleware.consultar_autorizacao_central("joao", sessao_http=sessao)
        self.assertTrue(resultado["autorizado"])


class DecoratorFlaskTest(unittest.TestCase):
    """Fim a fim: a rota protegida de uma app consumidora exemplo nunca
    responde o conteúdo protegido sem a central aprovar."""

    def _app_exemplo(self, resultado_central=None, excecao_central=None):
        from flask import Flask, g, jsonify
        app = Flask(__name__)
        app.config.update(TESTING=True)

        def _consulta_fake(usuario_login, permissao_necessaria=None, sessao_http=None):
            if excecao_central:
                raise excecao_central
            return resultado_central

        original = middleware.consultar_autorizacao_central
        middleware.consultar_autorizacao_central = _consulta_fake
        self.addCleanup(lambda: setattr(middleware, "consultar_autorizacao_central", original))

        @app.route("/protegida")
        @middleware.exigir_acesso_central(permissao="ler")
        def protegida():
            return jsonify({"conteudo": "DADOS SENSIVEIS", "perfil": g.hc_central_acesso["perfil"]})

        return app

    def test_sem_usuario_identificado_recebe_401_e_nao_vaza_conteudo(self):
        app = self._app_exemplo(resultado_central={"autorizado": True, "acesso": {"perfil": "X"}})
        client = app.test_client()
        resposta = client.get("/protegida")  # sem X-Usuario-Login-Local
        self.assertEqual(resposta.status_code, 401)
        self.assertNotIn(b"DADOS SENSIVEIS", resposta.data)

    def test_central_indisponivel_responde_503_e_nao_vaza_conteudo(self):
        app = self._app_exemplo(excecao_central=middleware.AutorizacaoCentralIndisponivel("fora do ar"))
        client = app.test_client()
        resposta = client.get("/protegida", headers={"X-Usuario-Login-Local": "joao"})
        self.assertEqual(resposta.status_code, 503)
        self.assertNotIn(b"DADOS SENSIVEIS", resposta.data)

    def test_central_nega_responde_403_e_nao_vaza_conteudo(self):
        app = self._app_exemplo(resultado_central={"autorizado": False, "motivo": "sem_liberacao"})
        client = app.test_client()
        resposta = client.get("/protegida", headers={"X-Usuario-Login-Local": "joao"})
        self.assertEqual(resposta.status_code, 403)
        self.assertNotIn(b"DADOS SENSIVEIS", resposta.data)

    def test_central_autoriza_libera_conteudo(self):
        app = self._app_exemplo(resultado_central={"autorizado": True, "motivo": "ok", "acesso": {"perfil": "GESTOR"}})
        client = app.test_client()
        resposta = client.get("/protegida", headers={"X-Usuario-Login-Local": "joao"})
        self.assertEqual(resposta.status_code, 200)
        self.assertIn(b"DADOS SENSIVEIS", resposta.data)


if __name__ == "__main__":
    unittest.main()

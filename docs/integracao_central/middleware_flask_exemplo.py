"""Exemplo DE REFERÊNCIA de middleware Flask pra uma aplicação consumidora se
integrar ao controle central de acesso da HC Overview.

Este arquivo roda e é testado (ver tests/test_central_auth_middleware_exemplo.py
no repositório da HC Overview) para provar o comportamento fail-closed - mas
ele pertence ao REPOSITÓRIO DA OUTRA APLICAÇÃO, não à HC Overview. Copie e
adapte pro seu framework (o contrato HTTP em docs/central_auth_contrato.md é o
que importa; esta implementação é só uma referência em Flask).

Fluxo (ver docs/central_auth_contrato.md):
  1. A aplicação já autenticou o usuário com o PRÓPRIO esquema dela (cookie,
     SSO, o que for) - esse passo NÃO é feito aqui.
  2. O identificador da aplicação (HC_APP_SLUG) e a credencial técnica
     (HC_APP_API_KEY) vêm de configuração confiável do servidor (variável de
     ambiente) - nunca do cliente.
  3. A cada requisição protegida, consulta POST /api/central/autorizar.
  4. 401 da central = credencial da APLICAÇÃO inválida -> erro de config,
     nunca libera (503/500). 403 = usuário autenticado sem permissão -> 403
     pro usuário final. Falha de rede/timeout -> 503, nunca libera.
  5. Nenhum resultado positivo é cacheado entre requisições.
"""
import functools
import os

import requests
from flask import abort, g, jsonify, request

HC_CENTRAL_URL = os.environ["HC_CENTRAL_URL"]        # ex.: https://hcoverview.exemplo.com
HC_APP_SLUG = os.environ["HC_APP_SLUG"]               # identificador estável desta app (config do servidor)
HC_APP_API_KEY = os.environ["HC_APP_API_KEY"]          # credencial técnica desta app (NUNCA no cliente/log)
HC_CENTRAL_TIMEOUT_SEGUNDOS = float(os.environ.get("HC_CENTRAL_TIMEOUT_SEGUNDOS", "3"))


class AutorizacaoCentralIndisponivel(Exception):
    """A central não respondeu a tempo ou está fora do ar. NUNCA deve resultar
    em acesso liberado - quem chama trata isso como 503."""


def _obter_usuario_login_atual():
    """Substitua por como ESTA aplicação já identifica o usuário autenticado
    (sessão, cookie, token próprio etc.) - já resolvido ANTES de chegar aqui.
    Este placeholder é só pra o exemplo rodar sozinho em teste."""
    return getattr(g, "usuario_login", None) or request.headers.get("X-Usuario-Login-Local")


def consultar_autorizacao_central(usuario_login, permissao_necessaria=None, sessao_http=None):
    """Chama a central. Levanta AutorizacaoCentralIndisponivel em qualquer
    falha de rede/timeout - NUNCA retorna "autorizado" nesse caso."""
    corpo = {"usuario_login": usuario_login}
    if permissao_necessaria:
        corpo["permissao_necessaria"] = permissao_necessaria

    cliente = sessao_http or requests
    try:
        resposta = cliente.post(
            f"{HC_CENTRAL_URL}/api/central/autorizar",
            json=corpo,
            headers={"Authorization": f"Bearer {HC_APP_API_KEY}"},
            timeout=HC_CENTRAL_TIMEOUT_SEGUNDOS,
        )
    except requests.exceptions.RequestException as e:
        raise AutorizacaoCentralIndisponivel(str(e)) from e

    if resposta.status_code == 401:
        # Credencial DESTA aplicação inválida/revogada/expirada - erro de
        # configuração do lado da app consumidora, não do usuário. Nunca libera.
        raise AutorizacaoCentralIndisponivel(f"Credencial da aplicação rejeitada pela central: {resposta.text}")
    if resposta.status_code not in (200, 403):
        raise AutorizacaoCentralIndisponivel(f"Resposta inesperada da central: HTTP {resposta.status_code}")

    return resposta.json()


def exigir_acesso_central(permissao=None):
    """Decorator pra rota protegida. 401 = usuário não autenticado NESTA app
    (resolver antes, no esquema de auth local). 403 = autenticado mas sem
    permissão central. 503 = central indisponível - nunca libera."""
    def decorator(view_func):
        @functools.wraps(view_func)
        def wrapper(*args, **kwargs):
            usuario_login = _obter_usuario_login_atual()
            if not usuario_login:
                return jsonify({"erro": "Nao autenticado."}), 401

            try:
                resultado = consultar_autorizacao_central(usuario_login, permissao)
            except AutorizacaoCentralIndisponivel:
                return jsonify({"erro": "Autorizacao central indisponivel. Tente novamente."}), 503

            if not resultado.get("autorizado"):
                return jsonify({"erro": "Sem permissao.", "motivo": resultado.get("motivo")}), 403

            g.hc_central_acesso = resultado.get("acesso")
            g.hc_central_usuario = resultado.get("usuario")
            return view_func(*args, **kwargs)
        return wrapper
    return decorator


# ── Exemplo de uso ───────────────────────────────────────────────────────
#
# from flask import Flask
# app = Flask(__name__)
#
# @app.route("/relatorio-sensivel")
# @exigir_acesso_central(permissao="ler_relatorios")
# def relatorio_sensivel():
#     return jsonify({"ok": True, "perfil": g.hc_central_acesso["perfil"]})

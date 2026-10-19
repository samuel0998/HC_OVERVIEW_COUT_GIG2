"""Controle centralizado de acesso às aplicações integradas.

A HC Overview é a autoridade única: qualquer aplicação integrada consulta
/api/central/autorizar a CADA requisição protegida, autenticando-se com a
própria credencial técnica (nunca em nome do usuário). Ver
docs/central_auth_contrato.md para o contrato completo de integração.

Dois grupos de rotas aqui:
  - Administração (cookie de sessão + is_admin): gerenciar aplicações, chaves
    e liberações - usado pela aba Usuários da HC Overview.
  - Checagem central (chave de API da aplicação, SEM cookie): /autorizar,
    chamada pelo backend de cada aplicação integrada.
"""
import json
from datetime import datetime

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from models import db
from models.central_auth import (
    STATUS_ATIVO,
    STATUS_REVOGADO,
    AcessoAplicacao,
    Aplicacao,
    AuditoriaCentral,
    ChaveAplicacao,
    ChaveFisicaUsuario,
    calcular_hash_segredo,
    extrair_yubikey_id,
)
from models.operadores import Operadores

central_bp = Blueprint("central", __name__, url_prefix="/api/central")


# ── Helpers ────────────────────────────────────────────────────────────


def _registrar_auditoria(tipo, usuario_alvo=None, aplicacao_id=None, descricao=""):
    db.session.add(AuditoriaCentral(
        tipo=tipo,
        usuario_alvo=usuario_alvo,
        aplicacao_id=aplicacao_id,
        ator_login=current_user.login if current_user.is_authenticated else "sistema",
        descricao=descricao,
    ))


def _parse_lista(valor):
    """Normaliza uma lista vinda do front (lista de strings, string separada
    por vírgula, ou vazio) pra JSON de strings."""
    if valor is None:
        return None
    if isinstance(valor, str):
        itens = [v.strip() for v in valor.split(",")]
    elif isinstance(valor, list):
        itens = [str(v).strip() for v in valor]
    else:
        return None
    return json.dumps([v for v in itens if v])


def _parse_datahora(valor):
    if not valor:
        return None
    try:
        return datetime.fromisoformat(valor)
    except ValueError:
        return None


def _resolver_chave_aplicacao():
    """Autentica a APLICAÇÃO chamadora pela credencial técnica (Authorization:
    Bearer <chave>). O identificador da aplicação vem da própria chave - a
    aplicação nunca escolhe no corpo da requisição qual app ela "é" (evita
    contornar a validação pedindo autorização em nome de outra app)."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None, None
    segredo = auth_header[len("Bearer "):].strip()
    if not segredo:
        return None, None

    chave = ChaveAplicacao.query.filter_by(hash_segredo=calcular_hash_segredo(segredo)).first()
    if not chave or not chave.esta_valida():
        return None, None

    aplicacao = Aplicacao.query.get(chave.aplicacao_id)
    if not aplicacao:
        return None, None

    chave.ultimo_uso_em = datetime.utcnow()
    db.session.commit()
    return chave, aplicacao


def avaliar_autorizacao(usuario_login, aplicacao, permissao_necessaria=None):
    """Decisão de autorização, consultada do ZERO a cada chamada - nunca
    cacheada como positiva entre requisições (revogação/bloqueio precisam
    valer na próxima checagem). Devolve (autorizado, motivo, operador, acesso)."""
    if not aplicacao.ativa:
        return False, "aplicacao_inativa", None, None

    login_norm = (usuario_login or "").strip().lower()
    operador = Operadores.query.get(login_norm) if login_norm else None
    if not operador:
        return False, "usuario_nao_encontrado", None, None
    if operador.bloqueado_global:
        return False, "usuario_bloqueado", operador, None

    acesso = AcessoAplicacao.query.filter_by(usuario_login=login_norm, aplicacao_id=aplicacao.id).first()
    if not acesso:
        return False, "sem_liberacao", operador, None
    if acesso.status != STATUS_ATIVO:
        return False, "liberacao_revogada", operador, acesso
    if acesso.esta_expirado():
        return False, "liberacao_expirada", operador, acesso
    if permissao_necessaria and permissao_necessaria not in acesso.lista_permissoes():
        return False, "permissao_insuficiente", operador, acesso

    return True, "ok", operador, acesso


# ── Checagem central (credencial de aplicação, sem cookie) ─────────────


@central_bp.route("/saude", methods=["GET"])
def saude():
    """Rota pública - verificação básica de saúde (ver seção de rotas
    publicas do contrato). Não expõe nenhum dado."""
    return jsonify({"status": "ok"})


@central_bp.route("/autorizar", methods=["POST"])
def autorizar():
    chave, aplicacao = _resolver_chave_aplicacao()
    if not aplicacao:
        return jsonify({"erro": "Credencial da aplicação ausente, inválida, revogada ou expirada."}), 401

    data = request.get_json(silent=True) or {}
    usuario_login = (data.get("usuario_login") or "").strip()
    if not usuario_login:
        return jsonify({"erro": "Informe usuario_login."}), 400
    permissao_necessaria = (data.get("permissao_necessaria") or "").strip() or None

    autorizado, motivo, operador, acesso = avaliar_autorizacao(usuario_login, aplicacao, permissao_necessaria)

    corpo = {
        "autorizado": autorizado,
        "motivo": motivo,
        "aplicacao": {"slug": aplicacao.slug, "nome": aplicacao.nome},
        "usuario": {
            "login": operador.login,
            "nome": operador.nome or operador.login,
            "ativo": not bool(operador.bloqueado_global),
        } if operador else None,
        "acesso": {
            "perfil": acesso.perfil or "",
            "permissoes": acesso.lista_permissoes(),
            "status": acesso.status_calculado(),
            "expira_em": acesso.to_dict()["expira_em"],
        } if acesso else None,
    }
    return jsonify(corpo), (200 if autorizado else 403)


@central_bp.route("/identificar-por-chave", methods=["POST"])
def identificar_por_chave():
    """Resolve QUAL usuário é dono de uma chave de segurança (YubiKey) pelo
    OTP apresentado - primeiro passo pra uma aplicação consumidora que aceita
    a chave física como login, antes de checar autorização em /autorizar
    (são checagens separadas: esta resolve IDENTIDADE, /autorizar resolve
    PERMISSÃO). Autenticado pela credencial técnica da aplicação, igual ao
    /autorizar - nunca em nome de um usuário."""
    chave_app, aplicacao = _resolver_chave_aplicacao()
    if not aplicacao:
        return jsonify({"erro": "Credencial da aplicação ausente, inválida, revogada ou expirada."}), 401

    data = request.get_json(silent=True) or {}
    yubikey_id = extrair_yubikey_id(data.get("otp_ou_id"))
    if not yubikey_id:
        return jsonify({"identificado": False, "motivo": "chave_invalida"}), 400

    chave = ChaveFisicaUsuario.query.filter_by(yubikey_id=yubikey_id, ativa=True).first()
    if not chave:
        return jsonify({"identificado": False, "motivo": "chave_nao_encontrada"}), 404

    operador = Operadores.query.get(chave.usuario_login)
    if not operador or operador.bloqueado_global:
        return jsonify({"identificado": False, "motivo": "usuario_bloqueado_ou_nao_encontrado"}), 403

    chave.ultimo_uso_em = datetime.utcnow()
    db.session.commit()

    return jsonify({
        "identificado": True,
        "usuario_login": operador.login,
        "usuario": {"login": operador.login, "nome": operador.nome or operador.login},
    }), 200


# ── Administração (cookie + is_admin) ───────────────────────────────────


def _exigir_admin():
    if not current_user.is_authenticated or not current_user.is_admin:
        return jsonify({"erro": "Acesso negado. Somente administradores da HC Overview."}), 403
    return None


@central_bp.route("/aplicacoes", methods=["GET"])
@login_required
def listar_aplicacoes():
    negado = _exigir_admin()
    if negado:
        return negado
    apps = Aplicacao.query.order_by(Aplicacao.nome.asc()).all()
    itens = []
    for app_ in apps:
        item = app_.to_dict()
        item["chaves_ativas"] = ChaveAplicacao.query.filter_by(aplicacao_id=app_.id, ativa=True).count()
        itens.append(item)
    return jsonify(itens)


@central_bp.route("/aplicacoes", methods=["POST"])
@login_required
def criar_aplicacao():
    negado = _exigir_admin()
    if negado:
        return negado
    data = request.get_json(silent=True) or {}
    slug = (data.get("slug") or "").strip().lower()
    nome = (data.get("nome") or "").strip()
    if not slug or not nome:
        return jsonify({"erro": "Informe slug e nome."}), 400
    if not slug.replace("-", "").replace("_", "").isalnum():
        return jsonify({"erro": "Slug deve conter só letras, números, '-' ou '_'."}), 400
    if Aplicacao.query.filter_by(slug=slug).first():
        return jsonify({"erro": "Já existe uma aplicação com esse slug."}), 409

    aplicacao = Aplicacao(
        slug=slug,
        nome=nome,
        descricao=(data.get("descricao") or "").strip() or None,
        perfis_disponiveis=_parse_lista(data.get("perfis_disponiveis")),
        criada_por=current_user.login,
    )
    db.session.add(aplicacao)
    db.session.flush()
    _registrar_auditoria("aplicacao_criada", aplicacao_id=aplicacao.id, descricao=f"Aplicação '{nome}' ({slug}) cadastrada.")
    db.session.commit()
    return jsonify({"mensagem": "Aplicação cadastrada.", "item": aplicacao.to_dict()}), 201


@central_bp.route("/aplicacoes/<int:aplicacao_id>", methods=["PATCH"])
@login_required
def atualizar_aplicacao(aplicacao_id):
    negado = _exigir_admin()
    if negado:
        return negado
    aplicacao = Aplicacao.query.get_or_404(aplicacao_id)
    data = request.get_json(silent=True) or {}

    if "nome" in data:
        nome = (data.get("nome") or "").strip()
        if not nome:
            return jsonify({"erro": "Nome não pode ficar vazio."}), 400
        aplicacao.nome = nome
    if "descricao" in data:
        aplicacao.descricao = (data.get("descricao") or "").strip() or None
    if "perfis_disponiveis" in data:
        aplicacao.perfis_disponiveis = _parse_lista(data.get("perfis_disponiveis"))
    if "ativa" in data:
        aplicacao.ativa = bool(data.get("ativa"))
        _registrar_auditoria(
            "aplicacao_ativada" if aplicacao.ativa else "aplicacao_desativada",
            aplicacao_id=aplicacao.id,
            descricao=f"Aplicação '{aplicacao.nome}' {'ativada' if aplicacao.ativa else 'desativada'}.",
        )

    db.session.commit()
    return jsonify({"mensagem": "Aplicação atualizada.", "item": aplicacao.to_dict()})


@central_bp.route("/aplicacoes/<int:aplicacao_id>", methods=["DELETE"])
@login_required
def excluir_aplicacao(aplicacao_id):
    """Exclui definitivamente a aplicação (ex.: cadastro de teste) e tudo que
    depende dela - chaves técnicas e liberações de usuário. Diferente de
    'Desativar' (reversível, mantém tudo): aqui não tem volta. A auditoria
    registra o nome/slug antes de apagar; como AuditoriaCentral.aplicacao_id
    não tem FK, o histórico continua existindo mesmo depois da exclusão."""
    negado = _exigir_admin()
    if negado:
        return negado
    aplicacao = Aplicacao.query.get_or_404(aplicacao_id)
    nome, slug = aplicacao.nome, aplicacao.slug

    qtd_chaves = ChaveAplicacao.query.filter_by(aplicacao_id=aplicacao.id).delete()
    qtd_acessos = AcessoAplicacao.query.filter_by(aplicacao_id=aplicacao.id).delete()
    _registrar_auditoria(
        "aplicacao_excluida",
        aplicacao_id=aplicacao.id,
        descricao=(
            f"Aplicação '{nome}' ({slug}) excluída - {qtd_chaves} chave(s) e "
            f"{qtd_acessos} liberação(ões) de acesso removidas junto."
        ),
    )
    db.session.delete(aplicacao)
    db.session.commit()
    return jsonify({"mensagem": f"Aplicação '{nome}' excluída."})


@central_bp.route("/aplicacoes/<int:aplicacao_id>/chaves", methods=["GET"])
@login_required
def listar_chaves(aplicacao_id):
    negado = _exigir_admin()
    if negado:
        return negado
    Aplicacao.query.get_or_404(aplicacao_id)
    chaves = ChaveAplicacao.query.filter_by(aplicacao_id=aplicacao_id).order_by(ChaveAplicacao.criada_em.desc()).all()
    return jsonify([c.to_dict() for c in chaves])


@central_bp.route("/aplicacoes/<int:aplicacao_id>/chaves", methods=["POST"])
@login_required
def criar_chave(aplicacao_id):
    negado = _exigir_admin()
    if negado:
        return negado
    aplicacao = Aplicacao.query.get_or_404(aplicacao_id)
    data = request.get_json(silent=True) or {}
    nome = (data.get("nome") or "").strip() or "padrão"
    expira_em = _parse_datahora(data.get("expira_em"))

    chave, segredo = ChaveAplicacao.gerar(aplicacao.id, nome, current_user.login, expira_em)
    db.session.add(chave)
    db.session.flush()
    _registrar_auditoria("chave_criada", aplicacao_id=aplicacao.id, descricao=f"Chave '{nome}' criada para '{aplicacao.nome}'.")
    db.session.commit()

    item = chave.to_dict()
    # O segredo em texto puro só existe nesta resposta - nunca mais é recuperável.
    item["segredo"] = segredo
    return jsonify({
        "mensagem": "Chave criada. Copie o segredo agora - ele não será mostrado de novo.",
        "item": item,
    }), 201


@central_bp.route("/chaves/<int:chave_id>/revogar", methods=["POST"])
@login_required
def revogar_chave(chave_id):
    negado = _exigir_admin()
    if negado:
        return negado
    chave = ChaveAplicacao.query.get_or_404(chave_id)
    chave.ativa = False
    chave.revogada_em = datetime.utcnow()
    chave.revogada_por = current_user.login
    _registrar_auditoria("chave_revogada", aplicacao_id=chave.aplicacao_id, descricao=f"Chave '{chave.nome}' revogada.")
    db.session.commit()
    return jsonify({"mensagem": "Chave revogada."})


@central_bp.route("/usuarios/<login_val>/acessos", methods=["GET"])
@login_required
def listar_acessos_usuario(login_val):
    negado = _exigir_admin()
    if negado:
        return negado
    login_norm = (login_val or "").strip().lower()
    aplicacoes = Aplicacao.query.order_by(Aplicacao.nome.asc()).all()
    acessos = {a.aplicacao_id: a for a in AcessoAplicacao.query.filter_by(usuario_login=login_norm).all()}

    itens = []
    for app_ in aplicacoes:
        acesso = acessos.get(app_.id)
        itens.append({
            "aplicacao": app_.to_dict(),
            "acesso": acesso.to_dict() if acesso else None,
        })
    return jsonify(itens)


@central_bp.route("/usuarios/<login_val>/acessos/<int:aplicacao_id>", methods=["PUT"])
@login_required
def liberar_acesso(login_val, aplicacao_id):
    """Concede ou atualiza a liberação de <login_val> pra aplicacao_id. Upsert:
    se já existe (mesmo revogado), reativa com os novos dados."""
    negado = _exigir_admin()
    if negado:
        return negado
    login_norm = (login_val or "").strip().lower()
    if not Operadores.query.get(login_norm):
        return jsonify({"erro": "Usuário não encontrado em operadores."}), 404
    aplicacao = Aplicacao.query.get_or_404(aplicacao_id)

    data = request.get_json(silent=True) or {}
    perfil = (data.get("perfil") or "").strip() or None
    perfis_validos = aplicacao.lista_perfis()
    if perfil and perfis_validos and perfil not in perfis_validos:
        return jsonify({"erro": f"Perfil inválido pra essa aplicação. Válidos: {', '.join(perfis_validos)}."}), 400

    expira_em = _parse_datahora(data.get("expira_em")) if data.get("expira_em") else None

    acesso = AcessoAplicacao.query.filter_by(usuario_login=login_norm, aplicacao_id=aplicacao.id).first()
    criado = acesso is None
    if criado:
        acesso = AcessoAplicacao(usuario_login=login_norm, aplicacao_id=aplicacao.id)
        db.session.add(acesso)

    acesso.perfil = perfil
    acesso.permissoes = _parse_lista(data.get("permissoes"))
    acesso.expira_em = expira_em
    acesso.status = STATUS_ATIVO
    acesso.concedido_por = current_user.login
    acesso.revogado_por = None
    acesso.revogado_em = None
    if criado:
        acesso.concedido_em = datetime.utcnow()

    _registrar_auditoria(
        "acesso_concedido" if criado else "acesso_atualizado",
        usuario_alvo=login_norm, aplicacao_id=aplicacao.id,
        descricao=f"Acesso a '{aplicacao.nome}' {'concedido' if criado else 'atualizado'} (perfil: {perfil or '-'}).",
    )
    db.session.commit()
    return jsonify({"mensagem": "Acesso liberado.", "item": acesso.to_dict()})


@central_bp.route("/usuarios/<login_val>/acessos/<int:aplicacao_id>/revogar", methods=["POST"])
@login_required
def revogar_acesso(login_val, aplicacao_id):
    negado = _exigir_admin()
    if negado:
        return negado
    login_norm = (login_val or "").strip().lower()
    aplicacao = Aplicacao.query.get_or_404(aplicacao_id)
    acesso = AcessoAplicacao.query.filter_by(usuario_login=login_norm, aplicacao_id=aplicacao.id).first()
    if not acesso:
        return jsonify({"erro": "Esse usuário não tem liberação pra essa aplicação."}), 404

    acesso.status = STATUS_REVOGADO
    acesso.revogado_por = current_user.login
    acesso.revogado_em = datetime.utcnow()
    _registrar_auditoria("acesso_revogado", usuario_alvo=login_norm, aplicacao_id=aplicacao.id, descricao=f"Acesso a '{aplicacao.nome}' revogado.")
    db.session.commit()
    return jsonify({"mensagem": "Acesso revogado.", "item": acesso.to_dict()})


@central_bp.route("/usuarios/<login_val>/bloquear", methods=["POST"])
@login_required
def bloquear_usuario(login_val):
    negado = _exigir_admin()
    if negado:
        return negado
    login_norm = (login_val or "").strip().lower()
    operador = Operadores.query.get(login_norm)
    if not operador:
        return jsonify({"erro": "Usuário não encontrado."}), 404

    data = request.get_json(silent=True) or {}
    bloquear = bool(data.get("bloquear", True))
    if bloquear and login_norm == (current_user.login or "").strip().lower():
        return jsonify({"erro": "Você não pode bloquear a si mesmo."}), 400

    operador.bloqueado_global = bloquear
    operador.bloqueado_em = datetime.utcnow() if bloquear else None
    operador.bloqueado_por = current_user.login if bloquear else None
    _registrar_auditoria(
        "usuario_bloqueado" if bloquear else "usuario_desbloqueado",
        usuario_alvo=login_norm,
        descricao=f"Usuário {'bloqueado' if bloquear else 'desbloqueado'} globalmente (todas as aplicações).",
    )
    db.session.commit()
    return jsonify({"mensagem": "Usuário bloqueado." if bloquear else "Usuário desbloqueado.", "operador": operador.to_dict()})


@central_bp.route("/usuarios/<login_val>/auditoria", methods=["GET"])
@login_required
def auditoria_usuario(login_val):
    negado = _exigir_admin()
    if negado:
        return negado
    login_norm = (login_val or "").strip().lower()
    registros = (
        AuditoriaCentral.query
        .filter_by(usuario_alvo=login_norm)
        .order_by(AuditoriaCentral.timestamp.desc())
        .limit(200)
        .all()
    )
    return jsonify([r.to_dict() for r in registros])


# ── Chaves de segurança (YubiKey) por usuário ───────────────────────────


@central_bp.route("/usuarios/<login_val>/chaves-fisicas", methods=["GET"])
@login_required
def listar_chaves_fisicas(login_val):
    negado = _exigir_admin()
    if negado:
        return negado
    login_norm = (login_val or "").strip().lower()
    chaves = (
        ChaveFisicaUsuario.query
        .filter_by(usuario_login=login_norm)
        .order_by(ChaveFisicaUsuario.cadastrada_em.desc())
        .all()
    )
    return jsonify([c.to_dict() for c in chaves])


@central_bp.route("/usuarios/<login_val>/chaves-fisicas", methods=["POST"])
@login_required
def cadastrar_chave_fisica(login_val):
    """Registra uma chave de segurança JÁ EXISTENTE (YubiKey física) pra este
    usuário - não gera nada, só grava o ID público extraído do OTP informado
    (ver extrair_yubikey_id). É assim que o próprio usuário "se identifica"
    depois: tocando a chave, sem digitar senha."""
    negado = _exigir_admin()
    if negado:
        return negado
    login_norm = (login_val or "").strip().lower()
    if not Operadores.query.get(login_norm):
        return jsonify({"erro": "Usuário não encontrado em operadores."}), 404

    data = request.get_json(silent=True) or {}
    yubikey_id = extrair_yubikey_id(data.get("otp_ou_id"))
    if not yubikey_id:
        return jsonify({"erro": "Toque a chave no campo (ou informe os 12 caracteres do ID) - mínimo 12 caracteres."}), 400

    existente = ChaveFisicaUsuario.query.filter_by(yubikey_id=yubikey_id).first()
    if existente and existente.ativa:
        dono = "este usuário" if existente.usuario_login == login_norm else f"'{existente.usuario_login}'"
        return jsonify({"erro": f"Essa chave já está cadastrada para {dono}."}), 409

    apelido = (data.get("apelido") or "").strip() or None
    if existente and not existente.ativa:
        # Chave existia (revogada) e está sendo redistribuída pra outro dono.
        existente.usuario_login = login_norm
        existente.ativa = True
        existente.apelido = apelido or existente.apelido
        existente.cadastrada_por = current_user.login
        existente.cadastrada_em = datetime.utcnow()
        existente.revogada_em = None
        existente.revogada_por = None
        chave = existente
        criado = False
    else:
        chave = ChaveFisicaUsuario(
            usuario_login=login_norm,
            yubikey_id=yubikey_id,
            apelido=apelido,
            cadastrada_por=current_user.login,
        )
        db.session.add(chave)
        criado = True

    db.session.flush()
    _registrar_auditoria(
        "chave_fisica_cadastrada",
        usuario_alvo=login_norm,
        descricao=f"Chave de segurança (ID {yubikey_id}) {'cadastrada' if criado else 'recadastrada'}.",
    )
    db.session.commit()
    return jsonify({"mensagem": "Chave de segurança cadastrada.", "item": chave.to_dict()}), 201


@central_bp.route("/chaves-fisicas/<int:chave_id>/revogar", methods=["POST"])
@login_required
def revogar_chave_fisica(chave_id):
    negado = _exigir_admin()
    if negado:
        return negado
    chave = ChaveFisicaUsuario.query.get_or_404(chave_id)
    chave.ativa = False
    chave.revogada_em = datetime.utcnow()
    chave.revogada_por = current_user.login
    _registrar_auditoria(
        "chave_fisica_revogada",
        usuario_alvo=chave.usuario_login,
        descricao=f"Chave de segurança (ID {chave.yubikey_id}) revogada.",
    )
    db.session.commit()
    return jsonify({"mensagem": "Chave revogada."})

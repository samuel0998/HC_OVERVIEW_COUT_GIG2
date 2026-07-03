import re

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import func

from models import db
from models.hc_gig2 import HCGig2
from models.operadores import Operadores
from models.turno_config import DEFAULT_TURNO_RESET, HCTurnoConfig, ensure_default_turno_config

auth_bp = Blueprint("auth", __name__)


def _hc_usuario_dict(colab):
    login = (colab.login or "").strip().lower()
    return {
        "login": login,
        "nome": colab.nome_completo or login,
        "setor": colab.area or "",
        "permission_hcview": False,
        "permission_level_hcview": "",
        "origem": "HC",
    }


def _usuarios_operadores_e_hc():
    operadores = Operadores.query.order_by(Operadores.nome.asc()).all()
    usuarios = {op.login.lower(): op.to_dict() for op in operadores if op.login}

    for colab in HCGig2.query.all():
        login = (colab.login or "").strip().lower()
        if login and login not in usuarios:
            usuarios[login] = _hc_usuario_dict(colab)

    return sorted(usuarios.values(), key=lambda item: ((item.get("nome") or "").lower(), item.get("login") or ""))


def _criar_operador_do_hc(login):
    colab = HCGig2.query.filter(func.lower(HCGig2.login) == login.lower()).first()
    if not colab:
        return None

    login_key = login.lower()
    valores_base = {
        "login": login_key,
        "nome": colab.nome_completo or login_key,
        "badge": "",
        "tag": "",
        "setor": colab.area or "",
        "treinamento": colab.status == "Treinamento",
        "permission_labordash": False,
        "permission_dockview": False,
        "permission_level_labordash": None,
        "permission_level_dockview": None,
        "permission_hcview": False,
        "permission_level_hcview": None,
    }

    colunas = db.session.execute(db.text(
        "SELECT column_name, data_type, is_nullable, column_default "
        "FROM information_schema.columns "
        "WHERE table_name = 'operadores'"
    )).mappings().all()

    valores = {}
    for coluna in colunas:
        nome = coluna["column_name"]
        if nome in valores_base:
            valores[nome] = valores_base[nome]
        elif coluna["is_nullable"] == "NO" and not coluna["column_default"]:
            tipo = (coluna["data_type"] or "").lower()
            if "bool" in tipo:
                valores[nome] = False
            elif any(t in tipo for t in ("integer", "numeric", "double", "real")):
                valores[nome] = 0
            else:
                valores[nome] = ""

    def quote_ident(identifier):
        return '"' + identifier.replace('"', '""') + '"'

    colunas_insert = list(valores.keys())
    sql = (
        f"INSERT INTO operadores ({', '.join(quote_ident(c) for c in colunas_insert)}) "
        f"VALUES ({', '.join(':' + c for c in colunas_insert)})"
    )
    db.session.execute(db.text(sql), valores)
    return Operadores.query.get(login_key)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("hc.home"))

    erro = None
    selected_fc = session.get("fc") or current_app.config.get("DEFAULT_FC", "GIG2")

    if request.method == "POST":
        login_val = (request.form.get("login") or "").strip().lower()
        selected_fc = (request.form.get("fc") or selected_fc).strip().upper()

        if selected_fc not in current_app.config["FC_DATABASES"]:
            erro = "FC invalido."
        else:
            session["fc"] = selected_fc
            operador = Operadores.query.filter_by(login=login_val).first()

            if not operador:
                erro = "Login nao encontrado no sistema."
            elif not operador.permission_hcview:
                erro = "Voce nao tem permissao para acessar o HC Overview."
            else:
                login_user(operador)
                next_page = request.args.get("next")
                return redirect(next_page or url_for("hc.home"))

    return render_template(
        "login.html",
        erro=erro,
        fc_options=current_app.config["FC_DATABASES"],
        selected_fc=selected_fc,
    )


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    session.pop("fc", None)
    return redirect(url_for("auth.login"))


@auth_bp.route("/usuarios")
@login_required
def usuarios_page():
    if not current_user.is_admin:
        return redirect(url_for("hc.home"))
    return render_template("usuarios.html")


@auth_bp.route("/api/usuarios", methods=["GET"])
@login_required
def listar_usuarios():
    if not current_user.is_admin:
        return jsonify({"erro": "Acesso negado."}), 403
    return jsonify(_usuarios_operadores_e_hc())


@auth_bp.route("/api/turnos-config", methods=["GET"])
@login_required
def listar_turnos_config():
    if not current_user.is_admin:
        return jsonify({"erro": "Acesso negado."}), 403

    criados = ensure_default_turno_config()
    if criados:
        db.session.commit()

    ordem = {turno: idx for idx, turno in enumerate(DEFAULT_TURNO_RESET)}
    configs = sorted(
        (cfg.to_dict() for cfg in HCTurnoConfig.query.all()),
        key=lambda item: (ordem.get(item["turno"], 99), item["turno"]),
    )
    return jsonify(configs)


@auth_bp.route("/api/turnos-config", methods=["PUT"])
@login_required
def salvar_turnos_config():
    if not current_user.is_admin:
        return jsonify({"erro": "Acesso negado."}), 403

    try:
        data = request.get_json() or {}
        configs = data.get("configs") or []
        if not isinstance(configs, list):
            return jsonify({"erro": "Formato invalido."}), 400

        ensure_default_turno_config()
        turnos_validos = set(DEFAULT_TURNO_RESET)
        for item in configs:
            if not isinstance(item, dict):
                return jsonify({"erro": "Formato invalido."}), 400

            turno = (item.get("turno") or "").strip().upper()
            hora_reset = (item.get("hora_reset") or "").strip()

            if turno not in turnos_validos:
                return jsonify({"erro": f"Turno invalido: {turno}"}), 400
            if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", hora_reset):
                return jsonify({"erro": f"Horario invalido para {turno}."}), 400

            config = HCTurnoConfig.query.get(turno)
            if not config:
                config = HCTurnoConfig(turno=turno, hora_reset=hora_reset)
                db.session.add(config)
            elif config.hora_reset != hora_reset:
                config.hora_reset = hora_reset
                config.last_reset_key = None

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"erro": f"Erro ao salvar horarios: {str(e)}"}), 500

    return jsonify({"mensagem": "Horarios dos turnos atualizados."})


@auth_bp.route("/api/usuarios/<login_val>", methods=["PUT"])
@login_required
def atualizar_permissao(login_val):
    if not current_user.is_admin:
        return jsonify({"erro": "Acesso negado."}), 403

    try:
        login_key = (login_val or "").strip().lower()
        operador = Operadores.query.get(login_key) or _criar_operador_do_hc(login_key)
        if not operador:
            return jsonify({"erro": "Login nao encontrado no HC nem em operadores."}), 404
        data = request.get_json() or {}

        if "permission_hcview" in data:
            if operador.login == current_user.login and not data["permission_hcview"]:
                return jsonify({"erro": "Voce nao pode revogar seu proprio acesso."}), 400
            operador.permission_hcview = bool(data["permission_hcview"])

        if "permission_level_hcview" in data:
            nivel = (data["permission_level_hcview"] or "").strip()
            if nivel not in ("LC1", "LC3", "LC5", "EXPERT", ""):
                return jsonify({"erro": "Nivel invalido."}), 400
            operador.permission_level_hcview = nivel or None

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"erro": f"Erro ao gravar permissao: {str(e)}"}), 500

    return jsonify({"mensagem": "Permissao atualizada.", "operador": operador.to_dict()})

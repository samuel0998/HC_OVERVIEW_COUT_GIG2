from flask import Blueprint, current_app, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import func

from models import db
from models.hc_gig2 import HCGig2
from models.operadores import Operadores

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

    operador = Operadores(
        login=login.lower(),
        nome=colab.nome_completo,
        setor=colab.area,
        treinamento=(colab.status == "Treinamento"),
        permission_hcview=False,
        permission_level_hcview=None,
    )
    db.session.add(operador)
    db.session.flush()
    return operador


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


@auth_bp.route("/api/usuarios/<login_val>", methods=["PUT"])
@login_required
def atualizar_permissao(login_val):
    if not current_user.is_admin:
        return jsonify({"erro": "Acesso negado."}), 403

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
    return jsonify({"mensagem": "Permissao atualizada.", "operador": operador.to_dict()})

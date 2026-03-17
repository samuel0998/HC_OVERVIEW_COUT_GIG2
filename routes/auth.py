from flask import Blueprint, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from models import db
from models.operadores import Operadores

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("hc.home"))

    erro = None
    if request.method == "POST":
        login_val = (request.form.get("login") or "").strip().lower()

        operador = Operadores.query.filter_by(login=login_val).first()

        if not operador:
            erro = "Login não encontrado no sistema."
        elif not operador.permission_hcview:
            erro = "Você não tem permissão para acessar o HC Overview."
        else:
            login_user(operador, remember=True)
            next_page = request.args.get("next")
            return redirect(next_page or url_for("hc.home"))

    return render_template("login.html", erro=erro)


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))


# ── Permission management (admin only) ──────────────────────────


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
    operadores = Operadores.query.order_by(Operadores.nome.asc()).all()
    return jsonify([o.to_dict() for o in operadores])


@auth_bp.route("/api/usuarios/<login_val>", methods=["PUT"])
@login_required
def atualizar_permissao(login_val):
    if not current_user.is_admin:
        return jsonify({"erro": "Acesso negado."}), 403

    operador = Operadores.query.get_or_404(login_val)
    data = request.get_json() or {}

    if "permission_hcview" in data:
        # Prevent admin from revoking their own access
        if operador.login == current_user.login and not data["permission_hcview"]:
            return jsonify({"erro": "Você não pode revogar seu próprio acesso."}), 400
        operador.permission_hcview = bool(data["permission_hcview"])

    if "permission_level_hcview" in data:
        nivel = (data["permission_level_hcview"] or "").strip()
        if nivel not in ("LC1", "LC3", "LC5", "EXPERT", ""):
            return jsonify({"erro": "Nível inválido."}), 400
        operador.permission_level_hcview = nivel or None

    db.session.commit()
    return jsonify({"mensagem": "Permissão atualizada.", "operador": operador.to_dict()})

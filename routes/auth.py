from datetime import datetime

from flask import Blueprint, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from models import db
from models.user_system import UserSystem

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("hc.home"))

    erro = None
    if request.method == "POST":
        login_val = (request.form.get("login") or "").strip().lower()
        senha = (request.form.get("senha") or "").strip()

        usuario = UserSystem.query.filter_by(login=login_val, ativo=True).first()

        if usuario and usuario.check_senha(senha):
            usuario.last_login = datetime.utcnow()
            db.session.commit()
            login_user(usuario, remember=True)
            next_page = request.args.get("next")
            return redirect(next_page or url_for("hc.home"))

        erro = "Login ou senha inválidos."

    return render_template("login.html", erro=erro)


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))


# ── User management (admin only) ──────────────────────────────


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
    usuarios = UserSystem.query.order_by(UserSystem.nome.asc()).all()
    return jsonify([u.to_dict() for u in usuarios])


@auth_bp.route("/api/usuarios", methods=["POST"])
@login_required
def criar_usuario():
    if not current_user.is_admin:
        return jsonify({"erro": "Acesso negado."}), 403

    data = request.get_json() or {}
    login_val = (data.get("login") or "").strip().lower()
    nome = (data.get("nome") or "").strip()
    senha = (data.get("senha") or "").strip()
    nivel = (data.get("nivel_acesso") or "gestor").strip()

    if not login_val or not nome or not senha:
        return jsonify({"erro": "Login, nome e senha são obrigatórios."}), 400

    if UserSystem.query.filter_by(login=login_val).first():
        return jsonify({"erro": "Login já existe."}), 409

    usuario = UserSystem(login=login_val, nome=nome, nivel_acesso=nivel)
    usuario.set_senha(senha)
    db.session.add(usuario)
    db.session.commit()
    return jsonify({"mensagem": "Usuário criado.", "usuario": usuario.to_dict()}), 201


@auth_bp.route("/api/usuarios/<int:user_id>", methods=["PUT"])
@login_required
def atualizar_usuario(user_id):
    if not current_user.is_admin:
        return jsonify({"erro": "Acesso negado."}), 403

    usuario = UserSystem.query.get_or_404(user_id)
    data = request.get_json() or {}

    if "nome" in data:
        usuario.nome = data["nome"].strip()
    if "nivel_acesso" in data:
        usuario.nivel_acesso = data["nivel_acesso"].strip()
    if "ativo" in data:
        if usuario.id == current_user.id and not data["ativo"]:
            return jsonify({"erro": "Você não pode desativar sua própria conta."}), 400
        usuario.ativo = bool(data["ativo"])
    if data.get("nova_senha"):
        usuario.set_senha(data["nova_senha"].strip())

    db.session.commit()
    return jsonify({"mensagem": "Usuário atualizado.", "usuario": usuario.to_dict()})


@auth_bp.route("/api/usuarios/<int:user_id>", methods=["DELETE"])
@login_required
def excluir_usuario(user_id):
    if not current_user.is_admin:
        return jsonify({"erro": "Acesso negado."}), 403
    if user_id == current_user.id:
        return jsonify({"erro": "Você não pode excluir sua própria conta."}), 400

    usuario = UserSystem.query.get_or_404(user_id)
    db.session.delete(usuario)
    db.session.commit()
    return jsonify({"mensagem": "Usuário excluído."})

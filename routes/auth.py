import re

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import func

from models import db
from models.hc_gig2 import HCGig2
from models.operadores import Operadores
from models.turno_config import DEFAULT_TURNO_RESET, HCTurnoConfig, ensure_default_turno_config

auth_bp = Blueprint("auth", __name__)


def _inicializar_fc_sob_demanda(fc):
    fc_data = current_app.config["FC_DATABASES"].get(fc, {})
    if fc_data.get("bootstrap_on_startup", True):
        return None

    # Import tardio para evitar ciclo (app.py importa routes.auth no carregamento).
    # create_all() sozinho so cria tabelas que ainda nao existem — nao adiciona
    # colunas novas em tabelas ja existentes. Instancias sob demanda (ex.: IXD_CNF2)
    # precisam rodar as MESMAS migracoes ALTER TABLE que as demais rodam no boot,
    # senao ficam com o esquema desatualizado e toda consulta quebra (500).
    from app import _create_operational_tables_for_fc, _migrate_hc_table_for_fc, _migrate_lc_table_for_fc

    try:
        _create_operational_tables_for_fc(fc)
        _migrate_hc_table_for_fc(fc)
        _migrate_lc_table_for_fc(fc)
        ensure_default_turno_config()
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Falha ao inicializar a instancia %s", fc)
        return f"Nao foi possivel conectar na instancia {fc_data.get('label', fc)}."

    return None


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
        "permission_level_labordash": "",
        "permission_level_dockview": "",
        "permission_hcview": False,
        "permission_level_hcview": "",
    }

    def quote_ident(identifier):
        return '"' + identifier.replace('"', '""') + '"'

    def valor_padrao_coluna(coluna):
        tipo = (coluna["data_type"] or "").lower()
        if "bool" in tipo:
            return False
        if any(t in tipo for t in ("integer", "numeric", "double", "real")):
            return 0
        return ""

    with db.engines["GIG2"].begin() as conn:
        colunas = conn.execute(db.text(
            "SELECT column_name, data_type, is_nullable, column_default "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'operadores'"
        )).mappings().all()

        if not colunas:
            raise RuntimeError("Tabela operadores nao encontrada no banco GIG2.")

        valores = {}
        for coluna in colunas:
            nome = coluna["column_name"]
            if nome in valores_base:
                valor = valores_base[nome]
                if valor is None and coluna["is_nullable"] == "NO" and not coluna["column_default"]:
                    valor = valor_padrao_coluna(coluna)
                valores[nome] = valor
            elif coluna["is_nullable"] == "NO" and not coluna["column_default"]:
                valores[nome] = valor_padrao_coluna(coluna)

        if "login" not in valores:
            raise RuntimeError("Coluna login nao encontrada na tabela operadores.")

        colunas_insert = list(valores.keys())
        sql = (
            f"INSERT INTO operadores ({', '.join(quote_ident(c) for c in colunas_insert)}) "
            f"VALUES ({', '.join(':' + c for c in colunas_insert)})"
        )
        conn.execute(db.text(sql), valores)

    db.session.expire_all()
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
                erro = _inicializar_fc_sob_demanda(selected_fc)
                if not erro:
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
            from models.operadores import NIVELS_HC
            nivel = (data["permission_level_hcview"] or "").strip()
            if nivel not in (*NIVELS_HC, ""):
                return jsonify({"erro": "Nivel invalido."}), 400
            # LC-HARD-EXPERT: só o login autorizado concede (e não pode rebaixar
            # quem já tem, a não ser o próprio login autorizado).
            mexendo_hard = "LC-HARD-EXPERT" in (nivel, operador.permission_level_hcview or "")
            if mexendo_hard and not current_user.pode_conceder_hard_expert:
                return jsonify({"erro": "Somente o login autorizado (Planning) pode conceder ou remover LC-HARD-EXPERT."}), 403
            operador.permission_level_hcview = nivel or None

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"erro": f"Erro ao gravar permissao: {str(e)}"}), 500

    return jsonify({"mensagem": "Permissao atualizada.", "operador": operador.to_dict()})

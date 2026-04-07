import json
import os
import smtplib
import unicodedata
from datetime import date, timedelta
from email.mime.text import MIMEText
from io import BytesIO

import pandas as pd
from flask import Blueprint, abort, jsonify, render_template, request, send_file
from flask_login import current_user, login_required
from sqlalchemy import or_

from models import db
from models.hc_gig2 import HCGig2

hc_bp = Blueprint("hc", __name__)

CARGOS  = ["Associado", "PIT", "Analista", "Supervisor", "Líder", "Técnico", "Fiscal", "Coordenador", "Gerente"]
AREAS   = ["INBOUND", "OUTBOUND", "ICQA", "INSUMOS", "LEARNING", "LP", "FACILITIES", "RME", "SUPORTE", "C-RET", "TOM", "ADM"]
TURNOS  = ["BLUE DAY", "BLUE NIGHT", "RED DAY", "RED NIGHT", "ADM"]
STATUS  = ["OPERACIONAL", "Licença", "Férias", "Desligado", "OFF"]
RH_EMAIL = "rh_gig2-br@id-logistics.com"
APP_URL  = "https://hcoverviewcoutgig2-production.up.railway.app/atualizar"


# ── Helpers ────────────────────────────────────────────────────


def _parse_date(value):
    from datetime import datetime
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _normalizar(s):
    return unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode("ascii").lower().strip()


def _find_col(df, keyword):
    norm_kw = _normalizar(keyword)
    for col in df.columns:
        if norm_kw in _normalizar(col):
            return col
    return None


def _registrar(tipo, op, descricao, dados_ant=None, dados_nov=None):
    """Log an activity to registro_atividade."""
    from models.registro_atividade import RegistroAtividade
    try:
        u_login = current_user.login if current_user.is_authenticated else "sistema"
        u_nome  = current_user.nome  if current_user.is_authenticated else "Sistema"
    except Exception:
        u_login, u_nome = "sistema", "Sistema"

    reg = RegistroAtividade(
        tipo=tipo,
        operador_id=op.id if op else None,
        operador_login=op.login if op else None,
        operador_nome=op.nome_completo if op else None,
        usuario_login=u_login,
        usuario_nome=u_nome,
        descricao=descricao,
        dados_anteriores=dados_ant,
        dados_novos=dados_nov,
    )
    db.session.add(reg)


def _pendencias_count():
    """Return count of operators with pending dates."""
    return HCGig2.query.filter(
        or_(
            db.and_(HCGig2.status.in_(["Licença", "Férias"]), HCGig2.data_inicio_licenca.is_(None)),
            db.and_(HCGig2.status == "Desligado", HCGig2.data_desligamento.is_(None)),
        )
    ).count()


# ── Page routes ────────────────────────────────────────────────


@hc_bp.route("/")
@login_required
def home():
    count = _pendencias_count()
    return render_template("hc_overview.html", pendencias_count=count)


@hc_bp.route("/novo")
@login_required
def novo_hc():
    if not current_user.can_edit:
        abort(403)
    return render_template("newcolaborator.html", cargos=CARGOS, areas=AREAS, turnos=TURNOS, status_list=STATUS)


@hc_bp.route("/atualizar")
@login_required
def atualizar():
    if not current_user.can_edit:
        abort(403)
    return render_template("atualizar.html", cargos=CARGOS, areas=AREAS, turnos=TURNOS, status_list=STATUS)


@hc_bp.route("/dashboard")
@login_required
def dashboard():
    if not current_user.can_dashboard:
        abort(403)
    return render_template("dashboard_hc.html")


@hc_bp.route("/pendencias")
@login_required
def pendencias_page():
    if not current_user.can_edit:
        abort(403)
    return render_template("pendencias.html")


@hc_bp.route("/historico")
@login_required
def historico_page():
    if not current_user.can_historico:
        abort(403)
    return render_template("historico.html")


# ── API: Colaboradores ─────────────────────────────────────────


@hc_bp.route("/api/hc", methods=["GET"])
@login_required
def listar_colaboradores():
    termo = request.args.get("q", "").strip()
    query = HCGig2.query

    if termo:
        like = f"%{termo}%"
        query = query.filter(
            or_(
                HCGig2.nome_completo.ilike(like),
                HCGig2.login.ilike(like),
                HCGig2.cargo.ilike(like),
                HCGig2.area.ilike(like),
                HCGig2.turno.ilike(like),
                HCGig2.status.ilike(like),
            )
        )

    registros = query.order_by(HCGig2.nome_completo.asc()).all()

    alterou = False
    for r in registros:
        antigo = r.status
        r.aplicar_status_por_data()
        if antigo != r.status:
            alterou = True
    if alterou:
        db.session.commit()

    return jsonify([r.to_dict() for r in registros])


@hc_bp.route("/api/hc", methods=["POST"])
@login_required
def novo_colaborador():
    data = request.get_json() or {}

    login = (data.get("login") or "").strip() or None

    if login:
        existente = HCGig2.query.filter_by(login=login).first()
        if existente:
            return jsonify({"erro": "Já existe colaborador com esse login."}), 409

    colaborador = HCGig2(
        nome_completo=(data.get("nome_completo") or "").strip(),
        login=login,
        cargo=(data.get("cargo") or "").strip(),
        area=(data.get("area") or "").strip() or None,
        turno=(data.get("turno") or "").strip() or None,
        status="OPERACIONAL",
    )

    if not colaborador.nome_completo or not colaborador.cargo:
        return jsonify({"erro": "Nome e cargo são obrigatórios."}), 400

    db.session.add(colaborador)
    db.session.flush()  # get id before commit

    _registrar(
        "adicao",
        colaborador,
        f"Novo colaborador cadastrado: {colaborador.nome_completo} ({colaborador.cargo})",
        dados_nov=json.dumps({
            "nome_completo": colaborador.nome_completo,
            "login": colaborador.login or "",
            "cargo": colaborador.cargo,
            "area": colaborador.area or "",
            "turno": colaborador.turno or "",
        }),
    )

    db.session.commit()
    return jsonify({"mensagem": "Colaborador cadastrado com sucesso.", "item": colaborador.to_dict()}), 201


@hc_bp.route("/api/hc/<int:item_id>", methods=["PUT"])
@login_required
def atualizar_colaborador(item_id):
    colaborador = HCGig2.query.get_or_404(item_id)
    data = request.get_json() or {}

    dados_ant = json.dumps({
        "nome_completo": colaborador.nome_completo,
        "login": colaborador.login or "",
        "cargo": colaborador.cargo,
        "area": colaborador.area or "",
        "turno": colaborador.turno or "",
        "status": colaborador.status,
        "causa_afastamento": colaborador.causa_afastamento or "",
    })

    novo_login = (data.get("login") or "").strip() or None
    if novo_login and novo_login != colaborador.login:
        existe_login = HCGig2.query.filter(HCGig2.login == novo_login, HCGig2.id != item_id).first()
        if existe_login:
            return jsonify({"erro": "Já existe outro colaborador com esse login."}), 409

    novo_status = (data.get("status") or colaborador.status).strip()

    if novo_status in ("Licença", "Férias"):
        descricao = (data.get("causa_afastamento") or "").strip()
        if not descricao:
            return jsonify({"erro": f"Descrição é obrigatória para status '{novo_status}'."}), 400

    if novo_status == "Desligado":
        descricao = (data.get("causa_afastamento") or "").strip()
        if not descricao:
            return jsonify({"erro": "Descrição é obrigatória para Desligamento."}), 400

    status_anterior = colaborador.status
    colaborador.nome_completo = (data.get("nome_completo") or colaborador.nome_completo).strip()
    colaborador.login         = novo_login if novo_login else colaborador.login
    colaborador.cargo         = (data.get("cargo") or colaborador.cargo).strip()
    colaborador.area          = (data.get("area") or "").strip() or None
    colaborador.turno         = (data.get("turno") or "").strip() or None
    colaborador.status        = novo_status
    colaborador.causa_afastamento = (data.get("causa_afastamento") or "").strip() or None

    if novo_status in ("Licença", "Férias"):
        colaborador.data_inicio_licenca = _parse_date(data.get("data_inicio_licenca"))
        colaborador.data_fim_licenca    = _parse_date(data.get("data_fim_licenca"))
        colaborador.data_desligamento   = None
    elif novo_status == "Desligado":
        colaborador.data_desligamento   = _parse_date(data.get("data_desligamento"))
        colaborador.data_inicio_licenca = None
        colaborador.data_fim_licenca    = None
    else:
        colaborador.data_inicio_licenca = None
        colaborador.data_fim_licenca    = None
        colaborador.data_desligamento   = None

    dados_nov = json.dumps({
        "nome_completo": colaborador.nome_completo,
        "login": colaborador.login or "",
        "cargo": colaborador.cargo,
        "area": colaborador.area or "",
        "turno": colaborador.turno or "",
        "status": colaborador.status,
        "causa_afastamento": colaborador.causa_afastamento or "",
    })

    tipo = "edicao_status" if status_anterior != novo_status else "edicao"
    msg_status = f" (status: {status_anterior} → {novo_status})" if status_anterior != novo_status else ""
    _registrar(
        tipo,
        colaborador,
        f"Colaborador atualizado: {colaborador.nome_completo}{msg_status}",
        dados_ant=dados_ant,
        dados_nov=dados_nov,
    )

    db.session.commit()
    return jsonify({"mensagem": "Colaborador atualizado com sucesso.", "item": colaborador.to_dict()})


@hc_bp.route("/api/hc/<int:item_id>", methods=["DELETE"])
@login_required
def excluir_colaborador(item_id):
    if not current_user.can_delete:
        return jsonify({"erro": "Sem permissão para excluir colaboradores."}), 403
    colaborador = HCGig2.query.get_or_404(item_id)
    nome = colaborador.nome_completo

    # If terminated, archive before deleting
    if colaborador.status == "Desligado":
        from models.historico import HistoricoOperacional
        try:
            u_login = current_user.login if current_user.is_authenticated else "sistema"
        except Exception:
            u_login = "sistema"

        hist = HistoricoOperacional(
            hc_id_original=colaborador.id,
            nome_completo=colaborador.nome_completo,
            login=colaborador.login,
            cargo=colaborador.cargo,
            area=colaborador.area,
            turno=colaborador.turno,
            status_final=colaborador.status,
            data_desligamento=colaborador.data_desligamento,
            data_inicio_licenca=colaborador.data_inicio_licenca,
            data_fim_licenca=colaborador.data_fim_licenca,
            causa=colaborador.causa_afastamento,
            data_criacao_original=colaborador.created_at,
            arquivado_por=u_login,
        )
        db.session.add(hist)

    _registrar(
        "exclusao",
        colaborador,
        f"Colaborador removido: {colaborador.nome_completo} ({colaborador.cargo} | {colaborador.status})",
        dados_ant=json.dumps(colaborador.to_dict()),
    )

    db.session.delete(colaborador)
    db.session.commit()
    return jsonify({"mensagem": f"Colaborador '{nome}' excluído com sucesso."})


# ── API: Pendências ────────────────────────────────────────────


@hc_bp.route("/api/hc/pendencias", methods=["GET"])
@login_required
def listar_pendencias():
    hoje = date.today()
    weekday = hoje.weekday()

    # Next Tuesday (or today if Tuesday)
    if weekday <= 1:
        days_to_tuesday = 1 - weekday
    else:
        days_to_tuesday = 8 - weekday
    proxima_terca = hoje + timedelta(days=days_to_tuesday)
    prazo_vencido = weekday > 1

    pendentes = HCGig2.query.filter(
        or_(
            db.and_(HCGig2.status.in_(["Licença", "Férias"]), HCGig2.data_inicio_licenca.is_(None)),
            db.and_(HCGig2.status == "Desligado", HCGig2.data_desligamento.is_(None)),
        )
    ).order_by(HCGig2.nome_completo.asc()).all()

    return jsonify({
        "pendencias": [p.to_dict() for p in pendentes],
        "total": len(pendentes),
        "prazo": proxima_terca.strftime("%d/%m/%Y"),
        "prazo_vencido": prazo_vencido,
    })


# ── API: Histórico ─────────────────────────────────────────────


@hc_bp.route("/api/hc/historico", methods=["GET"])
@login_required
def listar_historico():
    from models.registro_atividade import RegistroAtividade
    limite = int(request.args.get("limite", 200))
    tipo = request.args.get("tipo", "").strip()

    query = RegistroAtividade.query
    if tipo:
        query = query.filter(RegistroAtividade.tipo == tipo)
    registros = query.order_by(RegistroAtividade.timestamp.desc()).limit(limite).all()
    return jsonify([r.to_dict() for r in registros])


@hc_bp.route("/api/hc/historico-operacional", methods=["GET"])
@login_required
def listar_historico_operacional():
    from models.historico import HistoricoOperacional
    registros = HistoricoOperacional.query.order_by(HistoricoOperacional.data_arquivo.desc()).all()
    return jsonify([r.to_dict() for r in registros])


# ── API: Admin – trigger status processing ────────────────────


@hc_bp.route("/api/admin/processar-status", methods=["POST"])
@login_required
def trigger_processar_status():
    if not current_user.is_admin:
        return jsonify({"erro": "Acesso negado."}), 403
    from app import processar_status_automatico
    try:
        processar_status_automatico()
        return jsonify({"mensagem": "Processamento concluído."})
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


# ── API: Email ────────────────────────────────────────────────


@hc_bp.route("/api/hc/<int:item_id>/pedir-data-desligamento", methods=["POST"])
@login_required
def pedir_data_desligamento(item_id):
    colaborador = HCGig2.query.get_or_404(item_id)
    nome = colaborador.nome_completo

    corpo = (
        f"Olá equipe de RH,\n\n"
        f"Solicito uma previsão de data para o desligamento do colaborador {nome}.\n\n"
        f"Você pode adicionar a data sugerida no link: {APP_URL}\n\n"
        f"Att"
    )

    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASS", "")

    if not smtp_user or not smtp_pass:
        import urllib.parse
        assunto  = urllib.parse.quote(f"Previsão de data de desligamento – {nome}")
        corpo_q  = urllib.parse.quote(corpo)
        mailto   = f"mailto:{RH_EMAIL}?subject={assunto}&body={corpo_q}"
        return jsonify({"mailto": mailto, "aviso": "SMTP não configurado — use o link mailto."}), 202

    try:
        msg = MIMEText(corpo, "plain", "utf-8")
        msg["Subject"] = f"Previsão de data de desligamento – {nome}"
        msg["From"]    = smtp_user
        msg["To"]      = RH_EMAIL

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, [RH_EMAIL], msg.as_string())

        return jsonify({"mensagem": f"E-mail enviado para {RH_EMAIL} com sucesso."})
    except Exception as e:
        return jsonify({"erro": f"Falha ao enviar e-mail: {str(e)}"}), 500


# ── API: Import / Export ───────────────────────────────────────


@hc_bp.route("/api/hc/import-csv", methods=["POST"])
@login_required
def importar_csv():
    arquivo = request.files.get("arquivo")
    if not arquivo:
        return jsonify({"erro": "Envie um arquivo CSV."}), 400

    try:
        df = pd.read_csv(arquivo, encoding="utf-8-sig", dtype=str)
    except Exception:
        try:
            arquivo.seek(0)
            df = pd.read_csv(arquivo, encoding="latin-1", dtype=str)
        except Exception as e:
            return jsonify({"erro": f"Erro ao ler CSV: {str(e)}"}), 400

    col_nome = _find_col(df, "nome")
    col_login = _find_col(df, "login")
    col_cargo = _find_col(df, "cargo")
    col_area = _find_col(df, "area")
    col_turno = _find_col(df, "turno")
    col_previsao = _find_col(df, "previsao") or _find_col(df, "previs")
    col_descricao = _find_col(df, "descri")
    col_status_lib = _find_col(df, "libera")
    col_status = None
    for c in df.columns:
        norm = _normalizar(c)
        if norm == "status":
            col_status = c
            break
    if not col_status:
        col_status = _find_col(df, "status")

    if not col_nome:
        return jsonify({"erro": "Coluna 'Nome Completo' não encontrada no CSV."}), 400

    STATUS_MAP = {
        "operacional": "OPERACIONAL",
        "off": "OFF",
        "licenca": "Licença",
        "licença": "Licença",
    }

    # Apaga todos os colaboradores existentes antes de inserir os novos
    HCGig2.query.delete()

    inseridos = 0
    erros = []
    logins_vistos = set()

    for idx, row in df.iterrows():
        try:
            nome = str(row.get(col_nome, "")).strip() if col_nome else ""
            if not nome or nome.lower() == "nan":
                continue

            login = str(row.get(col_login, "")).strip() if col_login else ""
            login = None if login.lower() in ("nan", "none", "") else login

            # Se login duplicado no CSV, sobe o colaborador sem login para não violar unique constraint
            if login and login in logins_vistos:
                erros.append(f"⚠️ Linha {idx + 2}: login '{login}' duplicado no CSV — '{nome}' foi inserido SEM login. Corrija manualmente.")
                login = None
            elif login:
                logins_vistos.add(login)

            cargo = str(row.get(col_cargo, "")).strip() if col_cargo else ""
            cargo = "" if cargo.lower() == "nan" else cargo

            area = str(row.get(col_area, "")).strip() if col_area else ""
            area = None if area.lower() in ("nan", "none", "") else area

            turno = str(row.get(col_turno, "")).strip() if col_turno else ""
            turno = None if turno.lower() in ("nan", "none", "") else turno

            raw_status = str(row.get(col_status, "operacional")).strip() if col_status else "operacional"
            status = STATUS_MAP.get(_normalizar(raw_status), "OPERACIONAL")

            previsao_raw = str(row.get(col_previsao, "não")).strip() if col_previsao else "não"
            previsao = _normalizar(previsao_raw) in ("sim", "true", "1", "yes")

            causa = str(row.get(col_descricao, "")).strip() if col_descricao else ""
            causa = None if causa.lower() in ("nan", "none", "") else causa or None

            status_lib = str(row.get(col_status_lib, "")).strip() if col_status_lib else ""
            status_lib = None if status_lib.lower() in ("nan", "none", "") else status_lib or None

            item = HCGig2()
            db.session.add(item)
            inseridos += 1

            item.nome_completo = nome
            item.login = login
            item.cargo = cargo or ""
            item.area = area
            item.turno = turno
            item.status = status
            item.previsao_afastamento = previsao
            item.causa_afastamento = causa
            item.status_liberacao = status_lib
            item.aplicar_status_por_data()

        except Exception as e:
            erros.append(f"Linha {idx + 2}: {str(e)}")

    db.session.commit()
    result = {"mensagem": "Base renovada com sucesso.", "inseridos": inseridos}
    if erros:
        result["erros"] = erros
    return jsonify(result)


@hc_bp.route("/api/hc/import", methods=["POST"])
@login_required
def importar_excel():
    arquivo = request.files.get("arquivo")
    if not arquivo:
        return jsonify({"erro": "Envie um arquivo Excel."}), 400

    df = pd.read_excel(arquivo)
    colunas_esperadas = ["nome_completo", "login", "cargo", "area", "turno", "status",
                         "previsao_afastamento", "data_afastamento", "causa_afastamento"]

    normalizadas = {c.lower().strip(): c for c in df.columns}
    faltando = [c for c in colunas_esperadas if c not in normalizadas]
    if faltando:
        return jsonify({"erro": f"Colunas ausentes: {', '.join(faltando)}"}), 400

    inseridos = 0
    atualizados = 0

    for _, row in df.iterrows():
        login = str(row[normalizadas["login"]]).strip()
        if not login or login.lower() == "nan":
            login = None

        data_afastamento = None
        raw_date = row[normalizadas["data_afastamento"]]
        if pd.notna(raw_date):
            if isinstance(raw_date, pd.Timestamp):
                data_afastamento = raw_date.date()
            else:
                try:
                    data_afastamento = pd.to_datetime(raw_date).date()
                except Exception:
                    data_afastamento = None

        previsao = row[normalizadas["previsao_afastamento"]]
        previsao_bool = str(previsao).strip().lower() in ["true", "1", "sim", "yes"]

        item = HCGig2.query.filter_by(login=login).first() if login else None
        if not item:
            item = HCGig2(login=login)
            db.session.add(item)
            inseridos += 1
        else:
            atualizados += 1

        item.nome_completo = str(row[normalizadas["nome_completo"]]).strip()
        item.cargo = str(row[normalizadas["cargo"]]).strip()
        item.area = str(row[normalizadas["area"]]).strip() or None
        item.turno = str(row[normalizadas["turno"]]).strip() or None
        item.status = str(row[normalizadas["status"]]).strip() or "OPERACIONAL"
        item.previsao_afastamento = previsao_bool
        item.data_afastamento = data_afastamento
        causa = row[normalizadas["causa_afastamento"]]
        item.causa_afastamento = None if pd.isna(causa) else str(causa).strip()
        item.aplicar_status_por_data()

    db.session.commit()
    return jsonify({"mensagem": "Importação concluída.", "inseridos": inseridos, "atualizados": atualizados})


@hc_bp.route("/api/hc/export", methods=["GET"])
@login_required
def exportar_excel():
    registros = HCGig2.query.order_by(HCGig2.nome_completo.asc()).all()

    dados = []
    for r in registros:
        d = r.to_dict()
        dados.append({
            "ID": d["id"],
            "Nome Completo": d["nome_completo"],
            "Login": d["login"],
            "Cargo": d["cargo"],
            "Area": d["area"],
            "Turno": d["turno"],
            "Status": d["status"],
            "Status Liberação": d["status_liberacao"],
            "Previsão Afastamento": "SIM" if d["previsao_afastamento"] else "NÃO",
            "Data Afastamento": d["data_afastamento"] or "",
            "Descrição": d["causa_afastamento"] or "",
            "Criado em": d["created_at"] or "",
            "Atualizado em": d["updated_at"] or "",
        })

    df = pd.DataFrame(dados)

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="HC_GIG2")
    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name="hc_gig2.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ── API: Dashboard ─────────────────────────────────────────────


@hc_bp.route("/api/hc/dashboard", methods=["GET"])
@login_required
def dashboard_data():
    f_area   = request.args.get("area", "").strip()
    f_turno  = request.args.get("turno", "").strip()
    f_status = request.args.get("status", "").strip()

    todos = HCGig2.query.all()
    for r in todos:
        r.aplicar_status_por_data()
    db.session.commit()

    registros = todos
    if f_area:
        registros = [r for r in registros if (r.area or "") == f_area]
    if f_turno:
        registros = [r for r in registros if (r.turno or "") == f_turno]
    if f_status:
        registros = [r for r in registros if r.status == f_status]

    total      = len(registros)
    operacional = sum(1 for r in registros if r.status == "OPERACIONAL")
    off        = sum(1 for r in registros if r.status == "OFF")
    licenca    = sum(1 for r in registros if r.status == "Licença")
    ferias     = sum(1 for r in registros if r.status == "Férias")

    outbound_areas = {"OUTBOUND", "INSUMOS", "LP"}
    inbound_areas  = {"INBOUND", "C-RET"}
    icqa_areas     = {"ICQA"}

    por_area  = {}
    por_cargo = {}
    por_turno = {}

    for r in registros:
        por_area[r.area or "—"]   = por_area.get(r.area or "—", 0) + 1
        por_cargo[r.cargo]        = por_cargo.get(r.cargo, 0) + 1
        por_turno[r.turno or "—"] = por_turno.get(r.turno or "—", 0) + 1

    por_area  = dict(sorted(por_area.items(),  key=lambda x: x[1], reverse=True))
    por_cargo = dict(sorted(por_cargo.items(), key=lambda x: x[1], reverse=True))

    pct_outbound = round((sum(v for k, v in por_area.items() if k in outbound_areas) / total) * 100, 1) if total else 0
    pct_inbound  = round((sum(v for k, v in por_area.items() if k in inbound_areas)  / total) * 100, 1) if total else 0
    pct_icqa     = round((sum(v for k, v in por_area.items() if k in icqa_areas)     / total) * 100, 1) if total else 0

    associados_e_pits = {}
    for turno in TURNOS:
        associados_e_pits[turno] = {
            "Associado": sum(1 for r in registros if r.turno == turno and r.cargo == "Associado"),
            "PIT":       sum(1 for r in registros if r.turno == turno and r.cargo == "PIT"),
        }

    operacional_por_turno = {}
    for turno in TURNOS:
        if turno == "ADM":
            continue
        operacional_por_turno[turno] = {
            "Analista":  sum(1 for r in registros if r.turno == turno and r.cargo == "Analista"  and r.status == "OPERACIONAL"),
            "Associado": sum(1 for r in registros if r.turno == turno and r.cargo == "Associado" and r.status == "OPERACIONAL"),
            "PIT":       sum(1 for r in registros if r.turno == turno and r.cargo == "PIT"       and r.status == "OPERACIONAL"),
        }

    areas_disponiveis  = sorted({r.area  or "" for r in todos if r.area})
    turnos_disponiveis = sorted({r.turno or "" for r in todos if r.turno})
    status_disponiveis = sorted({r.status for r in todos})

    return jsonify({
        "cards": {
            "hc_total": total,
            "hc_operacional": operacional,
            "pct_outbound": pct_outbound,
            "pct_inbound":  pct_inbound,
            "pct_icqa":     pct_icqa,
        },
        "por_area":  por_area,
        "por_cargo": por_cargo,
        "por_turno": por_turno,
        "status": {"OPERACIONAL": operacional, "Licença": licenca, "Férias": ferias, "OFF": off},
        "associados_e_pits": associados_e_pits,
        "operacional_por_turno": operacional_por_turno,
        "filtros_disponiveis": {
            "areas":  areas_disponiveis,
            "turnos": turnos_disponiveis,
            "status": status_disponiveis,
        },
        "filtros_ativos": {"area": f_area, "turno": f_turno, "status": f_status},
    })

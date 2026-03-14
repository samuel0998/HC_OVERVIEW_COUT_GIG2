from io import BytesIO
from datetime import datetime

import pandas as pd
from flask import Blueprint, jsonify, render_template, request, send_file
from sqlalchemy import or_

from models import db
from models.hc_gig2 import HCGig2

hc_bp = Blueprint("hc", __name__)

CARGOS = ["Associado", "PIT", "Analista", "Supervisor", "Líder", "Técnico", "Fiscal", "Coordenador", "Gerente"]
AREAS = ["INBOUND", "OUTBOUND", "ICQA", "INSUMOS", "LEARNING", "LP", "FACILITIES", "RME", "SUPORTE", "C-RET", "ADM"]
TURNOS = ["BLUE DAY", "BLUE NIGHT", "RED DAY", "RED NIGHT", "ADM"]
STATUS = ["OPERACIONAL", "OFF"]


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


@hc_bp.route("/")
def home():
    return render_template("hc_overview.html", cargos=CARGOS, areas=AREAS, turnos=TURNOS, status_list=STATUS)


@hc_bp.route("/dashboard")
def dashboard():
    return render_template("dashboard_hc.html")


@hc_bp.route("/api/hc", methods=["GET"])
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
def novo_colaborador():
    data = request.get_json() or {}

    login = (data.get("login") or "").strip()
    if not login:
        return jsonify({"erro": "Login é obrigatório."}), 400

    existente = HCGig2.query.filter_by(login=login).first()
    if existente:
        return jsonify({"erro": "Já existe colaborador com esse login."}), 409

    colaborador = HCGig2(
        nome_completo=(data.get("nome_completo") or "").strip(),
        login=login,
        cargo=(data.get("cargo") or "").strip(),
        area=(data.get("area") or "").strip(),
        turno=(data.get("turno") or "").strip(),
        status=(data.get("status") or "OPERACIONAL").strip(),
        previsao_afastamento=bool(data.get("previsao_afastamento")),
        data_afastamento=_parse_date(data.get("data_afastamento")),
        causa_afastamento=(data.get("causa_afastamento") or "").strip() or None,
    )
    colaborador.aplicar_status_por_data()

    campos_obrigatorios = [colaborador.nome_completo, colaborador.cargo, colaborador.area, colaborador.turno]
    if not all(campos_obrigatorios):
        return jsonify({"erro": "Nome, cargo, área e turno são obrigatórios."}), 400

    db.session.add(colaborador)
    db.session.commit()
    return jsonify({"mensagem": "Colaborador cadastrado com sucesso.", "item": colaborador.to_dict()}), 201


@hc_bp.route("/api/hc/<int:item_id>", methods=["PUT"])
def atualizar_colaborador(item_id):
    colaborador = HCGig2.query.get_or_404(item_id)
    data = request.get_json() or {}

    novo_login = (data.get("login") or colaborador.login).strip()
    existe_login = HCGig2.query.filter(HCGig2.login == novo_login, HCGig2.id != item_id).first()
    if existe_login:
        return jsonify({"erro": "Já existe outro colaborador com esse login."}), 409

    colaborador.nome_completo = (data.get("nome_completo") or colaborador.nome_completo).strip()
    colaborador.login = novo_login
    colaborador.cargo = (data.get("cargo") or colaborador.cargo).strip()
    colaborador.area = (data.get("area") or colaborador.area).strip()
    colaborador.turno = (data.get("turno") or colaborador.turno).strip()
    colaborador.status = (data.get("status") or colaborador.status).strip()
    colaborador.previsao_afastamento = bool(data.get("previsao_afastamento"))
    colaborador.data_afastamento = _parse_date(data.get("data_afastamento"))
    colaborador.causa_afastamento = (data.get("causa_afastamento") or "").strip() or None
    colaborador.aplicar_status_por_data()

    db.session.commit()
    return jsonify({"mensagem": "Colaborador atualizado com sucesso.", "item": colaborador.to_dict()})


@hc_bp.route("/api/hc/import", methods=["POST"])
def importar_excel():
    arquivo = request.files.get("arquivo")
    if not arquivo:
        return jsonify({"erro": "Envie um arquivo Excel."}), 400

    df = pd.read_excel(arquivo)
    colunas_esperadas = [
        "nome_completo",
        "login",
        "cargo",
        "area",
        "turno",
        "status",
        "previsao_afastamento",
        "data_afastamento",
        "causa_afastamento",
    ]

    normalizadas = {c.lower().strip(): c for c in df.columns}
    faltando = [c for c in colunas_esperadas if c not in normalizadas]
    if faltando:
        return jsonify({"erro": f"Colunas ausentes: {', '.join(faltando)}"}), 400

    inseridos = 0
    atualizados = 0

    for _, row in df.iterrows():
        login = str(row[normalizadas["login"]]).strip()
        if not login or login.lower() == "nan":
            continue

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

        item = HCGig2.query.filter_by(login=login).first()
        if not item:
            item = HCGig2(login=login)
            db.session.add(item)
            inseridos += 1
        else:
            atualizados += 1

        item.nome_completo = str(row[normalizadas["nome_completo"]]).strip()
        item.cargo = str(row[normalizadas["cargo"]]).strip()
        item.area = str(row[normalizadas["area"]]).strip()
        item.turno = str(row[normalizadas["turno"]]).strip()
        item.status = str(row[normalizadas["status"]]).strip() or "OPERACIONAL"
        item.previsao_afastamento = previsao_bool
        item.data_afastamento = data_afastamento
        causa = row[normalizadas["causa_afastamento"]]
        item.causa_afastamento = None if pd.isna(causa) else str(causa).strip()
        item.aplicar_status_por_data()

    db.session.commit()
    return jsonify({"mensagem": "Importação concluída.", "inseridos": inseridos, "atualizados": atualizados})


@hc_bp.route("/api/hc/export", methods=["GET"])
def exportar_excel():
    registros = HCGig2.query.order_by(HCGig2.nome_completo.asc()).all()
    dados = [r.to_dict() for r in registros]
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


@hc_bp.route("/api/hc/dashboard", methods=["GET"])
def dashboard_data():
    registros = HCGig2.query.all()

    for r in registros:
        r.aplicar_status_por_data()
    db.session.commit()

    total = len(registros)
    operacional = sum(1 for r in registros if r.status == "OPERACIONAL")
    off = sum(1 for r in registros if r.status == "OFF")

    outbound_areas = {"OUTBOUND", "INSUMOS", "LP"}
    inbound_areas = {"INBOUND", "C-RET"}
    icqa_areas = {"ICQA"}

    por_area = {}
    por_cargo = {}
    por_turno = {}
    status_data = {"OPERACIONAL": operacional, "OFF": off}

    for r in registros:
        por_area[r.area] = por_area.get(r.area, 0) + 1
        por_cargo[r.cargo] = por_cargo.get(r.cargo, 0) + 1
        por_turno[r.turno] = por_turno.get(r.turno, 0) + 1

    pct_outbound = round((sum(v for k, v in por_area.items() if k in outbound_areas) / total) * 100, 1) if total else 0
    pct_inbound = round((sum(v for k, v in por_area.items() if k in inbound_areas) / total) * 100, 1) if total else 0
    pct_icqa = round((sum(v for k, v in por_area.items() if k in icqa_areas) / total) * 100, 1) if total else 0

    associados_e_pits = {}
    for turno in TURNOS:
        associados_e_pits[turno] = {
            "Associado": sum(1 for r in registros if r.turno == turno and r.cargo == "Associado"),
            "PIT": sum(1 for r in registros if r.turno == turno and r.cargo == "PIT"),
        }

    return jsonify(
        {
            "cards": {
                "hc_total": total,
                "hc_operacional": operacional,
                "pct_outbound": pct_outbound,
                "pct_inbound": pct_inbound,
                "pct_icqa": pct_icqa,
            },
            "por_area": por_area,
            "por_cargo": por_cargo,
            "por_turno": por_turno,
            "status": status_data,
            "associados_e_pits": associados_e_pits,
        }
    )

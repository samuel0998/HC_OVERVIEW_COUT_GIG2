import os
import smtplib
import unicodedata
from email.mime.text import MIMEText
from io import BytesIO
from datetime import datetime

import pandas as pd
from flask import Blueprint, jsonify, render_template, request, send_file
from sqlalchemy import or_

from models import db
from models.hc_gig2 import HCGig2

hc_bp = Blueprint("hc", __name__)

CARGOS  = ["Associado", "PIT", "Analista", "Supervisor", "Líder", "Técnico", "Fiscal", "Coordenador", "Gerente"]
AREAS   = ["INBOUND", "OUTBOUND", "ICQA", "INSUMOS", "LEARNING", "LP", "FACILITIES", "RME", "SUPORTE", "C-RET", "TOM", "ADM"]
TURNOS  = ["BLUE DAY", "BLUE NIGHT", "RED DAY", "RED NIGHT", "ADM"]
STATUS  = ["OPERACIONAL", "Licença", "Férias", "Desligado"]
RH_EMAIL = "rh_gig2-br@id-logistics.com"
APP_URL  = "https://hcoverviewcoutgig2-production.up.railway.app/atualizar"


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _normalizar(s):
    """Remove acentos e deixa em minúsculo para comparação de colunas."""
    return unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode("ascii").lower().strip()


def _find_col(df, keyword):
    """Encontra coluna no DataFrame pelo keyword normalizado."""
    norm_kw = _normalizar(keyword)
    for col in df.columns:
        if norm_kw in _normalizar(col):
            return col
    return None


@hc_bp.route("/")
def home():
    return render_template("hc_overview.html")


@hc_bp.route("/novo")
def novo_hc():
    return render_template("newcolaborator.html", cargos=CARGOS, areas=AREAS, turnos=TURNOS, status_list=STATUS)


@hc_bp.route("/atualizar")
def atualizar():
    return render_template("atualizar.html", cargos=CARGOS, areas=AREAS, turnos=TURNOS, status_list=STATUS)





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
    db.session.commit()
    return jsonify({"mensagem": "Colaborador cadastrado com sucesso.", "item": colaborador.to_dict()}), 201


@hc_bp.route("/api/hc/<int:item_id>", methods=["PUT"])
def atualizar_colaborador(item_id):
    colaborador = HCGig2.query.get_or_404(item_id)
    data = request.get_json() or {}

    novo_login = (data.get("login") or "").strip() or None
    if novo_login and novo_login != colaborador.login:
        existe_login = HCGig2.query.filter(HCGig2.login == novo_login, HCGig2.id != item_id).first()
        if existe_login:
            return jsonify({"erro": "Já existe outro colaborador com esse login."}), 409

    novo_status = (data.get("status") or colaborador.status).strip()

    # Validações por status
    if novo_status in ("Licença", "Férias"):
        descricao = (data.get("causa_afastamento") or "").strip()
        if not descricao:
            return jsonify({"erro": f"Descrição é obrigatória para status '{novo_status}'."}), 400

    if novo_status == "Desligado":
        descricao = (data.get("causa_afastamento") or "").strip()
        if not descricao:
            return jsonify({"erro": "Descrição é obrigatória para Desligamento."}), 400

    colaborador.nome_completo = (data.get("nome_completo") or colaborador.nome_completo).strip()
    colaborador.login         = novo_login if novo_login else colaborador.login
    colaborador.cargo         = (data.get("cargo") or colaborador.cargo).strip()
    colaborador.area          = (data.get("area") or "").strip() or None
    colaborador.turno         = (data.get("turno") or "").strip() or None
    colaborador.status        = novo_status
    colaborador.causa_afastamento = (data.get("causa_afastamento") or "").strip() or None

    # Campos específicos por status
    if novo_status in ("Licença", "Férias"):
        colaborador.data_inicio_licenca = _parse_date(data.get("data_inicio_licenca"))
        colaborador.data_fim_licenca    = _parse_date(data.get("data_fim_licenca"))
        colaborador.data_desligamento   = None
    elif novo_status == "Desligado":
        colaborador.data_desligamento   = _parse_date(data.get("data_desligamento"))
        colaborador.data_inicio_licenca = None
        colaborador.data_fim_licenca    = None
    else:  # OPERACIONAL
        colaborador.data_inicio_licenca = None
        colaborador.data_fim_licenca    = None
        colaborador.data_desligamento   = None

    db.session.commit()
    return jsonify({"mensagem": "Colaborador atualizado com sucesso.", "item": colaborador.to_dict()})


@hc_bp.route("/api/hc/<int:item_id>", methods=["DELETE"])
def excluir_colaborador(item_id):
    colaborador = HCGig2.query.get_or_404(item_id)
    db.session.delete(colaborador)
    db.session.commit()
    return jsonify({"mensagem": f"Colaborador '{colaborador.nome_completo}' excluído com sucesso."})


@hc_bp.route("/api/hc/<int:item_id>/pedir-data-desligamento", methods=["POST"])
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
        # Retorna o mailto como fallback
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


@hc_bp.route("/api/hc/import-csv", methods=["POST"])
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
    # Separar "status de liberacao" de "status"
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

    inseridos = 0
    atualizados = 0
    erros = []

    for idx, row in df.iterrows():
        try:
            nome = str(row.get(col_nome, "")).strip() if col_nome else ""
            if not nome or nome.lower() == "nan":
                continue

            login = str(row.get(col_login, "")).strip() if col_login else ""
            login = None if login.lower() in ("nan", "none", "") else login

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

            # Upsert: tenta por login, senão por nome
            item = None
            if login:
                item = HCGig2.query.filter_by(login=login).first()
            if not item:
                item = HCGig2.query.filter(
                    HCGig2.nome_completo.ilike(nome)
                ).first()

            if not item:
                item = HCGig2()
                db.session.add(item)
                inseridos += 1
            else:
                atualizados += 1

            item.nome_completo = nome
            item.login = login
            item.cargo = cargo or (item.cargo if item.cargo else "")
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

    result = {"mensagem": "Importação concluída.", "inseridos": inseridos, "atualizados": atualizados}
    if erros:
        result["erros"] = erros
    return jsonify(result)


@hc_bp.route("/api/hc/import", methods=["POST"])
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


@hc_bp.route("/api/hc/dashboard", methods=["GET"])
def dashboard_data():
    f_area   = request.args.get("area", "").strip()
    f_turno  = request.args.get("turno", "").strip()
    f_status = request.args.get("status", "").strip()

    todos = HCGig2.query.all()
    for r in todos:
        r.aplicar_status_por_data()
    db.session.commit()

    # Aplica filtros
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

    # Ordena por valor desc
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

    # HC Operacional por turno — Analista / Associado / PIT
    operacional_por_turno = {}
    for turno in TURNOS:
        if turno == "ADM":
            continue
        operacional_por_turno[turno] = {
            "Analista":  sum(1 for r in registros if r.turno == turno and r.cargo == "Analista"  and r.status == "OPERACIONAL"),
            "Associado": sum(1 for r in registros if r.turno == turno and r.cargo == "Associado" and r.status == "OPERACIONAL"),
            "PIT":       sum(1 for r in registros if r.turno == turno and r.cargo == "PIT"       and r.status == "OPERACIONAL"),
        }

    # Valores únicos para os filtros (sempre do total, não dos filtrados)
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
        "status": {"OPERACIONAL": operacional, "Licença": licenca, "OFF": off},
        "associados_e_pits": associados_e_pits,
        "operacional_por_turno": operacional_por_turno,
        "filtros_disponiveis": {
            "areas":  areas_disponiveis,
            "turnos": turnos_disponiveis,
            "status": status_disponiveis,
        },
        "filtros_ativos": {"area": f_area, "turno": f_turno, "status": f_status},
    })

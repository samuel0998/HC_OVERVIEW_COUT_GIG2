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
from models.lc_atual import LCAtual

hc_bp = Blueprint("hc", __name__)

CARGOS  = ["AA", "Associado", "PIT", "Analista", "Supervisor", "Líder", "Técnico", "Fiscal", "Coordenador", "Gerente"]
AREAS   = ["INBOUND", "OUTBOUND", "TRANSFER IN", "TRANSFERIN", "TRANSFER OUT", "ICQA", "INSUMOS", "LEARNING", "LP", "FACILITIES", "RME", "SUPORTE", "C-RET", "TOM", "ADM"]
TURNOS  = ["BLUE DAY", "BLUE NIGHT", "RED DAY", "RED NIGHT", "ADM"]
STATUS  = ["OPERACIONAL", "Treinamento", "Licença", "Férias", "Desligado", "OFF"]
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


def _clean_excel_value(value):
    if pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() in ("nan", "none") else text


def _cargo_normalizado(cargo):
    return _normalizar(cargo).upper()


def _turno_inicial(cargo, turno=None):
    if _cargo_normalizado(cargo) == "PIT":
        return "ADM"
    return (turno or "").strip() or None


def _pendencia_turno_expr():
    return db.and_(HCGig2.status == "OPERACIONAL", HCGig2.cargo == "PIT", HCGig2.turno.is_(None))


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


def _aplicar_regra_hc_atual(registros, hoje=None, commit=True):
    alterou = False
    for registro in registros:
        if registro.aplicar_status_por_data(hoje):
            alterou = True
    if alterou and commit:
        db.session.commit()
    return alterou


def _pendencias_count():
    """Return count of operators with pending dates or shift allocation."""
    _aplicar_regra_hc_atual(HCGig2.query.all())
    return HCGig2.query.filter(
        or_(
            db.and_(HCGig2.status.in_(["Licença", "Férias"]), HCGig2.data_inicio_licenca.is_(None)),
            db.and_(HCGig2.status == "Desligado", HCGig2.data_desligamento.is_(None)),
            _pendencia_turno_expr(),
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


@hc_bp.route("/lc")
@login_required
def lc_page():
    if not current_user.can_dashboard:
        abort(403)
    return render_template("lc_atual.html")


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

    _aplicar_regra_hc_atual(registros)

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
        turno=None,
        status="Treinamento",
    )
    colaborador.turno = _turno_inicial(colaborador.cargo, data.get("turno"))

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
            "status": colaborador.status,
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
    if colaborador.status == "Treinamento":
        colaborador.turno = _turno_inicial(colaborador.cargo, colaborador.turno)
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

    colaborador.aplicar_status_por_data()

    dados_nov = json.dumps({
        "nome_completo": colaborador.nome_completo,
        "login": colaborador.login or "",
        "cargo": colaborador.cargo,
        "area": colaborador.area or "",
        "turno": colaborador.turno or "",
        "status": colaborador.status,
        "causa_afastamento": colaborador.causa_afastamento or "",
    })

    status_final = colaborador.status
    tipo = "edicao_status" if status_anterior != status_final else "edicao"
    msg_status = f" (status: {status_anterior} → {status_final})" if status_anterior != status_final else ""
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
    _aplicar_regra_hc_atual(HCGig2.query.all(), hoje=hoje)

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
            _pendencia_turno_expr(),
        )
    ).order_by(HCGig2.nome_completo.asc()).all()

    return jsonify({
        "pendencias": [
            {
                **p.to_dict(),
                "pendencia_tipo": "turno" if p.status == "OPERACIONAL" and p.cargo == "PIT" and not p.turno else "data",
            }
            for p in pendentes
        ],
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
        "treinamento": "Treinamento",
        "off": "OFF",
        "licenca": "Licença",
        "licença": "Licença",
        "ferias": "Férias",
        "férias": "Férias",
        "desligado": "Desligado",
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
            item.turno = _turno_inicial(item.cargo, turno) if status == "Treinamento" else turno
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
        turno = str(row[normalizadas["turno"]]).strip() or None
        item.status = str(row[normalizadas["status"]]).strip() or "OPERACIONAL"
        item.turno = _turno_inicial(item.cargo, turno) if item.status == "Treinamento" else turno
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
    _aplicar_regra_hc_atual(registros)

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


@hc_bp.route("/api/lc", methods=["GET"])
@login_required
def listar_lc():
    termo = request.args.get("q", "").strip().lower()
    f_login = request.args.get("login", "").strip().lower()
    f_process = request.args.get("process_name", request.args.get("process", "")).strip()
    f_level = request.args.get("lc_level", request.args.get("level", "")).strip()
    f_area = request.args.get("area", "").strip()
    f_turno = request.args.get("turno", "").strip()
    f_status = request.args.get("status", "").strip()
    f_cargo = request.args.get("cargo", "").strip()
    sem_hc = request.args.get("sem_hc", "").strip().lower() in ("1", "true", "sim")

    hc_por_login = {
        (r.login or "").strip().lower(): r
        for r in HCGig2.query.all()
        if (r.login or "").strip()
    }

    registros = LCAtual.query.order_by(LCAtual.login.asc(), LCAtual.process_name.asc()).all()
    dados = []

    for r in registros:
        login_key = (r.login or "").strip().lower()
        hc_ref = hc_por_login.get(login_key)

        if sem_hc and hc_ref:
            continue
        if f_login and f_login not in login_key:
            continue
        if f_process and r.process_name != f_process:
            continue
        if f_level and r.lc_level != f_level:
            continue
        if f_area and ((hc_ref.area if hc_ref else "") or "") != f_area:
            continue
        if f_turno and ((hc_ref.turno if hc_ref else "") or "") != f_turno:
            continue
        if f_status and ((hc_ref.status if hc_ref else "") or "") != f_status:
            continue
        if f_cargo and ((hc_ref.cargo if hc_ref else "") or "") != f_cargo:
            continue

        item = {
            **r.to_dict(),
            "nome_completo": hc_ref.nome_completo if hc_ref else "",
            "cargo": hc_ref.cargo if hc_ref else "",
            "area": hc_ref.area if hc_ref else "",
            "turno": hc_ref.turno if hc_ref else "",
            "status": hc_ref.status if hc_ref else "",
            "hc_encontrado": bool(hc_ref),
        }

        if termo:
            haystack = " ".join([
                item["login"],
                item["process_name"],
                item["lc_level"],
                item["nome_completo"],
                item["cargo"],
                item["area"],
                item["turno"],
                item["status"],
            ]).lower()
            if termo not in haystack:
                continue

        dados.append(item)

    filtros = {
        "processos": sorted({r.process_name for r in registros if r.process_name}),
        "levels": sorted({r.lc_level for r in registros if r.lc_level}),
        "areas": sorted({r.area for r in hc_por_login.values() if r.area}),
        "turnos": sorted({r.turno for r in hc_por_login.values() if r.turno}),
        "status": sorted({r.status for r in hc_por_login.values() if r.status}),
        "cargos": ["Associado", "PIT"],
    }

    return jsonify({
        "registros": dados,
        "total": len(dados),
        "filtros": filtros,
    })


@hc_bp.route("/api/lc/import", methods=["POST"])
@login_required
def importar_lc_excel():
    if not current_user.can_edit:
        return jsonify({"erro": "Sem permissao para importar LC."}), 403

    arquivo = request.files.get("arquivo")
    if not arquivo:
        return jsonify({"erro": "Envie um arquivo Excel."}), 400

    try:
        df = pd.read_excel(arquivo, dtype=str)
    except Exception as e:
        return jsonify({"erro": f"Erro ao ler Excel de LC: {str(e)}"}), 400

    col_login = _find_col(df, "login")
    col_process = _find_col(df, "process name") or _find_col(df, "process")
    col_lc_level = _find_col(df, "lc level") or _find_col(df, "level")

    if not col_login and len(df.columns) > 1:
        col_login = df.columns[1]
    if not col_process and len(df.columns) > 5:
        col_process = df.columns[5]
    if not col_lc_level and len(df.columns) > 6:
        col_lc_level = df.columns[6]

    faltando = []
    if not col_login:
        faltando.append("Login (coluna B)")
    if not col_process:
        faltando.append("Process Name (coluna F)")
    if not col_lc_level:
        faltando.append("LC Level (coluna G)")
    if faltando:
        return jsonify({"erro": f"Colunas ausentes: {', '.join(faltando)}"}), 400

    try:
        LCAtual.query.delete()

        inseridos = 0
        ignorados = 0
        erros = []

        for idx, row in df.iterrows():
            try:
                login = _clean_excel_value(row.get(col_login))
                process_name = _clean_excel_value(row.get(col_process))
                lc_level = _clean_excel_value(row.get(col_lc_level))

                if not login and not process_name and not lc_level:
                    ignorados += 1
                    continue

                if not login or not process_name or not lc_level:
                    erros.append(f"Linha {idx + 2}: login, Process Name e LC Level sao obrigatorios.")
                    continue

                db.session.add(LCAtual(
                    login=login,
                    process_name=process_name,
                    lc_level=lc_level,
                ))
                inseridos += 1
            except Exception as e:
                erros.append(f"Linha {idx + 2}: {str(e)}")

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"erro": f"Erro ao gravar LC no banco: {str(e)}"}), 500

    result = {
        "mensagem": "LC atual renovada com sucesso.",
        "inseridos": inseridos,
        "ignorados": ignorados,
    }
    if erros:
        result["erros"] = erros
    return jsonify(result)


@hc_bp.route("/api/lc/export", methods=["GET"])
@login_required
def exportar_lc_excel():
    registros = LCAtual.query.order_by(LCAtual.login.asc(), LCAtual.process_name.asc()).all()
    dados = [{
        "Login": r.login,
        "Process Name": r.process_name,
        "LC Level": r.lc_level,
    } for r in registros]

    df = pd.DataFrame(dados)

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="LC_ATUAL")
    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name="lc_atual.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ── API: Dashboard ─────────────────────────────────────────────


@hc_bp.route("/api/hc/dashboard", methods=["GET"])
@login_required
def dashboard_data():
    f_area   = request.args.get("area", "").strip()
    f_turno  = request.args.get("turno", "").strip()
    f_status = request.args.get("status", "").strip()
    f_cargo  = request.args.get("cargo", "").strip()

    todos = HCGig2.query.all()
    _aplicar_regra_hc_atual(todos)

    registros = todos
    if f_area:
        registros = [r for r in registros if (r.area or "") == f_area]
    if f_turno:
        registros = [r for r in registros if (r.turno or "") == f_turno]
    if f_status:
        registros = [r for r in registros if r.status == f_status]
    if f_cargo:
        registros = [r for r in registros if r.cargo == f_cargo]

    total      = len(registros)
    operacional = sum(1 for r in registros if r.status == "OPERACIONAL")
    off        = sum(1 for r in registros if r.status == "OFF")
    treinamento = sum(1 for r in registros if r.status == "Treinamento")
    licenca    = sum(1 for r in registros if r.status == "Licença")
    ferias     = sum(1 for r in registros if r.status == "Férias")

    outbound_areas = {"OUTBOUND", "TRANSFER OUT", "INSUMOS", "LP"}
    inbound_areas  = {"INBOUND", "TRANSFER IN", "TRANSFERIN", "C-RET"}
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

    hc_por_login = {
        (r.login or "").strip().lower(): r
        for r in todos
        if (r.login or "").strip()
    }

    lc_todos = LCAtual.query.all()
    lc_registros = []
    lc_sem_hc = 0

    for lc in lc_todos:
        hc_ref = hc_por_login.get((lc.login or "").strip().lower())
        if not hc_ref:
            if not f_area and not f_turno and not f_status:
                lc_registros.append((lc, None))
            lc_sem_hc += 1
            continue

        if f_area and (hc_ref.area or "") != f_area:
            continue
        if f_turno and (hc_ref.turno or "") != f_turno:
            continue
        if f_status and hc_ref.status != f_status:
            continue
        if f_cargo and hc_ref.cargo != f_cargo:
            continue

        lc_registros.append((lc, hc_ref))

    def _count_dict(items):
        resultado = {}
        for item in items:
            chave = item or "Sem informacao"
            resultado[chave] = resultado.get(chave, 0) + 1
        return dict(sorted(resultado.items(), key=lambda x: x[1], reverse=True))

    def _unique_people_count(pares):
        return len({(lc.login or "").strip().lower() for lc, _ in pares if (lc.login or "").strip()})

    lc_por_processo = _count_dict([lc.process_name for lc, _ in lc_registros])
    lc_por_level = _count_dict([lc.lc_level for lc, _ in lc_registros])
    lc_por_turno = _count_dict([(hc_ref.turno if hc_ref else None) for _, hc_ref in lc_registros])
    lc_por_area = _count_dict([(hc_ref.area if hc_ref else None) for _, hc_ref in lc_registros])
    lc_por_cargo = _count_dict([(hc_ref.cargo if hc_ref else None) for _, hc_ref in lc_registros])
    lc_por_status = _count_dict([(hc_ref.status if hc_ref else None) for _, hc_ref in lc_registros])

    lc_processo_level = {}
    for lc, _ in lc_registros:
        processo = lc.process_name or "Sem informacao"
        level = lc.lc_level or "Sem informacao"
        lc_processo_level.setdefault(processo, {})
        lc_processo_level[processo][level] = lc_processo_level[processo].get(level, 0) + 1
    lc_processo_level = dict(
        sorted(lc_processo_level.items(), key=lambda x: sum(x[1].values()), reverse=True)[:12]
    )

    lc_turno_level = {}
    for lc, hc_ref in lc_registros:
        turno = (hc_ref.turno if hc_ref else None) or "Sem informacao"
        level = lc.lc_level or "Sem informacao"
        lc_turno_level.setdefault(turno, {})
        lc_turno_level[turno][level] = lc_turno_level[turno].get(level, 0) + 1

    lc_top_login = _count_dict([lc.login for lc, _ in lc_registros])
    lc_top_login = dict(list(lc_top_login.items())[:15])

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
        "status": {"OPERACIONAL": operacional, "Treinamento": treinamento, "Licença": licenca, "Férias": ferias, "OFF": off},
        "associados_e_pits": associados_e_pits,
        "operacional_por_turno": operacional_por_turno,
        "filtros_disponiveis": {
            "areas":  areas_disponiveis,
            "turnos": turnos_disponiveis,
            "status": status_disponiveis,
            "cargos": ["Associado", "PIT"],
        },
        "filtros_ativos": {"area": f_area, "turno": f_turno, "status": f_status, "cargo": f_cargo},
        "lc": {
            "cards": {
                "total_registros": len(lc_registros),
                "pessoas_com_lc": _unique_people_count(lc_registros),
                "processos": len(lc_por_processo),
                "sem_hc": lc_sem_hc,
            },
            "por_processo": lc_por_processo,
            "por_level": lc_por_level,
            "por_turno": lc_por_turno,
            "por_area": lc_por_area,
            "por_cargo": lc_por_cargo,
            "por_status": lc_por_status,
            "processo_level": lc_processo_level,
            "turno_level": lc_turno_level,
            "top_login": lc_top_login,
        },
    })

import json
import os
import smtplib
import unicodedata
from datetime import date, datetime, timedelta
from email.mime.text import MIMEText
from io import BytesIO
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import pandas as pd
from flask import Blueprint, abort, jsonify, render_template, request, send_file
from flask_login import current_user, login_required
from sqlalchemy import or_

from models import db, get_current_fc
from models.hc_gig2 import HCGig2
from models.lc_atual import LCAtual
from models.ticket import TICKET_TYPES, Ticket
from models.turno_config import HCTurnoConfig, ensure_default_turno_config

hc_bp = Blueprint("hc", __name__)

CARGOS  = ["AA", "Associado", "PA", "PIT", "Analista", "Supervisor", "Líder", "Técnico", "Fiscal", "Coordenador", "Gerente"]
AREAS   = ["INBOUND", "OUTBOUND", "TRANSFER IN", "TRANSFERIN", "TRANSFER OUT", "ICQA", "INSUMOS", "LEARNING", "LP", "FACILITIES", "RME", "SUPORTE", "C-RET", "TOM", "ADM"]
TURNOS  = ["BLUE DAY", "BLUE NIGHT", "RED DAY", "RED NIGHT", "ADM"]
STATUS  = ["OPERACIONAL", "VTE", "VTO", "Treinamento", "Ausência", "Licença", "Férias", "Desligado", "OFF"]
PROCESSOS_POR_AREA = {
    "C-RET": ["C-RET PROCESS", "C-RET STOW", "C-RET PS", "C-RET SUPPORT"],
    "TRANSFER IN": ["Transfer In Decant", "Each Transfer In", "Pallet Transfer In", "Tote Transfer In", "Transfer In Support", "Transfer In"],
    "TRANSFER OUT": ["Transfer Out Pick", "Transfer Out Dock", "Transfer Support"],
    "OUTBOUND": ["Pick", "Sort", "Pack Singles", "Pack Multis", "Outbound support", "OB Support", "Container Build", "Container Move", "Container Load"],
    "INBOUND": ["PS INBOUND"],
}
PROCESSOS = [processo for processos in PROCESSOS_POR_AREA.values() for processo in processos]
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


def _identificador_fc_exportacao():
    """Retorna o site ativo em formato seguro para nomes de arquivo e aba."""
    fc_ativo = get_current_fc()
    if fc_ativo.startswith("IXD_"):
        fc_ativo = "IXD"

    identificador = "".join(
        caractere if caractere.isalnum() else "_"
        for caractere in _normalizar(fc_ativo)
    )
    return "_".join(parte for parte in identificador.split("_") if parte) or "hc"


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


def _read_lc_upload(arquivo):
    """Localiza o cabecalho da base de LC mesmo quando ha titulo antes da tabela."""
    arquivo.seek(0)
    preview = pd.read_excel(arquivo, header=None, dtype=str, nrows=20)
    header_row = None
    for idx, row in preview.iterrows():
        colunas = {_normalizar(value) for value in row if _clean_excel_value(value)}
        if "login" in colunas and "process name" in colunas and "lc level" in colunas:
            header_row = idx
            break
    if header_row is None:
        raise ValueError("Cabecalho nao encontrado. Esperado: Login, Process Name e LC Level.")
    arquivo.seek(0)
    return pd.read_excel(arquivo, header=header_row, dtype=str)


def _read_csv_upload(arquivo):
    tentativas = [
        ("utf-8-sig", {"sep": None, "engine": "python"}),
        ("utf-8-sig", {"sep": ";"}),
        ("utf-8-sig", {"sep": ","}),
        ("latin-1", {"sep": None, "engine": "python"}),
        ("latin-1", {"sep": ";"}),
        ("latin-1", {"sep": ","}),
    ]
    ultimo_erro = None

    for encoding, opcoes in tentativas:
        try:
            arquivo.seek(0)
            df = pd.read_csv(arquivo, encoding=encoding, dtype=str, **opcoes)
            if len(df.columns) > 1:
                return df
            ultimo_erro = ValueError("CSV lido com apenas uma coluna.")
        except Exception as e:
            ultimo_erro = e

    raise ultimo_erro


def _cargo_normalizado(cargo):
    return _normalizar(cargo).upper()


def _cargo_eh(cargo, *valores):
    return _cargo_normalizado(cargo) in {_cargo_normalizado(valor) for valor in valores}


def _formatar_cargo(cargo):
    texto = (cargo or "").strip()
    if not texto or texto.lower() in ("nan", "none"):
        return ""

    cargo_map = {
        "AA": "AA",
        "ASSOCIADO": "Associado",
        "PIT": "PIT",
        "ANALISTA": "Analista",
        "SUPERVISOR": "Supervisor",
        "LIDER": "Líder",
        "TECNICO": "Técnico",
        "FISCAL": "Fiscal",
        "COORDENADOR": "Coordenador",
        "GERENTE": "Gerente",
    }
    return cargo_map.get(_cargo_normalizado(texto), texto)


def _formatar_job(job):
    texto = (job or "").strip()
    if not texto or _normalizar(texto) in ("nan", "none", "sem job", "sem processo"):
        return None

    normalizado = _normalizar(texto)
    for processo in PROCESSOS:
        if _normalizar(processo) == normalizado:
            return processo
    return texto


def _mapear_jobs_existentes():
    jobs_por_login = {}
    jobs_por_nome = {}

    for item in HCGig2.query.filter(HCGig2.job.isnot(None)).all():
        job = _formatar_job(item.job)
        if not job:
            continue

        login_key = (item.login or "").strip().lower()
        nome_key = _normalizar(item.nome_completo or "")
        if login_key:
            jobs_por_login[login_key] = job
        if nome_key:
            jobs_por_nome[nome_key] = job

    return jobs_por_login, jobs_por_nome


def _job_importado_ou_preservado(job_importado, login, nome, jobs_por_login, jobs_por_nome):
    if job_importado:
        return job_importado, False

    login_key = (login or "").strip().lower()
    nome_key = _normalizar(nome or "")
    job_existente = jobs_por_login.get(login_key) or jobs_por_nome.get(nome_key)
    return job_existente, bool(job_existente)


def _formatar_turno_extra(turno):
    texto = (turno or "").strip()
    if not texto or texto.lower() in ("nan", "none"):
        return None

    normalizado = _normalizar(texto).upper()
    for item in TURNOS:
        if _normalizar(item).upper() == normalizado:
            return item
    return texto


def _jobs_por_area(area):
    area_norm = _normalizar(area).upper()
    aliases = {
        "TRANSFERIN": "TRANSFER IN",
    }
    area_key = aliases.get(area_norm, area_norm)
    return PROCESSOS_POR_AREA.get(area_key, [])


def _parse_multi_filtro(value):
    """Aceita filtro simples ou multi-filtro (valores separados por vírgula)."""
    if not value:
        return []
    return [v.strip() for v in value.split(",") if v.strip()]


def _parse_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    texto = _normalizar(value)
    if not texto or texto in ("nan", "none"):
        return default
    if texto in ("nao", "n", "false", "0", "no", "ausente", "fora", "fora do fc", "off"):
        return False
    if texto in ("sim", "s", "true", "1", "yes", "y", "presente", "no fc", "fc", "on"):
        return True
    return default


def _turno_inicial(cargo, turno=None):
    if _cargo_normalizado(cargo) == "PIT":
        return "ADM"
    return (turno or "").strip() or None


def _pendencia_turno_expr():
    return db.and_(HCGig2.status == "OPERACIONAL", HCGig2.cargo == "PIT", HCGig2.turno.is_(None))


def _pendencia_filtro():
    """Quem precisa de uma data definida. O prazo de terça é só alerta visual: mesmo
    depois de virar OFF automaticamente, o colaborador continua aqui até alguém
    definir a data (off_origem guarda de onde ele veio)."""
    return or_(
        db.and_(HCGig2.status.in_(["Licença", "Férias"]), HCGig2.data_inicio_licenca.is_(None)),
        db.and_(HCGig2.status == "Desligado", HCGig2.data_desligamento.is_(None)),
        db.and_(HCGig2.status == "OFF", HCGig2.off_origem.isnot(None)),
        _pendencia_turno_expr(),
    )


def _registrar(tipo, op, descricao, dados_ant=None, dados_nov=None, sistema=False):
    """Log an activity to registro_atividade."""
    from models.registro_atividade import RegistroAtividade
    if sistema:
        u_login, u_nome = "sistema", "Automação"
    else:
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
    agora = datetime.utcnow()
    for registro in registros:
        antes = {
            "status": registro.status,
            "status_agendado": registro.status_agendado or "",
            "area": registro.area or "",
            "turno": registro.turno or "",
        }
        if registro.aplicar_status_por_data(hoje, agora):
            alterou = True
            depois = {
                "status": registro.status,
                "status_agendado": registro.status_agendado or "",
                "area": registro.area or "",
                "turno": registro.turno or "",
            }
            temporario_antes = antes["status"] if antes["status"] in ("VTE", "VTO") else antes["status_agendado"]
            if temporario_antes in ("VTE", "VTO"):
                if registro.status == "OPERACIONAL":
                    descricao = f"Retorno automático de {temporario_antes} para OPERACIONAL após 12h"
                else:
                    descricao = f"Ativação automática de {temporario_antes} na data agendada"
                if antes["area"] != depois["area"] or antes["turno"] != depois["turno"]:
                    descricao += (
                        f"; setor/escala: {antes['area'] or '-'} / {antes['turno'] or '-'}"
                        f" → {depois['area'] or '-'} / {depois['turno'] or '-'}"
                    )
                _registrar(
                    "edicao_status",
                    registro,
                    descricao,
                    dados_ant=json.dumps(antes),
                    dados_nov=json.dumps(depois),
                    sistema=True,
                )
    if alterou and commit:
        db.session.commit()
    return alterou


def _reset_chamada_por_virada_de_turno():
    configs_criadas = ensure_default_turno_config()
    agora = datetime.now(ZoneInfo("America/Sao_Paulo"))
    configs = HCTurnoConfig.query.all()
    configs_vencidas = []

    for config in configs:
        try:
            hora, minuto = [int(parte) for parte in config.hora_reset.split(":", 1)]
        except Exception:
            continue

        horario_reset = agora.replace(hour=hora, minute=minuto, second=0, microsecond=0)
        reset_key = f"{agora.date().isoformat()}:{config.turno}:{config.hora_reset}"
        if agora >= horario_reset and config.last_reset_key != reset_key:
            configs_vencidas.append((config, reset_key))

    if not configs_vencidas:
        if configs_criadas:
            db.session.commit()
        return False

    for registro in HCGig2.query.filter(HCGig2.status == "OPERACIONAL").all():
        registro.presente_fc = True
        registro.presenca_manual = False

    for config, reset_key in configs_vencidas:
        config.last_reset_key = reset_key

    db.session.commit()
    return True


def _pendencias_count():
    """Conta pendencias cadastrais e tickets visiveis para o usuario atual."""
    _reset_chamada_por_virada_de_turno()
    _aplicar_regra_hc_atual(HCGig2.query.all())
    total = HCGig2.query.filter(_pendencia_filtro()).count()
    tickets = _tickets_visiveis()
    return total + (len(tickets) if tickets is not None else 0)


# ── Tickets de premissas (LS, LT, TOFF, RP, ON) ──────────────────


def _match_valor_conhecido(valor, lista):
    """Casa o valor vindo do ticket (sector_key/shift_name/labor_type) com uma opcao
    conhecida do sistema (AREAS/TURNOS/CARGOS), ignorando acentos/caixa. Sem match
    confiavel, retorna vazio em vez de forcar um filtro/valor errado no List."""
    if not valor:
        return ""
    if lista is AREAS:
        alvo = _area_normalizada(valor)
    elif lista is TURNOS:
        alvo = _turno_normalizado(valor)
    else:
        alvo = _normalizar(valor)
    for item in lista:
        if lista is AREAS:
            conhecido = _area_normalizada(item)
        elif lista is TURNOS:
            conhecido = _turno_normalizado(item)
        else:
            conhecido = _normalizar(item)
        if conhecido == alvo:
            return item
    return ""


def _area_normalizada(valor):
    alvo = _normalizar(valor).replace("-", " ").replace("_", " ")
    alvo = " ".join(alvo.split())
    compacto = alvo.replace(" ", "")
    aliases = {
        "in": "inbound",
        "ib": "inbound",
        "inb": "inbound",
        "receive": "inbound",
        "receiving": "inbound",
        "out": "outbound",
        "ob": "outbound",
        "outb": "outbound",
        "shipping": "outbound",
        "ti": "transferin",
        "tfi": "transferin",
        "tfin": "transferin",
        "trin": "transferin",
        "transin": "transferin",
        "transferinbound": "transferin",
        "to": "transferout",
        "tfo": "transferout",
        "tfout": "transferout",
        "trout": "transferout",
        "transout": "transferout",
        "transferoutbound": "transferout",
        "cret": "cret",
    }
    return aliases.get(compacto, compacto)


def _area_corresponde(valor_hc, valor_ticket):
    return not valor_ticket or _area_normalizada(valor_hc) == _area_normalizada(valor_ticket)


def _turno_normalizado(valor):
    texto = _normalizar(valor).replace("-", " ").replace("_", " ")
    compacto = "".join(texto.split())
    aliases = {
        "bd": "blueday",
        "dayblue": "blueday",
        "azuldia": "blueday",
        "bn": "bluenight",
        "nightblue": "bluenight",
        "azulnoite": "bluenight",
        "rd": "redday",
        "dayred": "redday",
        "vermelhodia": "redday",
        "rn": "rednight",
        "nightred": "rednight",
        "vermelhonoite": "rednight",
        "d": "day",
        "dayshift": "day",
        "diurno": "day",
        "dia": "day",
        "n": "night",
        "nightshift": "night",
        "noturno": "night",
        "noite": "night",
        "administrativo": "adm",
    }
    return aliases.get(compacto, compacto)


def _turno_corresponde(valor_hc, valor_ticket):
    if not valor_ticket:
        return True
    hc = _turno_normalizado(valor_hc)
    ticket = _turno_normalizado(valor_ticket)
    if hc == ticket:
        return True
    # A ferramenta de premissas pode enviar apenas Day/Night, enquanto o HC
    # distingue BLUE/RED. Nesse caso a parte do dia ainda e uma correspondencia valida.
    if ticket in ("day", "night"):
        return hc.endswith(ticket)
    if hc in ("day", "night"):
        return ticket.endswith(hc)
    return False


def _cargo_ticket_corresponde(cargo_hc, cargo_ticket):
    cargo = _cargo_normalizado(cargo_hc)
    esperado = _cargo_normalizado(cargo_ticket)
    if not esperado or esperado in ("ALL", "TODOS", "HC"):
        return cargo in ("AA", "ASSOCIADO", "PIT")
    if esperado in ("AA", "ASSOCIATE", "ASSOCIADO"):
        return cargo in ("AA", "ASSOCIADO")
    return cargo == esperado


def _hc_turno_por_login(login):
    """Turno real (escala BLUE/RED) do colaborador no HC. Vazio se nao encontrar
    ninguem com esse login."""
    login = (login or "").strip().lower()
    if not login:
        return ""
    hc = HCGig2.query.filter(
        db.func.lower(db.func.trim(HCGig2.login)) == login
    ).first()
    return (hc.turno or "") if hc else ""


def _ticket_escala_lado(login, *fallbacks):
    """Escala (BLUE/RED) de um lado do ticket: usa o turno real de quem responde no
    HC; sem correspondencia, cai no texto bruto do ticket (normalmente so' Day/Night)."""
    turno = _hc_turno_por_login(login)
    if turno:
        return turno
    for valor in fallbacks:
        if valor:
            return valor
    return ""


def _ticket_owner_contexto(t):
    """Area/turno reais do owner no HC; usa os dados do ticket como fallback."""
    owner_login = (t.owner_login or "").strip().lower()
    owner_hc = None
    if owner_login:
        owner_hc = HCGig2.query.filter(
            db.func.lower(db.func.trim(HCGig2.login)) == owner_login
        ).first()

    if owner_hc:
        return owner_hc.area or "", owner_hc.turno or ""
    if t.is_transferencia:
        return (
            _match_valor_conhecido(t.source_sector_key, AREAS),
            _match_valor_conhecido(t.source_shift_name or t.source_shift_key, TURNOS),
        )
    return (
        _match_valor_conhecido(t.sector_key, AREAS),
        _match_valor_conhecido(t.shift_name or t.shift_key, TURNOS),
    )


def _ticket_resolver_url(t):
    """Link de 'Resolver Pendencia': ON manda para Novo HC, os demais para o List
    (Atualizar) ja filtrado pelo turno/setor de quem precisa agir."""
    if t.premise_type == "ON":
        pares = [
            ("area", _match_valor_conhecido(t.sector_key, AREAS)),
            ("turno", _match_valor_conhecido(t.shift_name or t.shift_key, TURNOS)),
            ("cargo", _match_valor_conhecido(t.labor_type, CARGOS)),
            ("ticket_id", t.premise_id),
        ]
        pares = [p for p in pares if p[1]]
        return "/novo" + (f"?{urlencode(pares)}" if pares else "")

    area, turno = _ticket_owner_contexto(t)
    cargo_ticket = (t.source_labor_type or t.labor_type) if t.is_transferencia else t.labor_type
    cargo = _match_valor_conhecido(cargo_ticket, CARGOS)

    pares = [p for p in (("area", area), ("turno", turno), ("cargo", cargo), ("ticket_id", t.premise_id)) if p[1]]
    return "/atualizar" + (f"?{urlencode(pares)}" if pares else "")


def _json_dict(valor):
    if not valor:
        return {}
    try:
        dados = json.loads(valor)
        return dados if isinstance(dados, dict) else {}
    except (TypeError, ValueError):
        return {}


def _registro_cumpre_ticket(t, registro, owner_area="", owner_turno=""):
    """Valida uma acao auditada do HC contra a regra concreta do ticket."""
    antes = _json_dict(registro.dados_anteriores)
    depois = _json_dict(registro.dados_novos)
    tipo = (t.premise_type or "").upper()

    if tipo == "ON":
        if registro.tipo != "adicao":
            return False
        return (
            _area_corresponde(depois.get("area"), t.sector_key)
            and _turno_corresponde(depois.get("turno"), t.shift_name or t.shift_key)
            and _cargo_ticket_corresponde(depois.get("cargo"), t.labor_type)
        )

    cargo_antes = antes.get("cargo") or depois.get("cargo")
    if tipo in ("LS", "LT", "LM"):
        if registro.tipo not in ("edicao", "edicao_status"):
            return False
        origem_area = t.source_sector_key or owner_area
        origem_turno = t.source_shift_name or t.source_shift_key or owner_turno
        mudou_alocacao = (
            _normalizar(antes.get("area")) != _normalizar(depois.get("area"))
            or _normalizar(antes.get("turno")) != _normalizar(depois.get("turno"))
        )
        return (
            mudou_alocacao
            and _cargo_ticket_corresponde(cargo_antes, t.source_labor_type or t.labor_type)
            and _area_corresponde(antes.get("area"), origem_area)
            and _turno_corresponde(antes.get("turno"), origem_turno)
            and _area_corresponde(depois.get("area"), t.sector_key)
            and _turno_corresponde(depois.get("turno"), t.shift_name or t.shift_key)
        )

    if tipo in ("TOFF", "RP"):
        if registro.tipo not in ("edicao", "edicao_status"):
            return False
        desligado_antes = antes.get("status") == "Desligado" or antes.get("status_agendado") == "Desligado"
        desligado_depois = depois.get("status") == "Desligado" or depois.get("status_agendado") == "Desligado"
        return (
            not desligado_antes
            and desligado_depois
            and _cargo_ticket_corresponde(cargo_antes, t.labor_type)
            and _area_corresponde(antes.get("area"), owner_area or t.sector_key)
            and _turno_corresponde(antes.get("turno"), owner_turno or t.shift_name or t.shift_key)
        )

    return False


def _ids_acoes_ja_consumidas():
    from models.registro_atividade import RegistroAtividade

    ids = set()
    registros = RegistroAtividade.query.filter(
        RegistroAtividade.tipo == "ticket_resolvido",
        RegistroAtividade.dados_novos.isnot(None),
    ).all()
    for registro in registros:
        dados = _json_dict(registro.dados_novos)
        ids.update(dados.get("acao_ids") or [])
    return ids


def _janela_inicio_ticket(t):
    """Limite inferior da busca de acoes. Pega o MAIS CEDO entre created_at e
    (data solicitada - 30d) / start_date - a ferramenta externa reescreve
    created_at a cada sync e isso empurrava a janela para depois da acao que o
    usuario ja tinha feito. Piso rigido de 60 dias atras para nao ficar ilimitado."""
    candidatos = []
    if t.created_at:
        candidatos.append(t.created_at)
    base = t.start_date or (t.work_date - timedelta(days=30) if t.work_date else None)
    if base:
        candidatos.append(datetime.combine(base, datetime.min.time()))
    piso = datetime.combine(date.today() - timedelta(days=60), datetime.min.time())
    return max(min(candidatos), piso) if candidatos else piso


def _acoes_validas_ticket(t):
    """Acoes auditadas do HC que cumprem a regra concreta do ticket.

    NAO filtra por quem executou a acao: o endpoint resolver_ticket ja restringe
    quem pode concluir (owner do ticket ou EXPERT). Aqui olha-se apenas o conteudo
    da acao - setor/turno/cargo origem->destino e transicao de status - dentro da
    janela do ticket, sem contar a mesma pessoa movida duas vezes.
    """
    from models.registro_atividade import RegistroAtividade

    tipo = (t.premise_type or "").upper()
    tipos_acao = ("adicao",) if tipo == "ON" else ("edicao", "edicao_status")
    query = RegistroAtividade.query.filter(RegistroAtividade.tipo.in_(tipos_acao))
    query = query.filter(RegistroAtividade.timestamp >= _janela_inicio_ticket(t))

    owner_area, owner_turno = _ticket_owner_contexto(t)
    acoes_consumidas = _ids_acoes_ja_consumidas()
    encontrados = []
    operadores_vistos = set()
    for registro in query.order_by(RegistroAtividade.timestamp.asc()).all():
        if registro.id in acoes_consumidas:
            continue
        if not _registro_cumpre_ticket(t, registro, owner_area, owner_turno):
            continue
        # Quantidade representa pessoas, portanto a mesma pessoa nao pode contar duas vezes.
        chave = registro.operador_id or registro.operador_login or registro.id
        if chave in operadores_vistos:
            continue
        operadores_vistos.add(chave)
        encontrados.append(registro)
    return encontrados


def _log_ticket_nao_validado(t, progresso, necessarias):
    """Diagnostico nos logs (Railway) quando 'Validar conclusao' nao acha a acao.
    Lista os candidatos na janela e por que cada um nao casou com a regra."""
    from models.registro_atividade import RegistroAtividade

    tipo = (t.premise_type or "").upper()
    tipos_acao = ("adicao",) if tipo == "ON" else ("edicao", "edicao_status")
    inicio = _janela_inicio_ticket(t)
    owner_area, owner_turno = _ticket_owner_contexto(t)
    consumidas = _ids_acoes_ja_consumidas()
    candidatos = (
        RegistroAtividade.query
        .filter(RegistroAtividade.tipo.in_(tipos_acao))
        .filter(RegistroAtividade.timestamp >= inicio)
        .order_by(RegistroAtividade.timestamp.desc())
        .limit(25)
        .all()
    )
    print(
        f"[TICKET-VALIDACAO] #{t.premise_id} {tipo} nao validado ({progresso}/{necessarias}). "
        f"regra: cargo={t.source_labor_type or t.labor_type!r} "
        f"origem={t.source_sector_key or owner_area!r}/"
        f"{t.source_shift_name or t.source_shift_key or owner_turno!r} -> "
        f"destino={t.sector_key!r}/{t.shift_name or t.shift_key!r} "
        f"created_at={t.created_at} janela>={inicio:%Y-%m-%d %H:%M} candidatos={len(candidatos)}"
    )
    for r in candidatos:
        antes, depois = _json_dict(r.dados_anteriores), _json_dict(r.dados_novos)
        if r.id in consumidas:
            motivo = "ja consumida por outro ticket"
        elif _registro_cumpre_ticket(t, r, owner_area, owner_turno):
            motivo = "OK (casaria)"
        else:
            motivo = "nao casa com a regra"
        print(
            f"[TICKET-VALIDACAO]   reg#{r.id} {r.tipo} ts={r.timestamp:%Y-%m-%d %H:%M} "
            f"por {r.usuario_login!r} :: op={r.operador_nome!r} "
            f"{antes.get('cargo')!r} {antes.get('area')!r}/{antes.get('turno')!r} "
            f"status={antes.get('status')!r} -> {depois.get('area')!r}/{depois.get('turno')!r} "
            f"status={depois.get('status')!r} agendado={depois.get('status_agendado')!r} :: {motivo}"
        )


def _concluir_ticket_se_validado(t, verbose=False):
    if t.hcview_resolvido:
        return True, max(t.amount or 1, 1), max(t.amount or 1, 1)

    necessarias = max(t.amount or 1, 1)
    acoes = _acoes_validas_ticket(t)
    progresso = len(acoes)
    if progresso < necessarias:
        if verbose:
            _log_ticket_nao_validado(t, progresso, necessarias)
        return False, progresso, necessarias

    acao_final = acoes[necessarias - 1]
    t.hcview_resolvido = True
    t.hcview_resolvido_em = acao_final.timestamp or datetime.utcnow()
    t.hcview_resolvido_por_login = acao_final.usuario_login
    t.hcview_resolvido_por_nome = acao_final.usuario_nome

    from models.registro_atividade import RegistroAtividade
    db.session.add(RegistroAtividade(
        tipo="ticket_resolvido",
        usuario_login=acao_final.usuario_login,
        usuario_nome=acao_final.usuario_nome,
        descricao=(
            f"Ticket {t.tipo_label} #{t.premise_id} concluido automaticamente: "
            f"{progresso}/{necessarias} acao(oes) validada(s)."
        ),
        dados_novos=json.dumps({
            "ticket_id": t.premise_id,
            "acao_ids": [acao.id for acao in acoes[:necessarias]],
        }),
    ))
    return True, progresso, necessarias


def _sincronizar_tickets_por_acoes(tickets):
    alterou = False
    ordenados = sorted(tickets, key=lambda t: t.created_at.isoformat() if t.created_at else "")
    for ticket in ordenados:
        if ticket.hcview_resolvido:
            continue
        resolvido, _, _ = _concluir_ticket_se_validado(ticket)
        alterou = alterou or resolvido
    if alterou:
        db.session.commit()
    return alterou


def _tickets_visiveis():
    """Tickets em aberto (nao finalizados/nao resolvidos) visiveis para o usuario
    logado: EXPERT ve tudo (acompanhamento); demais niveis veem so' os tickets em
    que sao o owner (quem precisa agir). ON e' exclusivo de EXPERT (premissa de RH
    sem owner)."""
    try:
        tickets = (
            Ticket.query
            .filter(Ticket.premise_type.in_(TICKET_TYPES))
            .filter(or_(
                Ticket.premise_status.is_(None),
                db.func.upper(Ticket.premise_status) != "FINALIZADA",
            ))
            .all()
        )
    except Exception:
        db.session.rollback()
        return None  # tabela 'tickets' indisponivel nesta FC (integracao externa nao provisionada)

    try:
        _sincronizar_tickets_por_acoes(tickets)
    except Exception:
        # A leitura dos tickets continua disponivel mesmo que um historico legado
        # incompleto nao possa ser validado automaticamente.
        db.session.rollback()

    login_atual = (current_user.login or "").strip().lower()
    visiveis = []
    for t in tickets:
        if t.hcview_resolvido:
            continue
        if current_user.is_admin:
            visiveis.append(t)
            continue
        if t.premise_type == "ON":
            continue
        owner = (t.owner_login or "").strip().lower()
        if owner and owner == login_atual:
            visiveis.append(t)

    visiveis.sort(key=lambda t: t.prazo or t.work_date or date.max)
    return visiveis


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
    return render_template("atualizar.html", cargos=CARGOS, areas=AREAS, turnos=TURNOS, status_list=STATUS, processos=PROCESSOS)


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
    _reset_chamada_por_virada_de_turno()
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
        cargo=_formatar_cargo(data.get("cargo")),
        area=(data.get("area") or "").strip() or None,
        turno=None,
        status="Treinamento",
        presente_fc=_parse_bool(data.get("presente_fc"), default=True),
        presenca_manual="presente_fc" in data,
        job=_formatar_job(data.get("job")),
        hora_extra_turno=_formatar_turno_extra(data.get("hora_extra_turno")),
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
            "presente_fc": colaborador.presente_fc,
            "job": colaborador.job or "",
            "hora_extra_turno": colaborador.hora_extra_turno or "",
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
        "status_agendado": colaborador.status_agendado or "",
        "off_origem": colaborador.off_origem or "",
        "causa_afastamento": colaborador.causa_afastamento or "",
        "status_temporario_inicio": colaborador.status_temporario_inicio.isoformat() if colaborador.status_temporario_inicio else "",
        "status_temporario_fim": colaborador.status_temporario_fim.isoformat() if colaborador.status_temporario_fim else "",
        "vte_area_origem": colaborador.vte_area_origem or "",
        "vte_turno_origem": colaborador.vte_turno_origem or "",
        "vte_area_destino": colaborador.vte_area_destino or "",
        "vte_turno_destino": colaborador.vte_turno_destino or "",
    })

    novo_login = (data.get("login") or "").strip() or None
    if novo_login and novo_login != colaborador.login:
        existe_login = HCGig2.query.filter(HCGig2.login == novo_login, HCGig2.id != item_id).first()
        if existe_login:
            return jsonify({"erro": "Já existe outro colaborador com esse login."}), 409

    novo_status = (data.get("status") or colaborador.status).strip()

    if novo_status in ("VTE", "VTO") and novo_status != colaborador.status:
        return jsonify({"erro": f"O status {novo_status} só pode ser aplicado pela validação de um ticket de RH."}), 400

    status_anterior          = colaborador.status
    status_agendado_anterior = colaborador.status_agendado
    preserva_temporario = (
        novo_status == status_anterior
        and (status_anterior in ("VTE", "VTO") or colaborador.status_agendado in ("VTE", "VTO"))
    )

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
    colaborador.cargo         = _formatar_cargo(data.get("cargo") or colaborador.cargo)
    colaborador.area          = (data.get("area") or "").strip() or None
    colaborador.turno         = (data.get("turno") or "").strip() or None
    if "presente_fc" in data:
        colaborador.presente_fc = _parse_bool(data.get("presente_fc"), default=True)
        colaborador.presenca_manual = True
    colaborador.job           = _formatar_job(data.get("job", colaborador.job))
    colaborador.hora_extra_turno = _formatar_turno_extra(data.get("hora_extra_turno", colaborador.hora_extra_turno))
    colaborador.causa_afastamento = (data.get("causa_afastamento") or "").strip() or None

    hoje = date.today()
    # Qualquer edição manual resolve uma eventual pendência de "OFF por prazo vencido".
    colaborador.off_origem = None

    # Licença/Férias/Desligado só passam a valer de fato quando a data marcada chega;
    # até lá o colaborador continua com o status atual e a mudança fica "agendada".
    if novo_status in ("Licença", "Férias"):
        colaborador.limpar_status_temporario()
        data_inicio = _parse_date(data.get("data_inicio_licenca"))
        data_fim    = _parse_date(data.get("data_fim_licenca"))
        colaborador.data_inicio_licenca = data_inicio
        colaborador.data_fim_licenca    = data_fim
        colaborador.data_desligamento   = None
        if data_inicio and data_inicio > hoje:
            colaborador.status_agendado = novo_status
        else:
            colaborador.status = novo_status
            colaborador.status_agendado = None
    elif novo_status == "Desligado":
        colaborador.limpar_status_temporario()
        data_deslig = _parse_date(data.get("data_desligamento"))
        colaborador.data_desligamento   = data_deslig
        colaborador.data_inicio_licenca = None
        colaborador.data_fim_licenca    = None
        if data_deslig and data_deslig > hoje:
            colaborador.status_agendado = "Desligado"
        else:
            colaborador.status = novo_status
            colaborador.status_agendado = None
    elif preserva_temporario:
        colaborador.status = novo_status
    else:
        colaborador.limpar_status_temporario()
        colaborador.status            = novo_status
        colaborador.status_agendado   = None
        colaborador.data_inicio_licenca = None
        colaborador.data_fim_licenca    = None
        colaborador.data_desligamento   = None
        if novo_status in ("Ausência", "Ausencia"):
            # Ausência dura 24h: marca hoje e a rotina automática devolve para
            # OPERACIONAL a partir do dia seguinte (ver aplicar_status_por_data).
            if status_anterior not in ("Ausência", "Ausencia") or not colaborador.data_inicio_ausencia:
                colaborador.data_inicio_ausencia = hoje
        else:
            colaborador.data_inicio_ausencia = None

    if colaborador.status == "Treinamento":
        colaborador.turno = _turno_inicial(colaborador.cargo, colaborador.turno)

    colaborador.aplicar_status_por_data()

    dados_nov = json.dumps({
        "nome_completo": colaborador.nome_completo,
        "login": colaborador.login or "",
        "cargo": colaborador.cargo,
        "area": colaborador.area or "",
        "turno": colaborador.turno or "",
        "status": colaborador.status,
        "status_agendado": colaborador.status_agendado or "",
        "presente_fc": colaborador.presente_fc,
        "job": colaborador.job or "",
        "hora_extra_turno": colaborador.hora_extra_turno or "",
        "causa_afastamento": colaborador.causa_afastamento or "",
        "status_temporario_inicio": colaborador.status_temporario_inicio.isoformat() if colaborador.status_temporario_inicio else "",
        "status_temporario_fim": colaborador.status_temporario_fim.isoformat() if colaborador.status_temporario_fim else "",
        "vte_area_origem": colaborador.vte_area_origem or "",
        "vte_turno_origem": colaborador.vte_turno_origem or "",
        "vte_area_destino": colaborador.vte_area_destino or "",
        "vte_turno_destino": colaborador.vte_turno_destino or "",
    })

    status_final = colaborador.status
    partes_status = []
    if status_anterior != status_final:
        partes_status.append(f"status: {status_anterior} → {status_final}")
    if status_agendado_anterior != colaborador.status_agendado:
        if colaborador.status_agendado:
            data_ref = (
                colaborador.data_desligamento
                if colaborador.status_agendado == "Desligado"
                else colaborador.data_inicio_licenca
            )
            data_txt = data_ref.strftime("%d/%m/%Y") if data_ref else "data indefinida"
            partes_status.append(f"{colaborador.status_agendado} agendado(a) para {data_txt}")
        else:
            partes_status.append("agendamento cancelado")
    antes_dict = _json_dict(dados_ant)
    depois_dict = _json_dict(dados_nov)
    partes_movimentacao = []
    if antes_dict.get("area") != depois_dict.get("area"):
        partes_movimentacao.append(f"setor: {antes_dict.get('area') or '-'} → {depois_dict.get('area') or '-'}")
    if antes_dict.get("turno") != depois_dict.get("turno"):
        partes_movimentacao.append(f"turno/escala: {antes_dict.get('turno') or '-'} → {depois_dict.get('turno') or '-'}")
    if antes_dict.get("cargo") != depois_dict.get("cargo"):
        partes_movimentacao.append(f"cargo: {antes_dict.get('cargo') or '-'} → {depois_dict.get('cargo') or '-'}")
    detalhes = partes_movimentacao + partes_status
    msg_status = f" ({'; '.join(detalhes)})" if detalhes else ""
    tipo = "edicao_status" if partes_status else "edicao"
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


@hc_bp.route("/api/hc/<int:item_id>/alocacao", methods=["PATCH"])
@login_required
def atualizar_alocacao(item_id):
    if not current_user.can_edit:
        return jsonify({"erro": "Sem permissao para atualizar alocacao."}), 403

    colaborador = HCGig2.query.get_or_404(item_id)
    data = request.get_json() or {}

    dados_ant = json.dumps({
        "presente_fc": colaborador.presente_fc,
        "job": colaborador.job or "",
        "hora_extra_turno": colaborador.hora_extra_turno or "",
    })

    if "presente_fc" in data:
        colaborador.presente_fc = _parse_bool(data.get("presente_fc"), default=True)
        colaborador.presenca_manual = True
    if "job" in data:
        colaborador.job = _formatar_job(data.get("job"))
    if "hora_extra_turno" in data:
        colaborador.hora_extra_turno = _formatar_turno_extra(data.get("hora_extra_turno"))

    dados_nov = json.dumps({
        "presente_fc": colaborador.presente_fc,
        "job": colaborador.job or "",
        "hora_extra_turno": colaborador.hora_extra_turno or "",
    })

    _registrar(
        "edicao",
        colaborador,
        f"Chamada/job/hora extra atualizados: {colaborador.nome_completo}",
        dados_ant=dados_ant,
        dados_nov=dados_nov,
    )

    db.session.commit()
    return jsonify({"mensagem": "Alocacao atualizada.", "item": colaborador.to_dict()})


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

    pendentes = HCGig2.query.filter(_pendencia_filtro()).order_by(HCGig2.nome_completo.asc()).all()
    tickets = _tickets_visiveis()
    total_tickets = len(tickets) if tickets is not None else 0

    return jsonify({
        "pendencias": [
            {
                **p.to_dict(),
                "pendencia_tipo": "turno" if p.status == "OPERACIONAL" and p.cargo == "PIT" and not p.turno else "data",
            }
            for p in pendentes
        ],
        "total": len(pendentes) + total_tickets,
        "total_colaboradores": len(pendentes),
        "total_tickets": total_tickets,
        "prazo": proxima_terca.strftime("%d/%m/%Y"),
        "prazo_vencido": prazo_vencido,
    })


@hc_bp.route("/api/hc/tickets-pendentes", methods=["GET"])
@login_required
def listar_tickets_pendentes():
    if not current_user.can_edit:
        return jsonify({"erro": "Sem permissao."}), 403

    visiveis = _tickets_visiveis()
    if visiveis is None:
        return jsonify({"tickets": [], "total": 0, "integracao_disponivel": False})

    itens = []
    for t in visiveis:
        item = t.to_dict()
        item["resolver_url"] = _ticket_resolver_url(t)
        item["progresso"] = len(_acoes_validas_ticket(t))
        item["quantidade_necessaria"] = max(t.amount or 1, 1)
        if t.is_transferencia:
            item["origem_escala"] = _ticket_escala_lado(
                t.source_responsible_login, t.source_shift_name, t.source_shift_key
            )
            item["destino_escala"] = _ticket_escala_lado(
                t.responsible_login, t.shift_name, t.shift_key
            )
            src_cargo = (t.source_labor_type or "").strip()
            dst_cargo = (t.labor_type or "").strip()
            if src_cargo and dst_cargo and src_cargo.lower() != dst_cargo.lower():
                item["cargo_label"] = f"{src_cargo} → {dst_cargo}"
            else:
                item["cargo_label"] = src_cargo or dst_cargo
        else:
            item["origem_escala"] = ""
            item["destino_escala"] = _ticket_escala_lado(
                t.responsible_login, t.shift_name, t.shift_key
            )
            item["cargo_label"] = (t.labor_type or "").strip()
        itens.append(item)

    return jsonify({"tickets": itens, "total": len(itens), "integracao_disponivel": True})


@hc_bp.route("/api/hc/tickets/<int:premise_id>/resolver", methods=["POST"])
@login_required
def resolver_ticket(premise_id):
    if not current_user.can_edit:
        return jsonify({"erro": "Sem permissao."}), 403

    ticket = Ticket.query.get_or_404(premise_id)
    eh_expert = current_user.is_admin

    if ticket.premise_type == "ON":
        if not eh_expert:
            return jsonify({"erro": "Somente nivel EXPERT pode concluir premissas ON."}), 403
    elif not eh_expert:
        owner = (ticket.owner_login or "").strip().lower()
        if not owner or owner != (current_user.login or "").strip().lower():
            return jsonify({"erro": "Somente o responsavel pelo ticket ou um EXPERT pode concluir."}), 403

    resolvido, progresso, necessarias = _concluir_ticket_se_validado(ticket, verbose=True)
    if not resolvido:
        return jsonify({
            "erro": (
                "A acao correspondente ainda nao foi localizada no historico do HC. "
                f"Progresso validado: {progresso}/{necessarias}."
            ),
            "progresso": progresso,
            "quantidade_necessaria": necessarias,
        }), 409

    db.session.commit()
    return jsonify({
        "mensagem": f"Ticket concluido: {progresso}/{necessarias} acao(oes) validada(s).",
        "item": ticket.to_dict(),
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


@hc_bp.route("/api/admin/migrar-portal-tickets", methods=["POST"])
@login_required
def migrar_portal_tickets():
    if not current_user.is_admin:
        return jsonify({"erro": "Acesso negado."}), 403
    from app import _migrate_portal_ticket_claims_for_fc
    from models import get_current_fc
    fc = get_current_fc()
    try:
        _migrate_portal_ticket_claims_for_fc(fc)
        return jsonify({"mensagem": f"Tabela portal_ticket_claims criada/verificada para {fc}."})
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
        df = _read_csv_upload(arquivo)
    except Exception as e:
        return jsonify({"erro": f"Erro ao ler CSV: {str(e)}"}), 400

    col_nome = _find_col(df, "nome")
    col_login = _find_col(df, "login")
    col_cargo = _find_col(df, "cargo")
    col_area = _find_col(df, "area")
    col_turno = _find_col(df, "turno")
    col_presente = _find_col(df, "presente") or _find_col(df, "chamada") or _find_col(df, "fc")
    col_job = _find_col(df, "job") or _find_col(df, "processo")
    col_he = _find_col(df, "hora extra") or _find_col(df, "he turno") or _find_col(df, "turno extra")
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

    jobs_por_login, jobs_por_nome = _mapear_jobs_existentes()

    # Apaga todos os colaboradores existentes antes de inserir os novos
    HCGig2.query.delete()

    inseridos = 0
    processos_preservados = 0
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

            cargo = _formatar_cargo(row.get(col_cargo, "")) if col_cargo else ""

            area = str(row.get(col_area, "")).strip() if col_area else ""
            area = None if area.lower() in ("nan", "none", "") else area

            turno = str(row.get(col_turno, "")).strip() if col_turno else ""
            turno = None if turno.lower() in ("nan", "none", "") else turno

            presente_fc = _parse_bool(row.get(col_presente), default=True) if col_presente else True
            job = _formatar_job(row.get(col_job, "")) if col_job else None
            job, preservou_job = _job_importado_ou_preservado(job, login, nome, jobs_por_login, jobs_por_nome)
            if preservou_job:
                processos_preservados += 1
            hora_extra_turno = _formatar_turno_extra(row.get(col_he, "")) if col_he else None

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
            item.presente_fc = presente_fc
            item.presenca_manual = bool(col_presente)
            item.job = job
            item.hora_extra_turno = hora_extra_turno
            item.previsao_afastamento = previsao
            item.causa_afastamento = causa
            item.status_liberacao = status_lib
            item.aplicar_status_por_data()

        except Exception as e:
            erros.append(f"Linha {idx + 2}: {str(e)}")

    db.session.commit()
    result = {
        "mensagem": "Base renovada com sucesso.",
        "inseridos": inseridos,
        "processos_preservados": processos_preservados,
    }
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
    processos_preservados = 0

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

        job_existente = _formatar_job(item.job)
        item.nome_completo = str(row[normalizadas["nome_completo"]]).strip()
        item.cargo = _formatar_cargo(row[normalizadas["cargo"]])
        item.area = str(row[normalizadas["area"]]).strip() or None
        turno = str(row[normalizadas["turno"]]).strip() or None
        item.status = str(row[normalizadas["status"]]).strip() or "OPERACIONAL"
        item.turno = _turno_inicial(item.cargo, turno) if item.status == "Treinamento" else turno
        col_presente = (
            normalizadas.get("presente_fc")
            or normalizadas.get("presente fc")
            or normalizadas.get("presenca")
            or normalizadas.get("presença")
            or normalizadas.get("chamada")
        )
        col_job = normalizadas.get("job") or normalizadas.get("processo")
        col_he = normalizadas.get("hora_extra_turno") or normalizadas.get("hora extra") or normalizadas.get("he turno") or normalizadas.get("turno extra")
        item.presente_fc = _parse_bool(row[col_presente], default=True) if col_presente else True
        item.presenca_manual = bool(col_presente)
        job_importado = _formatar_job(row[col_job]) if col_job else None
        item.job = job_importado or job_existente
        if not job_importado and job_existente:
            processos_preservados += 1
        item.hora_extra_turno = _formatar_turno_extra(row[col_he]) if col_he else None
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

    nome = request.args.get("nome", "").strip().lower()
    login = request.args.get("login", "").strip().lower()
    cargo = request.args.get("cargo", "").strip()
    area = request.args.get("area", "").strip()
    turno = request.args.get("turno", "").strip()
    status = request.args.get("status", "").strip()

    registros = [
        r for r in registros
        if (not nome or nome in (r.nome_completo or "").lower())
        and (not login or login in (r.login or "").lower())
        and (not cargo or (r.cargo or "") == cargo)
        and (not area or (r.area or "") == area)
        and (not turno or (r.turno or "") == turno)
        and (not status or (r.status or "") == status)
    ]

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
            "Chamada": "SIM" if d["presente_fc"] else "NAO",
            "Job": d["job"],
            "Hora Extra Turno": d["hora_extra_turno"],
            "Status Liberação": d["status_liberacao"],
            "Previsão Afastamento": "SIM" if d["previsao_afastamento"] else "NÃO",
            "Data Afastamento": d["data_afastamento"] or "",
            "Descrição": d["causa_afastamento"] or "",
            "Criado em": d["created_at"] or "",
            "Atualizado em": d["updated_at"] or "",
        })

    df = pd.DataFrame(dados)

    fc_exportacao = _identificador_fc_exportacao()
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=f"HC_{fc_exportacao.upper()}")
    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name=f"hc_{fc_exportacao}.xlsx",
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
    f_produtividade = request.args.get("produtividade", "").strip().upper()

    hc_por_login = {
        (r.login or "").strip().lower(): r
        for r in HCGig2.query.all()
        if (r.login or "").strip()
    }

    registros = LCAtual.query.order_by(LCAtual.login.asc(), LCAtual.process_name.asc()).all()
    registros = [r for r in registros if (r.login or "").strip().lower() in hc_por_login]
    logins_produtivos = {(r.login or "").strip().lower() for r in registros if (r.login or "").strip()}
    hc_aa_operacionais = {
        login_key: hc_ref for login_key, hc_ref in hc_por_login.items()
        if hc_ref.status == "OPERACIONAL" and _cargo_eh(hc_ref.cargo, "AA", "Associado")
    }
    total_produtivos = len(set(hc_aa_operacionais) & logins_produtivos)
    total_improdutivos = len(set(hc_aa_operacionais) - logins_produtivos)
    dados = []

    for r in registros:
        login_key = (r.login or "").strip().lower()
        hc_ref = hc_por_login.get(login_key)

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
            "produtividade": "PRODUTIVO",
        }

        if f_produtividade == "IMPRODUTIVO":
            continue

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

    # AA/Associado operacional no HC e ausente da base atual de LC.
    if f_produtividade != "PRODUTIVO":
        for login_key, hc_ref in hc_por_login.items():
            if login_key in logins_produtivos:
                continue
            if hc_ref.status != "OPERACIONAL" or not _cargo_eh(hc_ref.cargo, "AA", "Associado"):
                continue
            item = {
                "id": None,
                "login": hc_ref.login or "",
                "process_name": "",
                "lc_level": "",
                "created_at": None,
                "updated_at": None,
                "nome_completo": hc_ref.nome_completo or "",
                "cargo": hc_ref.cargo or "",
                "area": hc_ref.area or "",
                "turno": hc_ref.turno or "",
                "status": hc_ref.status or "",
                "hc_encontrado": True,
                "produtividade": "IMPRODUTIVO",
            }
            if f_process or f_level:
                continue
            if f_login and f_login not in login_key:
                continue
            if f_area and (hc_ref.area or "") != f_area:
                continue
            if f_turno and (hc_ref.turno or "") != f_turno:
                continue
            if f_status and (hc_ref.status or "") != f_status:
                continue
            if f_cargo and (hc_ref.cargo or "") != f_cargo:
                continue
            if termo and termo not in " ".join(str(v) for v in item.values()).lower():
                continue
            dados.append(item)

    filtros = {
        "processos": sorted({r.process_name for r in registros if r.process_name}),
        "levels": sorted({r.lc_level for r in registros if r.lc_level}),
        "areas": sorted({r.area for r in hc_por_login.values() if r.area}),
        "turnos": sorted({r.turno for r in hc_por_login.values() if r.turno}),
        "status": sorted({r.status for r in hc_por_login.values() if r.status}),
        "cargos": ["AA", "Associado", "PIT"],
    }

    return jsonify({
        "registros": dados,
        "total": len(dados),
        "resumo": {
            "produtivos": total_produtivos,
            "improdutivos": total_improdutivos,
        },
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
        df = _read_lc_upload(arquivo)
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
        descartados_sem_hc = 0
        erros = []
        logins_hc = {
            (item.login or "").strip().lower()
            for item in HCGig2.query.all()
            if (item.login or "").strip()
        }

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

                if login.lower() not in logins_hc:
                    descartados_sem_hc += 1
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
        "mensagem": "Base de LC renovada com sucesso.",
        "inseridos": inseridos,
        "ignorados": ignorados,
        "descartados_sem_hc": descartados_sem_hc,
    }
    if erros:
        result["erros"] = erros
    return jsonify(result)


@hc_bp.route("/api/lc/export", methods=["GET"])
@login_required
def exportar_lc_excel():
    registros = LCAtual.query.order_by(LCAtual.login.asc(), LCAtual.process_name.asc()).all()
    logins_hc = {
        (item.login or "").strip().lower()
        for item in HCGig2.query.all()
        if (item.login or "").strip()
    }
    registros = [r for r in registros if (r.login or "").strip().lower() in logins_hc]
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


# ── API: Tickets RH (VTO / VTE) ──────────────────────────────


def _inicio_status_ticket_rh(ticket, data_inicio=None):
    """Converte a data local do ticket para UTC; hoje/passado inicia imediatamente."""
    agora_utc = datetime.utcnow()
    hoje_local = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    inicio_data = _parse_date(data_inicio) or ticket.work_date
    if not inicio_data or inicio_data <= hoje_local:
        return agora_utc
    inicio_local = datetime.combine(inicio_data, datetime.min.time()).replace(
        tzinfo=ZoneInfo("America/Sao_Paulo")
    )
    return inicio_local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)


def _destino_vte(ticket, hc):
    area = _match_valor_conhecido(ticket.sector_key, AREAS)
    if not area:
        area = (ticket.sector_key or "").strip().upper()

    candidatos_turno = (ticket.shift_key, ticket.shift_name)
    turno = next(
        (_match_valor_conhecido(valor, TURNOS) for valor in candidatos_turno if _match_valor_conhecido(valor, TURNOS)),
        "",
    )
    if not turno:
        parcial = next(
            (_turno_normalizado(valor) for valor in candidatos_turno if _turno_normalizado(valor) in ("day", "night")),
            "",
        )
        origem = _turno_normalizado(hc.turno)
        cor = "BLUE" if origem.startswith("blue") else "RED" if origem.startswith("red") else ""
        if parcial and cor:
            turno = f"{cor} {parcial.upper()}"
        elif ticket.shift_name or ticket.shift_key:
            turno = (ticket.shift_name or ticket.shift_key).strip().upper()
    return area, turno


def _dados_status_temporario(hc):
    return {
        "cargo": hc.cargo or "",
        "area": hc.area or "",
        "turno": hc.turno or "",
        "status": hc.status,
        "status_agendado": hc.status_agendado or "",
        "status_temporario_inicio": hc.status_temporario_inicio.isoformat() if hc.status_temporario_inicio else "",
        "status_temporario_fim": hc.status_temporario_fim.isoformat() if hc.status_temporario_fim else "",
    }


@hc_bp.route("/api/rh-tickets", methods=["GET"])
@login_required
def listar_rh_tickets():
    from models.portal_ticket_claims import CLAIM_TYPES, PortalTicketClaim
    try:
        tickets = (
            PortalTicketClaim.query
            .filter(
                PortalTicketClaim.premise_type.in_(CLAIM_TYPES),
                PortalTicketClaim.cancelled_at.is_(None),
                db.or_(
                    PortalTicketClaim.hcview_resolvido.is_(None),
                    PortalTicketClaim.hcview_resolvido == False,  # noqa: E712
                ),
                db.func.lower(PortalTicketClaim.status) == "ativo",
            )
            .order_by(PortalTicketClaim.created_at.asc())
            .all()
        )
    except Exception:
        db.session.rollback()
        return jsonify([])

    # Enriquece com dados do HC pelo associado_id
    hc_por_id = {
        r.id: r for r in HCGig2.query.all()
    }

    resultado = []
    for t in tickets:
        item = t.to_dict()
        hc = hc_por_id.get(t.associado_id)
        item["solicitante_nome"] = hc.nome_completo if hc else f"ID {t.associado_id}"
        item["solicitante_login"] = hc.login or "" if hc else ""
        item["solicitante_cargo"] = hc.cargo or "" if hc else ""
        item["solicitante_area"] = hc.area or "" if hc else ""
        item["solicitante_turno"] = hc.turno or "" if hc else ""
        # RME responsável: busca pelo setor_key do ticket
        rme = HCGig2.query.filter(
            HCGig2.area == "RME",
            HCGig2.status == "OPERACIONAL",
        ).first()
        item["rme_responsavel_nome"] = rme.nome_completo if rme else ""
        item["rme_responsavel_login"] = rme.login or "" if rme else ""
        # URL para resolver pendência direto no login
        item["resolver_url"] = f"/atualizar?login={item['solicitante_login']}" if item["solicitante_login"] else "/atualizar"
        resultado.append(item)

    # Filtra por RME se não for admin
    if not current_user.is_admin:
        login_atual = (current_user.login or "").strip().lower()
        resultado = [
            item for item in resultado
            if (item["rme_responsavel_login"] or "").strip().lower() == login_atual
        ]

    return jsonify(resultado)


@hc_bp.route("/api/rh-tickets/<int:ticket_id>/resolver", methods=["POST"])
@login_required
def resolver_rh_ticket(ticket_id):
    from models.portal_ticket_claims import PortalTicketClaim
    try:
        ticket = PortalTicketClaim.query.get_or_404(ticket_id)
    except Exception:
        db.session.rollback()
        return jsonify({"erro": "Tabela portal_ticket_claims indisponível."}), 503

    if ticket.hcview_resolvido:
        return jsonify({"erro": "Ticket já resolvido."}), 409
    if ticket.cancelled_at:
        return jsonify({"erro": "Ticket cancelado pela ferramenta de origem."}), 409

    if not current_user.can_edit:
        return jsonify({"erro": "Sem permissão para validar tickets RH."}), 403

    hc = HCGig2.query.get(ticket.associado_id) if ticket.associado_id else None
    data = request.get_json() or {}
    acao = (data.get("acao") or "resolver").lower()

    if acao == "rejeitar":
        ticket.hcview_resolvido = True
        ticket.hcview_resolvido_em = datetime.utcnow()
        ticket.hcview_resolvido_por_login = current_user.login
        ticket.hcview_resolvido_por_nome = current_user.nome
        ticket.hcview_observacao = f"[REJEITADO] {data.get('observacao') or ''}"
        db.session.commit()
        return jsonify({"mensagem": "Ticket rejeitado.", "item": ticket.to_dict()})

    # ── Aplicar regras de negócio ──────────────────────────────────────────
    tipo = (ticket.premise_type or "").upper()
    if tipo not in ("VTE", "VTO"):
        return jsonify({"erro": f"Tipo de ticket RH não suportado: {tipo or 'vazio'}."}), 422
    if not hc:
        return jsonify({"erro": "Colaborador do ticket não foi localizado no HC Overview."}), 404
    if hc.status in ("VTE", "VTO") or hc.status_agendado in ("VTE", "VTO"):
        return jsonify({"erro": "O colaborador já possui um VTE/VTO ativo ou agendado."}), 409

    inicio = _inicio_status_ticket_rh(ticket, data.get("data_inicio"))
    fim = inicio + timedelta(hours=12)
    agora = datetime.utcnow()
    agendado = inicio > agora
    dados_ant = json.dumps(_dados_status_temporario(hc))

    hc.status_temporario_inicio = inicio
    hc.status_temporario_fim = fim
    hc.status_agendado = tipo if agendado else None

    if tipo == "VTE":
        area_destino, turno_destino = _destino_vte(ticket, hc)
        if not area_destino or not turno_destino:
            return jsonify({"erro": "O ticket VTE não possui setor e escala de destino válidos."}), 422
        ticket.hcview_area_origem = hc.area
        ticket.hcview_turno_origem = hc.turno
        ticket.hcview_vte_revertido = False
        hc.vte_area_origem = hc.area
        hc.vte_turno_origem = hc.turno
        hc.vte_area_destino = area_destino
        hc.vte_turno_destino = turno_destino
        if not agendado:
            hc.area = area_destino
            hc.turno = turno_destino
    else:
        hc.vte_area_origem = None
        hc.vte_turno_origem = None
        hc.vte_area_destino = None
        hc.vte_turno_destino = None

    if not agendado:
        hc.status = tipo

    dados_nov = json.dumps(_dados_status_temporario(hc))
    inicio_local = inicio.replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo("America/Sao_Paulo"))
    fim_local = fim.replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo("America/Sao_Paulo"))
    if agendado:
        descricao = f"Ticket RH {tipo} #{ticket.id} agendado para {inicio_local.strftime('%d/%m/%Y %H:%M')}"
        if tipo == "VTE":
            descricao += (
                f"; setor/escala: {hc.vte_area_origem or '-'} / {hc.vte_turno_origem or '-'}"
                f" → {hc.vte_area_destino or '-'} / {hc.vte_turno_destino or '-'}"
            )
    else:
        descricao = f"Ticket RH {tipo} #{ticket.id} aplicado: status → {tipo}"
        if tipo == "VTE":
            descricao += (
                f"; setor/escala: {hc.vte_area_origem or '-'} / {hc.vte_turno_origem or '-'}"
                f" → {hc.area or '-'} / {hc.turno or '-'}"
            )
    descricao += f"; retorno automático para OPERACIONAL em {fim_local.strftime('%d/%m/%Y %H:%M')}"
    _registrar("edicao_status", hc, descricao, dados_ant=dados_ant, dados_nov=dados_nov)

    ticket.hcview_resolvido = True
    ticket.hcview_resolvido_em = datetime.utcnow()
    ticket.hcview_resolvido_por_login = current_user.login
    ticket.hcview_resolvido_por_nome = current_user.nome
    ticket.hcview_observacao = data.get("observacao") or ""
    db.session.commit()
    acao_label = "agendado" if agendado else "aplicado"
    return jsonify({
        "mensagem": f"Ticket {tipo} validado e {acao_label}. Retorno automático configurado para 12h.",
        "item": ticket.to_dict(),
        "colaborador": hc.to_dict(),
    })


# ── API: Dashboard ─────────────────────────────────────────────


@hc_bp.route("/api/hc/dashboard", methods=["GET"])
@login_required
def dashboard_data():
    # Cada filtro aceita múltiplos valores separados por vírgula (multi-filtro via Ctrl+clique no front).
    f_area   = _parse_multi_filtro(request.args.get("area", ""))
    f_turno  = _parse_multi_filtro(request.args.get("turno", ""))
    f_status = _parse_multi_filtro(request.args.get("status", ""))
    f_cargo  = _parse_multi_filtro(request.args.get("cargo", ""))

    todos = HCGig2.query.all()
    _aplicar_regra_hc_atual(todos)

    registros = todos
    if f_area:
        registros = [r for r in registros if (r.area or "") in f_area]
    if f_turno:
        registros = [r for r in registros if (r.turno or "") in f_turno]
    if f_status:
        registros = [r for r in registros if r.status in f_status]
    if f_cargo:
        registros = [r for r in registros if r.cargo in f_cargo]

    total      = len(registros)
    operacional = sum(1 for r in registros if r.status == "OPERACIONAL")
    off        = sum(1 for r in registros if r.status == "OFF")
    treinamento = sum(1 for r in registros if r.status == "Treinamento")
    ausencia   = sum(1 for r in registros if r.status in ("Ausência", "Ausencia"))
    licenca    = sum(1 for r in registros if r.status == "Licença")
    ferias     = sum(1 for r in registros if r.status == "Férias")
    vte        = sum(1 for r in registros if r.status == "VTE")
    vto        = sum(1 for r in registros if r.status == "VTO")

    outbound_areas = {"OUTBOUND", "TRANSFER OUT", "INSUMOS", "LP"}
    inbound_areas  = {"INBOUND", "TRANSFER IN", "TRANSFERIN", "C-RET"}
    icqa_areas     = {"ICQA"}

    por_area  = {}
    por_cargo = {}
    por_turno = {}

    def _conta_no_turno(registro, turno):
        return registro.turno == turno

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
            "AA": sum(1 for r in registros if _conta_no_turno(r, turno) and _cargo_eh(r.cargo, "AA")),
            "Associado": sum(1 for r in registros if _conta_no_turno(r, turno) and _cargo_eh(r.cargo, "Associado")),
            "PIT":       sum(1 for r in registros if _conta_no_turno(r, turno) and _cargo_eh(r.cargo, "PIT")),
        }

    operacional_por_turno = {}
    for turno in TURNOS:
        if turno == "ADM":
            continue
        operacional_por_turno[turno] = {
            "Analista":  sum(1 for r in registros if _conta_no_turno(r, turno) and _cargo_eh(r.cargo, "Analista")  and r.status == "OPERACIONAL"),
            "AA":        sum(1 for r in registros if _conta_no_turno(r, turno) and _cargo_eh(r.cargo, "AA")        and r.status == "OPERACIONAL"),
            "Associado": sum(1 for r in registros if _conta_no_turno(r, turno) and _cargo_eh(r.cargo, "Associado") and r.status == "OPERACIONAL"),
            "PIT":       sum(1 for r in registros if _conta_no_turno(r, turno) and _cargo_eh(r.cargo, "PIT")       and r.status == "OPERACIONAL"),
        }

    areas_disponiveis  = sorted({r.area  or "" for r in todos if r.area})
    turnos_disponiveis = sorted({r.turno for r in todos if r.turno})
    status_disponiveis = sorted({r.status for r in todos})

    hc_por_login = {
        (r.login or "").strip().lower(): r
        for r in todos
        if (r.login or "").strip()
    }

    lc_todos = LCAtual.query.all()
    lc_registros = []
    lc_logins = {(lc.login or "").strip().lower() for lc in lc_todos if (lc.login or "").strip()}

    for lc in lc_todos:
        hc_ref = hc_por_login.get((lc.login or "").strip().lower())
        if not hc_ref:
            continue

        if f_area and (hc_ref.area or "") not in f_area:
            continue
        if f_turno and (hc_ref.turno or "") not in f_turno:
            continue
        if f_status and hc_ref.status not in f_status:
            continue
        if f_cargo and hc_ref.cargo not in f_cargo:
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
    lc_improdutivos = sum(
        1 for r in registros
        if r.status == "OPERACIONAL"
        and _cargo_eh(r.cargo, "AA", "Associado")
        and (r.login or "").strip().lower() not in lc_logins
    )

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
        "status": {"OPERACIONAL": operacional, "VTE": vte, "VTO": vto, "Treinamento": treinamento, "Ausência": ausencia, "Licença": licenca, "Férias": ferias, "OFF": off},
        "associados_e_pits": associados_e_pits,
        "operacional_por_turno": operacional_por_turno,
        "filtros_disponiveis": {
            "areas":  areas_disponiveis,
            "turnos": turnos_disponiveis,
            "status": status_disponiveis,
            "cargos": ["AA", "Associado", "PIT", "Analista"],
        },
        "filtros_ativos": {"area": f_area, "turno": f_turno, "status": f_status, "cargo": f_cargo},
        "lc": {
            "cards": {
                "total_registros": len(lc_registros),
                "pessoas_com_lc": _unique_people_count(lc_registros),
                "processos": len(lc_por_processo),
                "sem_hc": lc_improdutivos,
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

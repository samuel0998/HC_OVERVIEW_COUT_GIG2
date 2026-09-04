import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, redirect, request, url_for
from flask_login import LoginManager

from config import Config
from models import db
from routes.auth import auth_bp
from routes.hc import hc_bp


def _get_last_tuesday():
    """Returns the most recent Tuesday (today if today is Tuesday)."""
    today = date.today()
    days_back = (today.weekday() - 1) % 7
    return today - timedelta(days=days_back)


def processar_status_automatico():
    """Automatic status transitions: revert leaves, deadline OFF, archive terminations."""
    from models.hc_gig2 import HCGig2
    from models.historico import HistoricoOperacional
    from models.registro_atividade import RegistroAtividade

    hoje = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    agora = datetime.utcnow()
    prazo_vencido = hoje.weekday() > 1

    todos = HCGig2.query.all()
    registros = []
    para_arquivar = []

    for op in todos:
        status_ant = op.status
        status_agendado_ant = op.status_agendado
        area_ant = op.area
        turno_ant = op.turno
        ls_retorno_data_ant = op.ls_retorno_data
        ls_ticket_id_ant = op.ls_ticket_id

        desligamento_efetivo = op.status == "Desligado" or op.status_agendado == "Desligado"
        if desligamento_efetivo and op.data_desligamento and hoje >= op.data_desligamento:
            para_arquivar.append(op)
            continue

        alterou_por_data = op.aplicar_status_por_data(hoje, agora)

        if ls_retorno_data_ant and not op.ls_retorno_data and alterou_por_data:
            registros.append(RegistroAtividade(
                tipo="retorno_ls",
                operador_id=op.id,
                operador_login=op.login,
                operador_nome=op.nome_completo,
                usuario_login="sistema",
                usuario_nome="Automacao",
                descricao=(
                    f"Retorno automático do LS #{ls_ticket_id_ant}: setor/escala "
                    f"{area_ant or '-'} / {turno_ant or '-'} → {op.area or '-'} / {op.turno or '-'}"
                ),
                dados_anteriores=json.dumps({"area": area_ant or "", "turno": turno_ant or "", "ls_retorno_data": str(ls_retorno_data_ant)}),
                dados_novos=json.dumps({"area": op.area or "", "turno": op.turno or ""}),
            ))

        if status_ant in ("VTE", "VTO") and op.status == "OPERACIONAL" and alterou_por_data:
            detalhes_retorno = ""
            if status_ant == "VTE":
                detalhes_retorno = f"; setor/escala: {area_ant or '-'} / {turno_ant or '-'} → {op.area or '-'} / {op.turno or '-'}"
            registros.append(RegistroAtividade(
                tipo="edicao_status",
                operador_id=op.id,
                operador_login=op.login,
                operador_nome=op.nome_completo,
                usuario_login="sistema",
                usuario_nome="Automacao",
                descricao=f"Retorno automático de {status_ant} para OPERACIONAL após 12h{detalhes_retorno}",
                dados_anteriores=json.dumps({"status": status_ant, "area": area_ant or "", "turno": turno_ant or ""}),
                dados_novos=json.dumps({"status": "OPERACIONAL", "area": op.area or "", "turno": op.turno or ""}),
            ))
            continue

        if status_agendado_ant in ("VTE", "VTO") and not op.status_agendado and op.status == "OPERACIONAL" and alterou_por_data:
            registros.append(RegistroAtividade(
                tipo="edicao_status",
                operador_id=op.id,
                operador_login=op.login,
                operador_nome=op.nome_completo,
                usuario_login="sistema",
                usuario_nome="Automacao",
                descricao=f"Agendamento de {status_agendado_ant} processado; a janela de 12h já havia encerrado. Status mantido em OPERACIONAL.",
                dados_anteriores=json.dumps({"status": status_ant, "status_agendado": status_agendado_ant, "area": area_ant or "", "turno": turno_ant or ""}),
                dados_novos=json.dumps({"status": "OPERACIONAL", "area": op.area or "", "turno": op.turno or ""}),
            ))
            continue

        if status_agendado_ant and not op.status_agendado and op.status == status_agendado_ant:
            detalhe_alocacao = ""
            if status_agendado_ant == "VTE":
                detalhe_alocacao = f"; setor/escala: {area_ant or '-'} / {turno_ant or '-'} → {op.area or '-'} / {op.turno or '-'}"
            registros.append(RegistroAtividade(
                tipo="edicao_status",
                operador_id=op.id,
                operador_login=op.login,
                operador_nome=op.nome_completo,
                usuario_login="sistema",
                usuario_nome="Automacao",
                descricao=f"Ativação automática: '{status_agendado_ant}' passou a valer (data agendada atingida){detalhe_alocacao}",
                dados_anteriores=json.dumps({"status": status_ant, "status_agendado": status_agendado_ant, "area": area_ant or "", "turno": turno_ant or ""}),
                dados_novos=json.dumps({"status": op.status, "area": op.area or "", "turno": op.turno or ""}),
            ))
            continue

        if status_ant in ("Licenca", "Licença", "Ferias", "Férias") and op.status == "OPERACIONAL" and alterou_por_data:
            registros.append(RegistroAtividade(
                tipo="edicao_status",
                operador_id=op.id,
                operador_login=op.login,
                operador_nome=op.nome_completo,
                usuario_login="sistema",
                usuario_nome="Automacao",
                descricao=f"Retorno automatico para OPERACIONAL - periodo de {status_ant} encerrado",
                dados_anteriores=json.dumps({"status": status_ant}),
                dados_novos=json.dumps({"status": "OPERACIONAL"}),
            ))
            continue

        if status_ant in ("Ausência", "Ausencia") and op.status == "OPERACIONAL" and alterou_por_data:
            registros.append(RegistroAtividade(
                tipo="edicao_status",
                operador_id=op.id,
                operador_login=op.login,
                operador_nome=op.nome_completo,
                usuario_login="sistema",
                usuario_nome="Automacao",
                descricao="Retorno automatico para OPERACIONAL - ausencia de 24h encerrada",
                dados_anteriores=json.dumps({"status": status_ant}),
                dados_novos=json.dumps({"status": "OPERACIONAL"}),
            ))
            continue

        if status_ant == "Treinamento" and op.status == "OPERACIONAL" and alterou_por_data:
            registros.append(RegistroAtividade(
                tipo="edicao_status",
                operador_id=op.id,
                operador_login=op.login,
                operador_nome=op.nome_completo,
                usuario_login="sistema",
                usuario_nome="Automacao",
                descricao=f"Virada automatica de Treinamento para OPERACIONAL ({op.cargo})",
                dados_anteriores=json.dumps({"status": status_ant}),
                dados_novos=json.dumps({"status": "OPERACIONAL", "turno": op.turno or ""}),
            ))

        if prazo_vencido:
            # O prazo de terca e so um alerta: quem vira OFF por falta de data continua
            # aparecendo em Pendencias (off_origem guarda de onde veio) ate alguem definir a data.
            if op.status in ("Licenca", "Licença", "Ferias", "Férias") and not op.data_inicio_licenca:
                op.off_origem = "Licença" if op.status in ("Licenca", "Licença") else "Férias"
                op.status = "OFF"
                registros.append(RegistroAtividade(
                    tipo="edicao_status",
                    operador_id=op.id,
                    operador_login=op.login,
                    operador_nome=op.nome_completo,
                    usuario_login="sistema",
                    usuario_nome="Automacao",
                    descricao=f"Status -> OFF: pendencia '{status_ant}' sem data definida (prazo terca-feira vencido; continua em Pendencias)",
                    dados_anteriores=json.dumps({"status": status_ant}),
                    dados_novos=json.dumps({"status": "OFF", "off_origem": op.off_origem}),
                ))
            elif op.status == "Desligado" and not op.data_desligamento:
                op.off_origem = "Desligado"
                op.status = "OFF"
                registros.append(RegistroAtividade(
                    tipo="edicao_status",
                    operador_id=op.id,
                    operador_login=op.login,
                    operador_nome=op.nome_completo,
                    usuario_login="sistema",
                    usuario_nome="Automacao",
                    descricao="Status -> OFF: pendencia de desligamento sem data (prazo terca-feira vencido; continua em Pendencias)",
                    dados_anteriores=json.dumps({"status": status_ant}),
                    dados_novos=json.dumps({"status": "OFF", "off_origem": op.off_origem}),
                ))

    for op in para_arquivar:
        hist = HistoricoOperacional(
            hc_id_original=op.id,
            nome_completo=op.nome_completo,
            login=op.login,
            cargo=op.cargo,
            area=op.area,
            turno=op.turno,
            status_final="Desligado",
            data_desligamento=op.data_desligamento,
            causa=op.causa_afastamento,
            data_criacao_original=op.created_at,
            arquivado_por="sistema",
        )
        db.session.add(hist)
        registros.append(RegistroAtividade(
            tipo="desligamento_automatico",
            operador_id=op.id,
            operador_login=op.login,
            operador_nome=op.nome_completo,
            usuario_login="sistema",
            usuario_nome="Automacao",
            descricao=f"Colaborador '{op.nome_completo}' arquivado automaticamente em {op.data_desligamento}.",
        ))
        db.session.delete(op)

    for r in registros:
        db.session.add(r)

    db.session.commit()
    count = len(registros)
    if count:
        print(f"[AUTO-STATUS] {count} operacao(oes) processada(s).")
    else:
        print("[AUTO-STATUS] Nenhuma alteracao necessaria.")

def _create_operational_tables_for_fc(fc):
    engine = db.engines[fc]
    # 'tickets' e' de propriedade de uma ferramenta externa (espelha gig2_hc_premises) -
    # o HC Overview nunca cria essa tabela, so' altera (ver _migrate_tickets_table_for_fc).
    tabelas = [t for t in db.metadatas[None].tables.values() if t.name != "tickets"]
    db.metadatas[None].create_all(bind=engine, tables=tabelas)
    print(f"[MIGRATION:{fc}] Tabelas operacionais verificadas.")


def _migrate_portal_ticket_claims_for_fc(fc):
    """So' adiciona colunas hcview_* - nunca cria nem recria a tabela (ferramenta externa).
    Se a tabela nao existir nessa FC, pula sem erro."""
    engine = db.engines[fc]
    with engine.begin() as conn:
        existe = conn.execute(db.text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = 'portal_ticket_claims'"
        )).first()
        if not existe:
            print(f"[MIGRATION:{fc}] Tabela 'portal_ticket_claims' nao encontrada. Pulando.")
            return
        conn.execute(db.text("ALTER TABLE portal_ticket_claims ADD COLUMN IF NOT EXISTS hcview_resolvido BOOLEAN DEFAULT FALSE"))
        conn.execute(db.text("ALTER TABLE portal_ticket_claims ADD COLUMN IF NOT EXISTS hcview_resolvido_em TIMESTAMP"))
        conn.execute(db.text("ALTER TABLE portal_ticket_claims ADD COLUMN IF NOT EXISTS hcview_resolvido_por_login VARCHAR(50)"))
        conn.execute(db.text("ALTER TABLE portal_ticket_claims ADD COLUMN IF NOT EXISTS hcview_resolvido_por_nome VARCHAR(150)"))
        conn.execute(db.text("ALTER TABLE portal_ticket_claims ADD COLUMN IF NOT EXISTS hcview_observacao TEXT"))
        conn.execute(db.text("ALTER TABLE portal_ticket_claims ADD COLUMN IF NOT EXISTS hcview_area_origem VARCHAR(50)"))
        conn.execute(db.text("ALTER TABLE portal_ticket_claims ADD COLUMN IF NOT EXISTS hcview_turno_origem VARCHAR(50)"))
        conn.execute(db.text("ALTER TABLE portal_ticket_claims ADD COLUMN IF NOT EXISTS hcview_vte_revertido BOOLEAN DEFAULT FALSE"))
    print(f"[MIGRATION:{fc}] portal_ticket_claims colunas hcview_* verificadas.")


def _migrate_hc_table_for_fc(fc):
    engine = db.engines[fc]
    with engine.begin() as conn:
        conn.execute(db.text("ALTER TABLE hc_gig2 ADD COLUMN IF NOT EXISTS status_liberacao VARCHAR(100)"))
        conn.execute(db.text("ALTER TABLE hc_gig2 ALTER COLUMN login DROP NOT NULL"))
        conn.execute(db.text("ALTER TABLE hc_gig2 ALTER COLUMN area DROP NOT NULL"))
        conn.execute(db.text("ALTER TABLE hc_gig2 ALTER COLUMN turno DROP NOT NULL"))
        conn.execute(db.text("ALTER TABLE hc_gig2 ADD COLUMN IF NOT EXISTS presente_fc BOOLEAN DEFAULT TRUE"))
        conn.execute(db.text("ALTER TABLE hc_gig2 ALTER COLUMN presente_fc SET DEFAULT TRUE"))
        conn.execute(db.text("UPDATE hc_gig2 SET presente_fc = TRUE WHERE presente_fc IS NULL"))
        conn.execute(db.text("ALTER TABLE hc_gig2 ALTER COLUMN presente_fc SET NOT NULL"))
        conn.execute(db.text("ALTER TABLE hc_gig2 ADD COLUMN IF NOT EXISTS presenca_manual BOOLEAN DEFAULT FALSE"))
        conn.execute(db.text("ALTER TABLE hc_gig2 ALTER COLUMN presenca_manual SET DEFAULT FALSE"))
        conn.execute(db.text("UPDATE hc_gig2 SET presenca_manual = FALSE WHERE presenca_manual IS NULL"))
        conn.execute(db.text("ALTER TABLE hc_gig2 ALTER COLUMN presenca_manual SET NOT NULL"))
        conn.execute(db.text(
            "UPDATE hc_gig2 "
            "SET presente_fc = TRUE "
            "WHERE presenca_manual = FALSE "
            "AND status = 'OPERACIONAL' "
            "AND UPPER(cargo) IN ('AA', 'ASSOCIADO')"
        ))
        # AA e Associado sao o mesmo cargo; TRANSFERIN e TRANSFER IN a mesma area.
        res_cargo = conn.execute(db.text(
            "UPDATE hc_gig2 SET cargo = 'Associado' WHERE UPPER(TRIM(cargo)) = 'AA'"
        ))
        res_area = conn.execute(db.text(
            "UPDATE hc_gig2 SET area = 'TRANSFER IN' WHERE UPPER(TRIM(area)) = 'TRANSFERIN'"
        ))
        print(f"[MIGRATION:{fc}] Consolidacao: {res_cargo.rowcount} cargo(s) 'AA'->'Associado', "
              f"{res_area.rowcount} area(s) 'TRANSFERIN'->'TRANSFER IN'.")
        conn.execute(db.text("ALTER TABLE hc_gig2 ADD COLUMN IF NOT EXISTS job VARCHAR(80)"))
        conn.execute(db.text("ALTER TABLE hc_gig2 ADD COLUMN IF NOT EXISTS hora_extra_turno VARCHAR(50)"))
        conn.execute(db.text("ALTER TABLE hc_gig2 ADD COLUMN IF NOT EXISTS data_inicio_licenca DATE"))
        conn.execute(db.text("ALTER TABLE hc_gig2 ADD COLUMN IF NOT EXISTS data_fim_licenca DATE"))
        conn.execute(db.text("ALTER TABLE hc_gig2 ADD COLUMN IF NOT EXISTS data_desligamento DATE"))
        conn.execute(db.text("ALTER TABLE hc_gig2 ALTER COLUMN causa_afastamento TYPE VARCHAR(500)"))
        conn.execute(db.text("ALTER TABLE hc_gig2 ADD COLUMN IF NOT EXISTS status_agendado VARCHAR(20)"))
        print(f"[MIGRATION:{fc}] Coluna status_agendado verificada (Ferias/Licenca/Desligado agendados).")
        conn.execute(db.text("ALTER TABLE hc_gig2 ADD COLUMN IF NOT EXISTS off_origem VARCHAR(20)"))
        print(f"[MIGRATION:{fc}] Coluna off_origem verificada (OFF por prazo vencido continua em Pendencias).")
        conn.execute(db.text("ALTER TABLE hc_gig2 ADD COLUMN IF NOT EXISTS data_inicio_ausencia DATE"))
        print(f"[MIGRATION:{fc}] Coluna data_inicio_ausencia verificada (status Ausencia dura 24h e volta a OPERACIONAL no dia seguinte).")
        conn.execute(db.text("ALTER TABLE hc_gig2 ADD COLUMN IF NOT EXISTS status_temporario_inicio TIMESTAMP"))
        conn.execute(db.text("ALTER TABLE hc_gig2 ADD COLUMN IF NOT EXISTS status_temporario_fim TIMESTAMP"))
        conn.execute(db.text("ALTER TABLE hc_gig2 ADD COLUMN IF NOT EXISTS vte_area_origem VARCHAR(50)"))
        conn.execute(db.text("ALTER TABLE hc_gig2 ADD COLUMN IF NOT EXISTS vte_turno_origem VARCHAR(50)"))
        conn.execute(db.text("ALTER TABLE hc_gig2 ADD COLUMN IF NOT EXISTS vte_area_destino VARCHAR(50)"))
        conn.execute(db.text("ALTER TABLE hc_gig2 ADD COLUMN IF NOT EXISTS vte_turno_destino VARCHAR(50)"))
        print(f"[MIGRATION:{fc}] Colunas de VTE/VTO temporarios verificadas.")
        conn.execute(db.text("ALTER TABLE hc_gig2 ADD COLUMN IF NOT EXISTS ls_retorno_data DATE"))
        conn.execute(db.text("ALTER TABLE hc_gig2 ADD COLUMN IF NOT EXISTS ls_area_origem VARCHAR(50)"))
        conn.execute(db.text("ALTER TABLE hc_gig2 ADD COLUMN IF NOT EXISTS ls_turno_origem VARCHAR(50)"))
        conn.execute(db.text("ALTER TABLE hc_gig2 ADD COLUMN IF NOT EXISTS ls_ticket_id INTEGER"))
        print(f"[MIGRATION:{fc}] Colunas de retorno automatico de LS verificadas.")
        result = conn.execute(db.text(
            "SELECT column_name, data_type, is_nullable "
            "FROM information_schema.columns "
            "WHERE table_name = 'hc_gig2' "
            "ORDER BY ordinal_position"
        ))
        colunas = result.fetchall()

    print(f"=== [MIGRATION:{fc}] Estrutura atual da tabela hc_gig2 ===")
    for col in colunas:
        print(f"  {col[0]:30s} | {col[1]:20s} | nullable={col[2]}")
    print(f"=== [MIGRATION:{fc}] Concluida com sucesso ===")


def _migrate_tickets_table_for_fc(fc):
    """So' adiciona colunas hcview_* de controle - nunca cria a tabela 'tickets' (ela e'
    populada por uma ferramenta externa que espelha gig2_hc_premises). Se a tabela ainda
    nao existir nessa FC, pula sem erro: a integracao de tickets fica indisponivel ali
    ate a ferramenta externa provisiona-la."""
    engine = db.engines[fc]
    with engine.begin() as conn:
        existe = conn.execute(db.text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = 'tickets'"
        )).first()
        if not existe:
            print(f"[MIGRATION:{fc}] Tabela 'tickets' ainda nao provisionada nesta base (integracao externa). Pulando.")
            return

        conn.execute(db.text("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS hcview_resolvido BOOLEAN DEFAULT FALSE"))
        conn.execute(db.text("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS hcview_resolvido_em TIMESTAMP"))
        conn.execute(db.text("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS hcview_resolvido_por_login VARCHAR(50)"))
        conn.execute(db.text("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS hcview_resolvido_por_nome VARCHAR(150)"))
        # Gestao pelo time de Planning (LC-HARD-EXPERT): arquivar / cancelar ticket.
        conn.execute(db.text("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS hcview_arquivado BOOLEAN DEFAULT FALSE"))
        conn.execute(db.text("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS hcview_arquivado_por VARCHAR(50)"))
        conn.execute(db.text("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS hcview_arquivado_em TIMESTAMP"))
        conn.execute(db.text("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS hcview_cancelado BOOLEAN DEFAULT FALSE"))
        conn.execute(db.text("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS hcview_cancelado_por VARCHAR(50)"))
        conn.execute(db.text("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS hcview_cancelado_em TIMESTAMP"))

        result = conn.execute(db.text(
            "SELECT column_name, data_type, is_nullable "
            "FROM information_schema.columns "
            "WHERE table_name = 'tickets' AND column_name LIKE 'hcview_%' "
            "ORDER BY ordinal_position"
        ))
        colunas = result.fetchall()

    print(f"=== [MIGRATION:{fc}] Colunas hcview_* na tabela tickets ===")
    for col in colunas:
        print(f"  {col[0]:30s} | {col[1]:20s} | nullable={col[2]}")
    print(f"=== [MIGRATION:{fc}] Concluida com sucesso ===")


def _migrate_lc_table_for_fc(fc):
    engine = db.engines[fc]
    with engine.begin() as conn:
        conn.execute(db.text("ALTER TABLE lc_atual ADD COLUMN IF NOT EXISTS week VARCHAR(20)"))
        conn.execute(db.text("ALTER TABLE lc_atual ADD COLUMN IF NOT EXISTS fc VARCHAR(20)"))
        conn.execute(db.text("ALTER TABLE lc_atual ADD COLUMN IF NOT EXISTS rate_na_lc VARCHAR(50)"))
        conn.execute(db.text("ALTER TABLE lc_atual ADD COLUMN IF NOT EXISTS horas_processo DOUBLE PRECISION"))


def _migrate_operadores_table():
    db.metadatas["GIG2"].create_all(bind=db.engines["GIG2"])
    with db.engines["GIG2"].begin() as conn:
        conn.execute(db.text("ALTER TABLE operadores ADD COLUMN IF NOT EXISTS permission_hcview BOOLEAN DEFAULT FALSE"))
        conn.execute(db.text("ALTER TABLE operadores ADD COLUMN IF NOT EXISTS permission_level_hcview VARCHAR(20)"))
    print("[MIGRATION:GIG2] Tabela central de operadores verificada.")


def _bootstrap_databases(app):
    fc_keys = [
        fc
        for fc, fc_data in app.config["FC_DATABASES"].items()
        if fc_data.get("bootstrap_on_startup", True)
    ]

    for fc in fc_keys:
        try:
            _create_operational_tables_for_fc(fc)
            _migrate_hc_table_for_fc(fc)
            _migrate_lc_table_for_fc(fc)
            _migrate_tickets_table_for_fc(fc)
            _migrate_portal_ticket_claims_for_fc(fc)
            app.config["ACTIVE_FC"] = fc
            db.session.remove()
            from models.turno_config import ensure_default_turno_config
            ensure_default_turno_config()
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"[MIGRATION:{fc}] ERRO: {e}")
        finally:
            db.session.remove()

    try:
        _migrate_operadores_table()
    except Exception as e:
        print(f"[MIGRATION:GIG2] ERRO na tabela central de operadores: {e}")

    for fc in fc_keys:
        try:
            app.config["ACTIVE_FC"] = fc
            db.session.remove()
            print(f"[AUTO-STATUS:{fc}] Iniciando processamento.")
            processar_status_automatico()
        except Exception as e:
            db.session.rollback()
            print(f"[AUTO-STATUS:{fc}] ERRO: {e}")
        finally:
            db.session.remove()

    app.config.pop("ACTIVE_FC", None)


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)

    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Faca login para acessar o sistema."

    @login_manager.user_loader
    def load_user(user_id):
        from models.operadores import Operadores
        return Operadores.query.get(user_id)

    @login_manager.unauthorized_handler
    def unauthorized():
        if request.is_json or request.path.startswith("/api/"):
            return jsonify({"erro": "Nao autenticado."}), 401
        return redirect(url_for("auth.login"))

    @app.context_processor
    def inject_fc_context():
        from models import get_current_fc
        fc_key = get_current_fc()
        fc_data = app.config["FC_DATABASES"].get(fc_key, {})
        return {
            "active_fc": fc_key,
            "active_fc_label": fc_data.get("label", fc_key),
            "active_fc_logo": fc_data.get("logo", "lion_logo.png"),
            "fc_options": app.config["FC_DATABASES"],
        }

    with app.app_context():
        from models.hc_gig2 import HCGig2  # noqa: F401
        from models.lc_atual import LCAtual  # noqa: F401
        from models.operadores import Operadores  # noqa: F401
        from models.historico import HistoricoOperacional  # noqa: F401
        from models.registro_atividade import RegistroAtividade  # noqa: F401
        from models.turno_config import HCTurnoConfig  # noqa: F401
        from models.ticket import Ticket  # noqa: F401
        from models.portal_ticket_claims import PortalTicketClaim  # noqa: F401

        _bootstrap_databases(app)

    app.register_blueprint(hc_bp)
    app.register_blueprint(auth_bp)
    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

import json
from datetime import date, timedelta

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

    hoje = date.today()
    prazo_vencido = hoje.weekday() > 1

    todos = HCGig2.query.all()
    registros = []
    para_arquivar = []

    for op in todos:
        status_ant = op.status

        if op.status == "Desligado" and op.data_desligamento and hoje >= op.data_desligamento:
            para_arquivar.append(op)
            continue

        alterou_por_data = op.aplicar_status_por_data(hoje)
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
            if op.status in ("Licenca", "Licença", "Ferias", "Férias") and not op.data_inicio_licenca:
                op.status = "OFF"
                registros.append(RegistroAtividade(
                    tipo="edicao_status",
                    operador_id=op.id,
                    operador_login=op.login,
                    operador_nome=op.nome_completo,
                    usuario_login="sistema",
                    usuario_nome="Automacao",
                    descricao=f"Status -> OFF: pendencia '{status_ant}' sem data definida (prazo terca-feira vencido)",
                    dados_anteriores=json.dumps({"status": status_ant}),
                    dados_novos=json.dumps({"status": "OFF"}),
                ))
            elif op.status == "Desligado" and not op.data_desligamento:
                op.status = "OFF"
                registros.append(RegistroAtividade(
                    tipo="edicao_status",
                    operador_id=op.id,
                    operador_login=op.login,
                    operador_nome=op.nome_completo,
                    usuario_login="sistema",
                    usuario_nome="Automacao",
                    descricao="Status -> OFF: pendencia de desligamento sem data (prazo terca-feira vencido)",
                    dados_anteriores=json.dumps({"status": status_ant}),
                    dados_novos=json.dumps({"status": "OFF"}),
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
    db.metadatas[None].create_all(bind=engine)
    print(f"[MIGRATION:{fc}] Tabelas operacionais verificadas.")


def _migrate_hc_table_for_fc(fc):
    engine = db.engines[fc]
    with engine.begin() as conn:
        conn.execute(db.text("ALTER TABLE hc_gig2 ADD COLUMN IF NOT EXISTS status_liberacao VARCHAR(100)"))
        conn.execute(db.text("ALTER TABLE hc_gig2 ALTER COLUMN login DROP NOT NULL"))
        conn.execute(db.text("ALTER TABLE hc_gig2 ALTER COLUMN area DROP NOT NULL"))
        conn.execute(db.text("ALTER TABLE hc_gig2 ALTER COLUMN turno DROP NOT NULL"))
        conn.execute(db.text("ALTER TABLE hc_gig2 ADD COLUMN IF NOT EXISTS data_inicio_licenca DATE"))
        conn.execute(db.text("ALTER TABLE hc_gig2 ADD COLUMN IF NOT EXISTS data_fim_licenca DATE"))
        conn.execute(db.text("ALTER TABLE hc_gig2 ADD COLUMN IF NOT EXISTS data_desligamento DATE"))
        conn.execute(db.text("ALTER TABLE hc_gig2 ALTER COLUMN causa_afastamento TYPE VARCHAR(500)"))
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


def _migrate_operadores_table():
    db.metadatas["GIG2"].create_all(bind=db.engines["GIG2"])
    with db.engines["GIG2"].begin() as conn:
        conn.execute(db.text("ALTER TABLE operadores ADD COLUMN IF NOT EXISTS permission_hcview BOOLEAN DEFAULT FALSE"))
        conn.execute(db.text("ALTER TABLE operadores ADD COLUMN IF NOT EXISTS permission_level_hcview VARCHAR(20)"))
    print("[MIGRATION:GIG2] Tabela central de operadores verificada.")


def _bootstrap_databases(app):
    fc_keys = list(app.config["FC_DATABASES"].keys())

    for fc in fc_keys:
        try:
            _create_operational_tables_for_fc(fc)
            _migrate_hc_table_for_fc(fc)
        except Exception as e:
            print(f"[MIGRATION:{fc}] ERRO: {e}")

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
            "fc_options": app.config["FC_DATABASES"],
        }

    with app.app_context():
        from models.hc_gig2 import HCGig2  # noqa: F401
        from models.lc_atual import LCAtual  # noqa: F401
        from models.operadores import Operadores  # noqa: F401
        from models.historico import HistoricoOperacional  # noqa: F401
        from models.registro_atividade import RegistroAtividade  # noqa: F401

        _bootstrap_databases(app)

    app.register_blueprint(hc_bp)
    app.register_blueprint(auth_bp)
    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

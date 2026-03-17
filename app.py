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
    days_back = (today.weekday() - 1) % 7  # Mon(0)->6, Tue(1)->0, Wed(2)->1 ...
    return today - timedelta(days=days_back)


def processar_status_automatico():
    """Automatic status transitions: revert leaves, deadline OFF, archive terminations."""
    from models.hc_gig2 import HCGig2
    from models.historico import HistoricoOperacional
    from models.registro_atividade import RegistroAtividade

    hoje = date.today()
    prazo_vencido = hoje.weekday() > 1  # Wed(2) through Sun(6) = past Tuesday

    todos = HCGig2.query.all()
    registros = []
    para_arquivar = []

    for op in todos:
        status_ant = op.status

        # 1. Auto-archive: termination date reached
        if op.status == "Desligado" and op.data_desligamento and hoje >= op.data_desligamento:
            para_arquivar.append(op)
            continue

        # 2. Auto-revert: license/vacation period ended
        if op.status in ("Licença", "Férias") and op.data_fim_licenca and hoje > op.data_fim_licenca:
            op.status = "OPERACIONAL"
            op.data_inicio_licenca = None
            op.data_fim_licenca = None
            registros.append(RegistroAtividade(
                tipo="edicao_status",
                operador_id=op.id,
                operador_login=op.login,
                operador_nome=op.nome_completo,
                usuario_login="sistema",
                usuario_nome="Automação",
                descricao=f"Retorno automático para OPERACIONAL — período de {status_ant} encerrado",
                dados_anteriores=json.dumps({"status": status_ant}),
                dados_novos=json.dumps({"status": "OPERACIONAL"}),
            ))
            continue

        # 3. Pendência deadline missed (no dates defined) → OFF
        if prazo_vencido:
            if op.status in ("Licença", "Férias") and not op.data_inicio_licenca:
                op.status = "OFF"
                registros.append(RegistroAtividade(
                    tipo="edicao_status",
                    operador_id=op.id,
                    operador_login=op.login,
                    operador_nome=op.nome_completo,
                    usuario_login="sistema",
                    usuario_nome="Automação",
                    descricao=f"Status → OFF: pendência '{status_ant}' sem data definida (prazo terça-feira vencido)",
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
                    usuario_nome="Automação",
                    descricao="Status → OFF: pendência de desligamento sem data (prazo terça-feira vencido)",
                    dados_anteriores=json.dumps({"status": status_ant}),
                    dados_novos=json.dumps({"status": "OFF"}),
                ))

    # Archive and delete terminated employees
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
            usuario_nome="Automação",
            descricao=f"Colaborador '{op.nome_completo}' arquivado automaticamente em {op.data_desligamento}.",
        ))
        db.session.delete(op)

    for r in registros:
        db.session.add(r)

    db.session.commit()
    count = len(registros)
    if count:
        print(f"[AUTO-STATUS] {count} operação(ões) processada(s).")
    else:
        print("[AUTO-STATUS] Nenhuma alteração necessária.")


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)

    # ── Flask-Login ────────────────────────────────────────────
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Faça login para acessar o sistema."

    @login_manager.user_loader
    def load_user(user_id):
        from models.operadores import Operadores
        return Operadores.query.get(user_id)

    @login_manager.unauthorized_handler
    def unauthorized():
        if request.is_json or request.path.startswith("/api/"):
            return jsonify({"erro": "Não autenticado."}), 401
        return redirect(url_for("auth.login"))

    with app.app_context():
        from models.hc_gig2 import HCGig2  # noqa: F401
        from models.operadores import Operadores  # noqa: F401
        from models.historico import HistoricoOperacional  # noqa: F401
        from models.registro_atividade import RegistroAtividade  # noqa: F401

        db.create_all()

        # ── Column migrations ──────────────────────────────────
        try:
            db.session.execute(db.text(
                "ALTER TABLE hc_gig2 ADD COLUMN IF NOT EXISTS status_liberacao VARCHAR(100)"
            ))
            db.session.execute(db.text(
                "ALTER TABLE hc_gig2 ALTER COLUMN login DROP NOT NULL"
            ))
            db.session.execute(db.text(
                "ALTER TABLE hc_gig2 ALTER COLUMN area DROP NOT NULL"
            ))
            db.session.execute(db.text(
                "ALTER TABLE hc_gig2 ALTER COLUMN turno DROP NOT NULL"
            ))
            db.session.execute(db.text(
                "ALTER TABLE hc_gig2 ADD COLUMN IF NOT EXISTS data_inicio_licenca DATE"
            ))
            db.session.execute(db.text(
                "ALTER TABLE hc_gig2 ADD COLUMN IF NOT EXISTS data_fim_licenca DATE"
            ))
            db.session.execute(db.text(
                "ALTER TABLE hc_gig2 ADD COLUMN IF NOT EXISTS data_desligamento DATE"
            ))
            db.session.execute(db.text(
                "ALTER TABLE hc_gig2 ALTER COLUMN causa_afastamento TYPE VARCHAR(500)"
            ))
            db.session.commit()

            result = db.session.execute(db.text(
                "SELECT column_name, data_type, is_nullable "
                "FROM information_schema.columns "
                "WHERE table_name = 'hc_gig2' "
                "ORDER BY ordinal_position"
            ))
            colunas = result.fetchall()
            print("=== [MIGRATION] Estrutura atual da tabela hc_gig2 ===")
            for col in colunas:
                print(f"  {col[0]:30s} | {col[1]:20s} | nullable={col[2]}")
            print("=== [MIGRATION] Concluída com sucesso ===")

        except Exception as e:
            db.session.rollback()
            print(f"[MIGRATION] ERRO ao aplicar migração: {e}")

        # ── Migrations: operadores permission columns ──────────
        try:
            db.session.execute(db.text(
                "ALTER TABLE operadores ADD COLUMN IF NOT EXISTS permission_hcview BOOLEAN DEFAULT FALSE"
            ))
            db.session.execute(db.text(
                "ALTER TABLE operadores ADD COLUMN IF NOT EXISTS permission_level_hcview VARCHAR(20)"
            ))
            db.session.commit()
            print("[MIGRATION] Colunas permission_hcview e permission_level_hcview verificadas em 'operadores'.")
        except Exception as e:
            db.session.rollback()
            print(f"[MIGRATION] ERRO nas colunas de permissão HC View: {e}")

        # ── Auto-status on startup ─────────────────────────────
        try:
            processar_status_automatico()
        except Exception as e:
            print(f"[AUTO-STATUS] ERRO: {e}")

    app.register_blueprint(hc_bp)
    app.register_blueprint(auth_bp)
    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

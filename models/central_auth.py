"""Controle centralizado de acesso: a HC Overview é a fonte oficial de
autorização para as demais aplicações integradas.

Modelos (todos no banco central GIG2, independente do site/FC ativo):
  Aplicacao         - app integrada (identificador estável = slug).
  ChaveAplicacao     - credencial técnica (servidor-a-servidor) de uma app.
                      Só o HASH do segredo é gravado; o valor em texto puro só
                      existe na resposta do momento da criação.
  AcessoAplicacao    - liberação de um usuário (login) pra uma Aplicacao:
                      perfil, permissões, status (ATIVO/REVOGADO), expiração.
                      É a tabela consultada a cada checagem de autorização -
                      nunca cacheada como "autorizado" entre requisições.
  ChaveFisicaUsuario - chave de segurança (YubiKey) registrada pra UM usuário -
                      autentica uma PESSOA (não uma app) pelo ID público e
                      estável da chave física. Ver nota de segurança no
                      docstring da classe antes de usar em algo crítico.
  AuditoriaCentral   - quem fez o quê, quando, em cima de qual usuário/app.
                      Nunca grava segredos nem tokens - só metadados.

Ver routes/central.py para as regras de negócio e docs/central_auth_contrato.md
para o contrato de integração das aplicações consumidoras.
"""
import hashlib
import json
import secrets
from datetime import datetime

from models import db

STATUS_ATIVO = "ATIVO"
STATUS_REVOGADO = "REVOGADO"

# Um OTP de YubiKey (modo padrão) tem até 44 caracteres em ModHex; os 12
# primeiros são o ID PÚBLICO e ESTÁVEL daquela chave física específica - não
# mudam nunca. O restante (até ~32 caracteres) é a parte variável/um-uso-só,
# que troca a cada toque na chave.
YUBIKEY_ID_LEN = 12


def extrair_yubikey_id(otp_ou_id):
    """Extrai o identificador público (12 caracteres) de uma chave YubiKey a
    partir do OTP completo digitado/colado, ou do próprio ID já isolado.
    Aceita qualquer um dos dois porque é assim que a chave "digita" (via
    teclado USB) quando tocada - só os 12 primeiros caracteres importam pra
    identificar QUAL chave física é."""
    valor = (otp_ou_id or "").strip().lower()
    if len(valor) < YUBIKEY_ID_LEN:
        return None
    return valor[:YUBIKEY_ID_LEN]


def _gerar_segredo():
    """Segredo opaco pra credencial de aplicação. Prefixo fixo só pra
    reconhecimento visual (nunca reduz a entropia: o resto é aleatório)."""
    return "hcx_" + secrets.token_urlsafe(32)


def calcular_hash_segredo(segredo):
    """Público: routes/central.py usa pra conferir a chave recebida em cada
    checagem de autorização sem nunca guardar o segredo em texto puro."""
    return hashlib.sha256(segredo.encode("utf-8")).hexdigest()


class Aplicacao(db.Model):
    __bind_key__ = "GIG2"
    __tablename__ = "central_aplicacoes"

    id = db.Column(db.Integer, primary_key=True)
    # Identificador ESTÁVEL da aplicação (nunca muda, usado por quem integra).
    slug = db.Column(db.String(50), unique=True, nullable=False, index=True)
    nome = db.Column(db.String(150), nullable=False)
    descricao = db.Column(db.String(300), nullable=True)
    ativa = db.Column(db.Boolean, nullable=False, default=True)
    # Listas sugeridas pra UI (não são um catálogo rígido obrigatório) - JSON
    # de strings, ex.: '["LEITURA","GESTOR","ADMIN"]'.
    perfis_disponiveis = db.Column(db.Text, nullable=True)
    criada_por = db.Column(db.String(50), nullable=True)
    criada_em = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def lista_perfis(self):
        try:
            valores = json.loads(self.perfis_disponiveis or "[]")
            return [str(v) for v in valores] if isinstance(valores, list) else []
        except (TypeError, ValueError):
            return []

    def to_dict(self):
        return {
            "id": self.id,
            "slug": self.slug,
            "nome": self.nome,
            "descricao": self.descricao or "",
            "ativa": bool(self.ativa),
            "perfis_disponiveis": self.lista_perfis(),
            "criada_por": self.criada_por or "",
            "criada_em": self.criada_em.strftime("%Y-%m-%d %H:%M:%S") if self.criada_em else None,
        }


class ChaveAplicacao(db.Model):
    """Credencial TÉCNICA da aplicação (servidor-a-servidor) - autentica QUAL
    aplicação está chamando a checagem central, nunca em nome de um usuário.
    Uma chave sozinha nunca concede acesso a ninguém; só identifica a app."""
    __bind_key__ = "GIG2"
    __tablename__ = "central_chaves_aplicacao"

    id = db.Column(db.Integer, primary_key=True)
    aplicacao_id = db.Column(db.Integer, db.ForeignKey("central_aplicacoes.id"), nullable=False, index=True)
    nome = db.Column(db.String(100), nullable=False)  # rótulo livre, ex.: "producao"
    prefixo = db.Column(db.String(16), nullable=False)  # só pra identificar na UI, nunca reconstrói o segredo
    hash_segredo = db.Column(db.String(128), nullable=False, unique=True, index=True)
    ativa = db.Column(db.Boolean, nullable=False, default=True)
    criada_por = db.Column(db.String(50), nullable=True)
    criada_em = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    expira_em = db.Column(db.DateTime, nullable=True)
    revogada_em = db.Column(db.DateTime, nullable=True)
    revogada_por = db.Column(db.String(50), nullable=True)
    ultimo_uso_em = db.Column(db.DateTime, nullable=True)

    @staticmethod
    def gerar(aplicacao_id, nome, criada_por, expira_em=None):
        """Cria a credencial e devolve (instancia, segredo_em_texto_puro).
        O segredo só existe aqui - depois disso, só o hash fica gravado."""
        segredo = _gerar_segredo()
        chave = ChaveAplicacao(
            aplicacao_id=aplicacao_id,
            nome=nome,
            prefixo=segredo[:12],
            hash_segredo=calcular_hash_segredo(segredo),
            criada_por=criada_por,
            expira_em=expira_em,
        )
        return chave, segredo

    def esta_valida(self, agora=None):
        agora = agora or datetime.utcnow()
        if not self.ativa or self.revogada_em:
            return False
        if self.expira_em and agora >= self.expira_em:
            return False
        return True

    def to_dict(self):
        return {
            "id": self.id,
            "aplicacao_id": self.aplicacao_id,
            "nome": self.nome,
            "prefixo": self.prefixo + "…",
            "ativa": bool(self.ativa),
            "criada_por": self.criada_por or "",
            "criada_em": self.criada_em.strftime("%Y-%m-%d %H:%M:%S") if self.criada_em else None,
            "expira_em": self.expira_em.strftime("%Y-%m-%d %H:%M:%S") if self.expira_em else None,
            "revogada_em": self.revogada_em.strftime("%Y-%m-%d %H:%M:%S") if self.revogada_em else None,
            "revogada_por": self.revogada_por or "",
            "ultimo_uso_em": self.ultimo_uso_em.strftime("%Y-%m-%d %H:%M:%S") if self.ultimo_uso_em else None,
            "valida": self.esta_valida(),
        }


class AcessoAplicacao(db.Model):
    """Liberação de UM usuário (login) pra UMA aplicação - fonte oficial da
    autorização. Consultada do zero em toda checagem (nunca cacheada como
    positiva entre requisições - ver routes.central.avaliar_autorizacao)."""
    __bind_key__ = "GIG2"
    __tablename__ = "central_acessos"
    __table_args__ = (db.UniqueConstraint("usuario_login", "aplicacao_id", name="uq_central_acesso_usuario_app"),)

    id = db.Column(db.Integer, primary_key=True)
    usuario_login = db.Column(db.String(50), nullable=False, index=True)
    aplicacao_id = db.Column(db.Integer, db.ForeignKey("central_aplicacoes.id"), nullable=False, index=True)
    perfil = db.Column(db.String(50), nullable=True)
    # JSON de strings - permissões concedidas dentro da aplicação, ex.: '["ler","editar"]'.
    permissoes = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default=STATUS_ATIVO)
    expira_em = db.Column(db.DateTime, nullable=True)
    concedido_por = db.Column(db.String(50), nullable=True)
    concedido_em = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    atualizado_em = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    revogado_por = db.Column(db.String(50), nullable=True)
    revogado_em = db.Column(db.DateTime, nullable=True)

    def lista_permissoes(self):
        try:
            valores = json.loads(self.permissoes or "[]")
            return [str(v) for v in valores] if isinstance(valores, list) else []
        except (TypeError, ValueError):
            return []

    def esta_expirado(self, agora=None):
        agora = agora or datetime.utcnow()
        return bool(self.expira_em and agora >= self.expira_em)

    def status_calculado(self, agora=None):
        """Status "de fato" pra exibição - REVOGADO explícito vence; senão,
        EXPIRADO se passou da data; senão o status gravado (ATIVO)."""
        if self.status != STATUS_ATIVO:
            return STATUS_REVOGADO
        if self.esta_expirado(agora):
            return "EXPIRADO"
        return STATUS_ATIVO

    def to_dict(self):
        return {
            "id": self.id,
            "usuario_login": self.usuario_login,
            "aplicacao_id": self.aplicacao_id,
            "perfil": self.perfil or "",
            "permissoes": self.lista_permissoes(),
            "status": self.status,
            "status_calculado": self.status_calculado(),
            "expira_em": self.expira_em.strftime("%Y-%m-%dT%H:%M") if self.expira_em else None,
            "concedido_por": self.concedido_por or "",
            "concedido_em": self.concedido_em.strftime("%Y-%m-%d %H:%M:%S") if self.concedido_em else None,
            "revogado_por": self.revogado_por or "",
            "revogado_em": self.revogado_em.strftime("%Y-%m-%d %H:%M:%S") if self.revogado_em else None,
        }


class ChaveFisicaUsuario(db.Model):
    """Chave de segurança (YubiKey) registrada pra UM usuário - identifica a
    PESSOA pelo ID público e estável da chave física, sem senha. Diferente de
    ChaveAplicacao: aquela autentica uma aplicação (servidor-a-servidor),
    esta autentica um operador (pessoa), e uma nunca substitui a outra.

    NOTA DE SEGURANÇA (simplificação deliberada, a pedido): só o ID público
    (os 12 primeiros caracteres do OTP) é conferido aqui. A parte variável do
    OTP (os ~32 caracteres restantes, que mudam a cada toque na chave) NÃO é
    validada contra o Yubico OTP/YubiCloud nesta versão. Na prática isso
    funciona como um identificador fixo ligado à posse física da chave, não
    como uma senha de uso único à prova de repetição ("replay"): quem souber
    os 12 caracteres (ex.: viu por cima do ombro, achou anotado) consegue se
    passar pelo dono dela. Trate o ID como um dado sensível (não exiba
    completo em telas/log fora da própria administração) e, se precisar de
    garantia criptográfica real de uso único no futuro, o caminho é validar o
    OTP completo contra a YubiCloud (precisa de client id/secret da Yubico) -
    ver docs/central_auth_contrato.md, seção "Autenticação por chave de
    segurança (YubiKey)"."""
    __bind_key__ = "GIG2"
    __tablename__ = "central_chaves_usuario"

    id = db.Column(db.Integer, primary_key=True)
    usuario_login = db.Column(db.String(50), nullable=False, index=True)
    yubikey_id = db.Column(db.String(12), nullable=False, unique=True, index=True)
    apelido = db.Column(db.String(100), nullable=True)
    ativa = db.Column(db.Boolean, nullable=False, default=True)
    cadastrada_por = db.Column(db.String(50), nullable=True)
    cadastrada_em = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    revogada_em = db.Column(db.DateTime, nullable=True)
    revogada_por = db.Column(db.String(50), nullable=True)
    ultimo_uso_em = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "usuario_login": self.usuario_login,
            "yubikey_id": self.yubikey_id,
            "apelido": self.apelido or "",
            "ativa": bool(self.ativa),
            "cadastrada_por": self.cadastrada_por or "",
            "cadastrada_em": self.cadastrada_em.strftime("%Y-%m-%d %H:%M:%S") if self.cadastrada_em else None,
            "revogada_em": self.revogada_em.strftime("%Y-%m-%d %H:%M:%S") if self.revogada_em else None,
            "revogada_por": self.revogada_por or "",
            "ultimo_uso_em": self.ultimo_uso_em.strftime("%Y-%m-%d %H:%M:%S") if self.ultimo_uso_em else None,
        }


class AuditoriaCentral(db.Model):
    """Trilha de auditoria das mudanças de acesso central - nunca grava
    segredos/tokens, só metadados de quem fez o quê."""
    __bind_key__ = "GIG2"
    __tablename__ = "central_auditoria"

    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String(50), nullable=False, index=True)
    usuario_alvo = db.Column(db.String(50), nullable=True, index=True)
    aplicacao_id = db.Column(db.Integer, nullable=True, index=True)
    ator_login = db.Column(db.String(50), nullable=True)
    descricao = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "tipo": self.tipo,
            "usuario_alvo": self.usuario_alvo or "",
            "aplicacao_id": self.aplicacao_id,
            "ator_login": self.ator_login or "",
            "descricao": self.descricao or "",
            "timestamp": self.timestamp.strftime("%Y-%m-%d %H:%M:%S") if self.timestamp else None,
        }

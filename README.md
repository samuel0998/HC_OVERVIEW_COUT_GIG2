# HC GIG2 - Headcount Overview

Projeto Flask pronto para Railway com PostgreSQL.

## Estrutura
- Cadastro de novo colaborador
- Busca e edição por login, nome, cargo, área e turno
- Importação e exportação Excel
- Dashboard de HC Overview
- Criação automática da tabela `hc_gig2`

## Variáveis de ambiente
Use no Railway:
- `DATABASE_URL`
- `SECRET_KEY`

## Rodando local
```bash
pip install -r requirements.txt
python init_hc_gig2.py
python app.py
```

## Deploy Railway
O `Procfile` já está pronto para usar Gunicorn.

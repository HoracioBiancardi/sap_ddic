# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@~/.claude/python-code-standards.md

## Comandos

```bash
uv sync                                        # instala dependências (Python 3.11+, uv)
uv run ddic                                    # sobe o servidor dev em 127.0.0.1:8000 (uvicorn --reload)
uv run pytest                                  # roda toda a suíte
uv run pytest tests/test_heuristics.py         # roda um arquivo de teste
uv run pytest tests/test_heuristics.py::TestClassifyTableType   # roda uma classe/teste específico
uv run pytest -k "incremental"                 # roda por substring do nome
```

Não há linter/formatter configurado no `pyproject.toml` (sem ruff/black/mypy) — não presuma que exista um comando de lint.

Não há suíte de testes para o frontend (JS puro, sem build step, sem framework).

## Arquitetura

Backend em camadas, cada uma só falando com a de baixo. `main.py` só monta o
`FastAPI()`, constrói o `MetadataService` uma vez no `_lifespan` e inclui os
routers de `sap_ddic/routers/` — as rotas em si vivem lá, uma por domínio:

```
routers/{search,tables,tcode,mart,system}.py (rotas HTTP, um APIRouter por domínio)
  -> dependencies.py    (get_service: lê o MetadataService de request.app.state)
  -> security.py         (valida table_name/search term ANTES de qualquer I/O)
  -> service.py           (MetadataService: orquestra tudo abaixo)
       -> cache.py         (MetadataCache: lê/grava cache/{table}.json, invalida por AS4DATE)
       -> ddic_repository.py (DDICRepository: SQL parametrizado contra o schema DDIC replicado)
            -> connection.py (DatasphereConnector: engine SQLAlchemy + retry/tenacity sobre HANA)
       -> heuristics.py    (TableClassifier: regras de classificação, puras, sem I/O — testadas com fixtures)
  -> dbt_generator.py      (TableContract -> SQL/YML de staging dbt para 1 tabela; routers/tables.py)
  -> mart_generator.py     (grafo de tabelas + joins -> SQL/YML/MD de um mart fact/dim; routers/mart.py)
  -> schemas.py            (contrato Pydantic single-source-of-truth de toda a API)
```

`MetadataService.get_table_contract` é o método central: busca o header,
decide se o cache local ainda é válido comparando `AS4DATE`, e só reconstrói
o contrato completo (colunas, FKs, stats técnicas) via `DDICRepository`
quando necessário. `security.py` roda como dependency do FastAPI *antes*
desse fluxo — um `table_name` validado é seguro tanto para bind de SQL
quanto para path de arquivo de cache (`cache/{table_name}.json`).

`routers/system.py` expõe `GET /api/system/health` (badge de conexão do
topbar) e `GET /api/system/logs`/`POST /api/system/logs/clear`, lendo de um
ring buffer em memória (`logger.BufferHandler`, `maxlen=500`) anexado como
handler extra em `logger.get_logger()` — todo `logger.info/warning/error` já
emitido em qualquer módulo (`cache.py`, `service.py`, `ddic_repository.py`,
`connection.py`, os próprios routers) alimenta esse buffer automaticamente,
sem precisar instrumentar chamadas separadas.

`table_name` usa o conversor `:path` nas rotas (não o matcher padrão de
segmento único), porque nomes de objeto namespaced do SAP (ex.:
`/BIC/AZCUSTOMER`) têm `/` no próprio nome.

### Geradores dbt (`dbt_generator.py` / `mart_generator.py`)

Ambos portam a lógica de mapeamento de tipo/macro/alias do projeto irmão
`datasphere_generator_dbt` (`ingestor/translator.py`,
`dbt_generator/generator.py`), adaptada para ler direto do `TableContract`
já montado pelo `MetadataService` — sem reextração DDIC separada.
`mart_generator.py` **reimporta funções privadas** de `dbt_generator.py`
(`_build_alias_map`, `_col_to_macro`, `_esc`, `_map_column_type`,
`_quote_if_needed`) para que uma coluna renderize de forma idêntica num
model de staging single-table ou num mart multi-tabela — ao alterar uma
dessas funções em `dbt_generator.py`, cheque o impacto em `mart_generator.py`.

No mart, o `node_id` de cada "box" (não o `table_name`) é o identificador no
grafo e vira o alias SQL, porque a mesma tabela SAP pode aparecer como dois
nós independentes com papéis diferentes (ex.: `BSEG` referencia `KNA1` duas
vezes — cliente e pagador; `MARA` se autorreferencia 5 vezes). O join do mart
é sempre `materialized="table"` completo (sem variante incremental — grain/
dedup de um mart é história diferente da de uma stream de tabela única).

### Particularidade real do DDIC (`ddic_repository.py`)

`DD05S.FORTABLE`/`FORKEY` só nomeia o lado filho da chave estrangeira, nunca
o campo da tabela pai. Por isso `fetch_foreign_keys` busca separadamente a
chave primária ordenada da tabela de checagem
(`_fetch_ordered_key_fields`) e casa por posição — necessário para capturar
casos como `MARA.BMATN -> MARA.MATNR` (nomes de campo divergentes entre
filho e pai). O dicionário de domínios de negócio para busca por área
(`financeiro`, `vendas`, etc.) está em `_BUSINESS_DOMAINS` nesse mesmo
arquivo — ao adicionar um domínio nesse dicionário, confirme o(s) código(s)
`APPLCLASS` reais contra tabelas conhecidas antes de cadastrar (nem sempre
correspondem à intuição, ex.: tabelas de ordem de produção usam
`APPLCLASS='CO'`).

### Frontend

HTML/CSS/JS puro (sem framework, sem build step), servido como estático pelo
próprio FastAPI (`app.mount("/", StaticFiles(...))`), mesma origem da API —
não há CORS a configurar. `sap_ddic/frontend/js/state.js` guarda o estado
compartilhado (tabela atual, contrato); `app.js` é o entrypoint que conecta
os demais módulos (`views.js` navegação, `render.js` renderização de
cards/tabelas, `graph.js` grafo de linhagem via vis-network, `dbtGenerator.js`
e `martGenerator.js` as telas dos dois geradores dbt, `exports.js` recortes
de exportação JSON, `jsonViewer.js` syntax highlight via Prism, `prefs.js`
tema persistido em `localStorage`, `toast.js` notificação transiente).

O design system (`css/theme.css` + `css/styles.css`) é portado do
`app_template` (starter kit irmão do ecossistema pessoal "SwordPower"):
topbar + activity bar (a antiga `.sidebar` de 240px virou uma trilha de
ícones de 64px) + cards com sombra + 3 temas trocáveis pelo modal de
Configurações (`corporate`/`green-neutral`/`cyber-dark`, padrão
`cyber-dark`) via `body.theme-*`. `graph.js`/`martGenerator.js`/`render.js`/
`tcodeSearch.js` colorem canvas/grafo lendo variáveis CSS "antigas"
(`--bg-solid`, `--surface-1/2`, `--text-primary/secondary`, `--accent`,
`--cat-*`) via `getComputedStyle()` — `theme.css` redefine essas variáveis
como alias dos tokens novos (`--bg`, `--surface`, `--text`, `--primary`,
etc.) em cada bloco de tema, então esses módulos não precisam saber que o
design system mudou. Ao trocar de tema depois que o grafo/canvas já
renderizou, `app.js::redrawThemedCanvases()` os redesenha (as cores são lidas
uma vez, no momento do desenho, e ficam "gravadas" no `vis.DataSet`).

### Config e segredos

`sap_ddic/config.py::Settings` lê `.env` via `pydantic-settings`
(`HANA_ADDRESS`, `HANA_PORT`, `HANA_USER`, `HANA_PASSWORD`, `DDIC_SCHEMA`,
`DDIC_LANGUAGE`, mais defaults de dbt como `DBT_DATABASE`/`DBT_SCHEMA`). O
`.env` deste repositório contém credenciais reais de um schema SAP
Datasphere — nunca o exponha em commits, logs ou saída de comando.

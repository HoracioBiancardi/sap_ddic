# SAP Metadata Discovery

Aplicação web para descoberta de metadados de tabelas SAP: busca uma tabela
técnica e devolve uma visão de negócio consolidada — tipo de tabela (Mestre /
Transacional / Configuração), hierarquia (Cabeçalho / Item / Standalone),
dicionário de campos com domínios e valores fixos, tabelas relacionadas e um
grafo de linhagem — a partir de uma réplica SAP Datasphere (HANA Cloud) do
Dicionário de Dados (DDIC) do SAP ECC.

Backend em **FastAPI** (proxy de leitura sobre o HANA, com heurísticas de
classificação de negócio e cache local); frontend em **HTML/CSS/JS puro**
(sem framework, sem build step), servido pelo próprio FastAPI.

## Requisitos

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) como gerenciador de pacotes
- Acesso de rede ao schema SAP Datasphere configurado no `.env`

## Instalação

```bash
uv sync
```

## Configuração

Crie um `.env` na raiz do projeto (veja `.env` já existente neste repositório
como referência):

```bash
HANA_ADDRESS=<host>.hana.prod-usXX.hanacloud.ondemand.com
HANA_PORT=443
HANA_USER=<usuário técnico>
HANA_PASSWORD=<senha>
DDIC_SCHEMA=IB_SAPECC
DDIC_LANGUAGE=P
LOG_LEVEL=INFO
LOG_TO_JSON=False
LOG_PATH=log/pipeline.json
```

**Nunca commite o `.env`** — já está no `.gitignore`.

## Executando

```bash
uv run ddic
```

Equivalente a `uv run uvicorn backend.main:app --reload`, disponível como
atalho via `[project.scripts]` no `pyproject.toml`.

Acesse `http://127.0.0.1:8000/` — o próprio FastAPI serve o frontend
(`frontend/`) e a API (`/api/*`) na mesma origem, sem necessidade de CORS.

## Testes

```bash
uv run pytest
```

Os testes cobrem as heurísticas de classificação (`backend/heuristics.py`) e o
cache local (`backend/cache.py`) com fixtures puras — não exigem conexão com o
SAP.

## Estrutura de pastas

```
sap_ddic/
├── backend/
│   ├── config.py           # Settings (.env) via pydantic-settings
│   ├── connection.py       # DatasphereConnector: engine SQLAlchemy + retry
│   ├── ddic_repository.py  # Queries parametrizadas contra o DDIC replicado
│   ├── heuristics.py       # TableClassifier: regras de negócio (puras, sem I/O)
│   ├── cache.py            # MetadataCache: cache local invalidado por AS4DATE
│   ├── schemas.py          # Modelos Pydantic do contrato JSON
│   ├── security.py         # Validação de table_name / termo de busca / grafo de mart
│   ├── service.py          # MetadataService: orquestra tudo acima
│   ├── dbt_generator.py    # TableContract -> SQL/YML de staging dbt (1 tabela)
│   ├── mart_generator.py   # Grafo de tabelas + joins -> SQL/YML/MD de mart fato/dimensão
│   ├── logger.py           # Logger da aplicação
│   └── main.py             # App FastAPI + rotas + arquivos estáticos
├── frontend/
│   ├── index.html
│   ├── css/styles.css
│   └── js/
│       ├── state.js        # Estado compartilhado (tabela atual, contrato)
│       ├── api.js          # fetch wrappers (/api/search, /api/table/{nome}, /api/table/{nome}/dbt, /api/mart/generate)
│       ├── views.js        # Navegação landing -> resumo -> detalhes
│       ├── render.js       # Card de resumo, tabela de dicionário, modal de enum
│       ├── graph.js        # Grafo de linhagem (vis-network)
│       ├── jsonViewer.js   # Syntax highlight (Prism), copiar/baixar o JSON completo
│       ├── exports.js      # Exportações JSON recortadas: técnico, linhagem/join, campos
│       ├── dbtGenerator.js # Tela "Gerador SQL": staging dbt de uma única tabela
│       ├── martGenerator.js# Tela "Fato/Dimensão": canvas visual de tabelas + joins -> mart
│       └── app.js          # Entrypoint — conecta tudo
├── cache/                  # Cache local por tabela (gitignored, criado em runtime)
└── tests/
    ├── test_heuristics.py
    ├── test_cache.py
    ├── test_dbt_generator.py
    └── test_mart_generator.py
```

## Endpoints

- `GET /api/search?q={termo}` — até 15 tabelas, em 3 níveis (cada um só roda
  se o anterior não preencheu o limite): **(1)** prefixo no nome técnico,
  **(2)** área de negócio (ver abaixo), **(3)** substring na descrição, como
  último recurso.

  **Busca explícita, não live-as-you-type**: a conexão HANA Cloud deste
  ambiente tem um piso de latência de ~2-5s por round-trip — mesmo um
  `SELECT 1` trivial mede mais de 1s (rede até o Datasphere, não é
  complexidade de query: testei trocar `DD02T` pela variante materializada
  `_LT` e a variância continuou igual dos dois lados). Buscar a cada tecla
  digitada faria disparar uma requisição lenta por pausa de digitação e
  pareceria travado. A busca só dispara no Enter/clique em "Buscar"
  (`frontend/js/app.js::performSearch`), com um spinner "Buscando
  tabelas..." explícito enquanto aguarda.
- `GET /api/table/{table_name}` — contrato completo de metadados da tabela
  (schema `SAPTableMetadata`), servido do cache local quando o `AS4DATE` da
  tabela no SAP não mudou desde a última extração.
- `POST /api/table/{table_name}/dbt` — gera o model de staging dbt
  (`stg_<tabela>.sql`) e o `sources.yml` de uma única tabela, a partir do
  contrato já montado (sem reextração DDIC). Aceita `load_type` (FULL/
  INCREMENTAL, auto-sugerido se omitido), `watermark_column` (informativo —
  não altera o SQL, que sempre usa `dt_ingestao`/`hash_pk` da camada bronze
  para o filtro incremental), overrides de `source_name`/`database`/
  `dbt_schema`, `plain_sql` (pula todo o scaffolding dbt e devolve um
  `SELECT` puro) e `use_business_alias` (alias curto a partir da descrição
  de negócio, ex. `numero_material`, em vez do nome de campo SAP cru). Tela
  "Gerador SQL" no frontend.
- `POST /api/mart/generate` — gera um model dbt de fato/dimensão
  (SQL + YML + Markdown com diagrama Mermaid) a partir de um grafo arbitrário
  de tabelas ("boxes") e seus joins, montado visualmente na tela
  "Fato/Dimensão". Cada box tem um `node_id` próprio (não necessariamente
  igual ao `table_name`), permitindo que a mesma tabela SAP apareça duas
  vezes com papéis diferentes (ex.: `KNA1` como cliente e como pagador em
  `BSEG`). Joins podem ser auto-detectados (FK real da `DD08L`) ou
  desenhados manualmente, para relacionamentos que o DDIC não modela como FK
  formal (ex.: cadeias de fluxo de documento via `VBFA`). Sempre gera
  `materialized="table"` (sem variante incremental).

### Busca por área de negócio

Termos como `financeiro`, `vendas`, `compras`, `materiais`, `producao` ou
`controladoria` (acentos são normalizados automaticamente) casam com
`DD02L.APPLCLASS` — o código de área de aplicação do SAP — em vez de exigir
que a palavra apareça literalmente na descrição técnica da tabela. Por
exemplo, `financeiro` traz `BKPF`/`BSEG` mesmo a descrição sendo "Documento
contábil: Cabeçalho". O dicionário de sinônimos e as tabelas-semente por
domínio (para garantir que as tabelas canônicas apareçam primeiro, não
tabelas obscuras da mesma classe) estão em
`backend/ddic_repository.py::_BUSINESS_DOMAINS` — para adicionar um novo
domínio, confirme o(s) código(s) `APPLCLASS` reais contra tabelas conhecidas
antes de cadastrar (nem sempre correspondem à intuição — ex.: `AFKO`/`AFPO`,
tabelas de ordem de produção, usam `APPLCLASS='CO'`, não algo ligado a "PP").

### Estatísticas técnicas (`technical_stats`)

Cada tabela também traz:

- `field_count`, `record_length_bytes` (soma do `LENG` de todos os campos) e
  `key_length_bytes` (soma do `LENG` dos campos de chave) — calculados a
  partir da `DD03L`.
- `data_class` e `size_category` — vêm da `DD09L` ("Further Attributes of a
  Table"): `TABART` (`APPL0`=dados mestres, `APPL1`=transacional — cabeçalho
  e item, `BSEG`/`EKPO`/`VBAP` são todos `APPL1`, verificado empiricamente —,
  `APPL2`=configuração/customizing, **não** "movimento" como uma versão
  anterior deste texto assumia) e `TABKAT` (categoria de volume esperado,
  escala ordinal 0-9 definida pelo desenvolvedor na criação da tabela). O
  frontend traduz `TABKAT` para um rótulo qualitativo (Mínima/Pequena/Média/
  Grande/Muito grande) **com a faixa numérica de registros entre parênteses**
  (ex.: "Média (até 2,5 milhões de registros)"), usando os limiares
  documentados no projeto irmão `datasphere-generator-dbt`
  (`SIZE_CATEGORY_RANGES` em `frontend/js/render.js`: cat.0 até 10 mil,
  cat.1 até 40 mil, cat.2 até 160 mil, cat.3 até 650 mil, cat.4 até 2,5
  milhões, cat.5 até 10 milhões, cat.6 até 40 milhões, cat.7 até 160
  milhões, cat.8 até 650 milhões, cat.9 acima disso).
- `incremental_candidate_fields`/`supports_incremental_load` — heurística
  estrutural (presença de campos de data de alteração conhecidos:
  `AEDAT`/`LAEDA`/`UPDDA`/`CPUDT`) indicando que a tabela **poderia** suportar
  extração incremental — não confirmação de que isso esteja configurado no
  pipeline de replicação.

Tudo isso é derivado **só do DDIC** — funciona mesmo para uma tabela que só
existe como view, sem dado físico replicado ainda. Duas fontes alternativas
foram avaliadas e descartadas por não servirem para esse propósito:
`DD02L.DATMIN`/`DATMAX`/`DATAVG`/`TABLEN_FEATURE` (vêm zeradas para tabelas
padrão SAP como MARA/BKPF nesse ambiente — só são preenchidas quando o
desenvolvedor define categoria de tamanho manualmente numa tabela Z) e
`SYS.M_TABLES` (dá contagem real de linhas, mas exige que a tabela já tenha
um objeto físico `_LT` replicado, o que nem toda tabela pesquisável tem — e
por isso foi descartada em favor da `DD09L`, que está disponível para
qualquer tabela DDIC). Pela mesma razão, não há fonte técnica confiável para
saber se a extração incremental está de fato configurada no pipeline de
replicação: os logs de execução do Datasphere
(`REPLICATIONFLOW_RUN_DETAILS`/`DELTA_PROVIDER_SUBSCRIBER`) estão vazios
neste ambiente, já que a réplica usa Data Flows em lote, não Replication
Flows nativos.

### Exportações

Cada tela exporta só o que é dela, todas em JSON (`frontend/js/exports.js`):

- **Resumo** — botão "Exportar técnico" ao lado do CTA "Ver campos e
  detalhes": objeto com `technical_class`, `table_type`, `hierarchy_type`,
  `associated_text_table` e todo o `technical_stats`.
- **Detalhes → aba Dicionário** — botão "Exportar campos": mesma informação
  da tabela de campos (array `columns`). Cada campo validado por uma tabela
  de checagem (foreign key) mostra uma tag clicável `🔗 NOME_TABELA` ao lado
  do domínio (ex.: `MTART` → `🔗 T134`) — cruzamento feito no frontend entre
  `columns` e `parent_tables[].foreign_key_fields[].child_field`, já que o
  contrato não repete essa informação por campo. Clicar na tag navega direto
  para a tela de Resumo daquela tabela (mesmo fluxo de uma busca nova —
  `renderColumnsTable`'s `onNavigateToTable` chama `selectTable` de novo),
  permitindo explorar recursivamente as tabelas de checagem.
- **Detalhes → aba Linhagem** — botão "Exportar linhagem/join": array
  `joins`, um item por par `child_field`/`parent_field` de `parent_tables`
  (child_table, child_field, parent_table, parent_field, relationship_type),
  pronto para consumir num script/pipeline.
- **Detalhes → aba Dados Brutos** (antes "Contrato JSON") — "Copiar"/"Baixar
  completo (JSON)" para o contrato inteiro, sem recorte, mais "Exportar PKs
  (JSON)": array `primary_keys` com `column_name`/`data_type`/`length`/
  `decimals`/`domain_name` de cada campo de chave, na ordem de posição.

### Rastreabilidade da fonte (de qual tabela SAP vem cada informação)

Todo card/aba que exibe dado derivado do DDIC tem uma nota "Fonte: tabela(s)
SAP ..." explicitando de onde aquilo vem — resumo (`DD02L`/`DD02T`/`DD03L`/
`DD09L`), Dicionário (`DD03L`/`DD04T`/`DD07T`/`DD08L`+`DD05S`), Linhagem
(`DD08L`/`DD05S`/`DD02L`+`DD09L`) e o modal de valores fixos (`DD07T`
especificamente, junto com o nome do domínio). Isso existe porque a origem
técnica de cada informação não é óbvia à primeira vista — por exemplo,
"Domínio XFELD" no título do modal não deixa claro que os valores 1/2/(vazio)
vêm da `DD07T`, não do próprio domínio.

### Grau de importância na Linhagem

Uma tabela como MARA pode ter 60+ relacionamentos de check-table, quase todos
lookups de configuração pequenos (unidade de medida, tipo de material...).
Cada `parent_tables[].importance` é classificado em 3 níveis
(`TableClassifier.classify_relationship_importance`, `backend/heuristics.py`):

- **Alta** — a tabela-pai é ela mesma dado de negócio (`CONTFLAG='A'`, ex.:
  `LFA1`, `MARA` auto-referenciada).
- **Média** — tabela de Configuração (`CONTFLAG` C/G/E), mas com categoria de
  tamanho substancial (`DD09L.TABKAT >= 3`) — ex.: `J_1BTANP` está na
  categoria 4, igual à própria MARA. Nem todo lookup de configuração é
  irrelevante.
- **Baixa** — Configuração e pequena/mínima (categoria < 3) — ex.: `T006`,
  `T134`, categoria 0.

O grafo de linhagem (aba Linhagem) mostra por padrão só Alta+Média; um
checkbox "Mostrar todas as tabelas" revela também as de Baixa importância
(estilizadas com borda tracejada cinza para ficarem visualmente secundárias
mesmo quando exibidas).

## Notas importantes sobre o ambiente real

O schema Datasphere consultado (`IB_SAPECC`) expõe as tabelas DDIC clássicas
como **views** (`DD02L`, `DD02T`, `DD03L`, `DD04T`, `DD07T`, `DD05S`,
`DD08L`) sobre os artefatos de replicação — não como tabelas físicas.

`parent_tables` é montado a partir de `DD08L` (define, por campo, qual a
tabela de checagem) + `DD05S` (mapeamento campo a campo por posição). Uma
particularidade real do DDIC: `DD05S.FORTABLE`/`FORKEY` **só nomeia o lado
local (filho)** da chave — nunca o campo da tabela pai. Por isso
`DDICRepository.fetch_foreign_keys` busca separadamente a chave primária
ordenada da tabela de checagem (`_fetch_ordered_key_fields`) e casa por
posição. Isso é o que permite capturar corretamente casos como
`MARA.BMATN → MARA.MATNR` (nomes de campo divergentes entre filho e pai) —
um mapeamento ingênuo por "mesmo nome" erraria esse caso.

## Exemplo de uso

```bash
curl "http://127.0.0.1:8000/api/search?q=MAR"
curl "http://127.0.0.1:8000/api/table/MARA" | jq
```

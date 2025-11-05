# ==============================================================
#   SEÇÃO: Instruções de Execução no Terminal
# ==============================================================

# Para ativar o dashboard Streamlit, siga os passos abaixo:
#
# 1) Abra o terminal no diretório do arquivo:
#       cd caminho/para/seu/projeto
#
# 2) Rode o servidor Streamlit:
#       streamlit run streamlit_app.py
#
# 3) Abra o endereço exibido no terminal (ex.: http://localhost:8501)
#
# Observações:
# - Use CTRL+C para encerrar.
# - Porta alternativa:
#       streamlit run streamlit_app.py --server.port=8502


# ==============================================================
#   SEÇÃO: Imports e Configuração Geral
# ==============================================================
import io
import json
import os
import re
from typing import Tuple, List

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Layout "wide" e padding reduzido
st.set_page_config(page_title="Análise de Investimentos", layout="wide")
st.markdown("""
<style>
.block-container { padding-top: 1rem; padding-bottom: 1rem; }
</style>
""", unsafe_allow_html=True)


# ==============================================================
#   SEÇÃO: Processamento de Dados (integrado do trat_monitor_aba.py)
# ==============================================================

def sanitize_default(default_list, options_list, fallback_list=None):
        """
        Garante que o 'default' do multiselect seja subconjunto de 'options'.
        Se nada sobrar, usa fallback_list (já validada no contexto) ou [].
        """
        default_list = default_list or []
        options_set = set(options_list or [])
        cleaned = [x for x in default_list if x in options_set]
        if cleaned:
            return cleaned
        # se não sobrou nada, tenta um fallback seguro
        if fallback_list:
            return [x for x in fallback_list if x in options_set]
        return []


def processar_base_geral(arquivo_path: str, header_line_excel: int = 13, descontos_config=None) -> pd.DataFrame:
    """
    Processa o arquivo base_geral.xlsx aplicando todas as transformações
    que estavam no script trat_monitor_aba.py
    
    Args:
        arquivo_path: Caminho para o arquivo base_geral.xlsx
        header_line_excel: Linha do cabeçalho (1-indexado)
    
    Returns:
        DataFrame processado equivalente ao df_geral.csv
    """
    
    def ler_primeira_aba(path, header_line_excel):
        """
        Lê apenas a primeira aba do arquivo Excel com o cabeçalho correto
        """
        # Lê a primeira aba (sheet_name=0) com o cabeçalho correto
        df = pd.read_excel(path, sheet_name=0, header=header_line_excel - 1)
        
        # Remove linhas e colunas que estão completamente vazias
        df = df.dropna(axis=0, how="all").dropna(axis=1, how="all")
        
        # Remove espaços extras dos nomes de coluna
        df.columns = [c.strip() if isinstance(c, str) else c for c in df.columns]
        
        return df

    def rename_existing(df, mapping):
        """
        Renomeia colunas usando apenas as chaves que existem no DataFrame.
        Também lida com NBSP (\xa0) e espaços extras nos nomes das colunas.
        """
        norm_to_real = {}
        for c in df.columns:
            if isinstance(c, str):
                norm_to_real[c.replace("\xa0", " ").strip()] = c

        real_map = {}
        for src, dst in mapping.items():
            if src in df.columns:
                real_map[src] = dst
            else:
                src_norm = src.replace("\xa0", " ").strip()
                if src_norm in norm_to_real:
                    real_src = norm_to_real[src_norm]
                    real_map[real_src] = dst

        return df.rename(columns=real_map)

    def _norm_txt(s):
        if pd.isna(s):
            return s
        s = str(s).replace("\xa0", " ").strip()
        s = re.sub(r"\s+", " ", s)  # colapsa espaços múltiplos
        return s

    def _upper_norm(s):
        s = _norm_txt(s)
        return s.upper() if isinstance(s, str) else s

    def _strip_parentheses_nacional(series):
        """(NACIONAL) -> NACIONAL"""
        series = series.astype("string")
        return (series
                .apply(_norm_txt)
                .str.replace(r"^\(?\s*NACIONAL\s*\)?$", "NACIONAL", regex=True, case=False))

    # Lê a primeira aba
    df = ler_primeira_aba(arquivo_path, header_line_excel)

    # Remove colunas desnecessárias (ajuste conforme necessário)
    colunas_remover = [
        "Anunciante",
        "Grupo de Anunciantes", 
        "Item",
        "Produto",
        "Marca",
        "Setor"
    ]

    df = df.drop(columns=colunas_remover, errors="ignore")

    # Mapeamento de renomeação de colunas (ajuste conforme necessário)
    rename_map = {
        "Marca-Mãe": "Marca",
        "(R$)": "Inv_Base",
        "ANO": "Ano",
    }
    # Aplica renomeação
    df = rename_existing(df, rename_map)

    # Mapeamento de valores da coluna Meio (se existir)
    if "Meio" in df.columns:
        map_meio = {
            "DISPLAY DESKTOP": "DIGITAL",
            "VIDEO DESKTOP+DISPLAY MOBILE": "DIGITAL", 
            "SEARCH": "DIGITAL",
            "TV MERCHANDISING": "TV ABERTA",
            "TV ASSINATURA": "PAY TV",
        }
        df["Meio"] = df["Meio"].replace(map_meio)
            
    # Usa dtype pandas "string" (mantém <NA> como nulo de verdade) e tira espaços
    if "Marca" in df.columns:
        df["Marca"] = df["Marca"].astype("string").str.strip()
            
    # Usar descontos configuráveis do session_state
    if descontos_config is None:
        descontos_config = {
            "JORNAL": 0.85,
            "TV ABERTA": 0.75,
            "REVISTA": 0.70,
            "DIGITAL": 0.70,
            "PAY TV": 0.65,
            "CINEMA": 0.50,
            "RADIO": 0.35,
            "OOH": 0.35,
            "TV ABERTA/GLOBO": 0.15
            }
    
    # Criar dataframe de descontos a partir da configuração
    df_descontos = pd.DataFrame([
        {"Meio": meio, "Desconto": desconto} 
        for meio, desconto in descontos_config.items() 
        if meio != "TV ABERTA/GLOBO"  # Excluir a exceção Globo
    ])

    # Aplicar descontos (se as colunas necessárias existirem)
    if "Meio" in df.columns and "Inv_Base" in df.columns:
        # Junta pelo campo "Meio"
        df = df.merge(df_descontos, on="Meio", how="left")
        
        # Exceção: TV ABERTA + GLOBO usa desconto configurável
        if "Veículo" in df.columns:
            mask = (df["Meio"] == "TV ABERTA") & (df["Veículo"] == "GLOBO")
            df.loc[mask, "Desconto"] = descontos_config.get("TV ABERTA/GLOBO", 0.15)
        
        # Cria novas colunas
        df["inv_000"] = df["Inv_Base"] * 1000
        df["Investimento"] = df["inv_000"] * (1 - df["Desconto"])


    # Mapeamento de meses PT -> número
    map_meses = {
        "jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6,
        "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12
    }

    # Criar coluna Período (se as colunas Ano e Mês existirem)
    if "Ano" in df.columns and "Mês" in df.columns:
        # Garante que as colunas estão no formato certo
        df["Ano"] = pd.to_numeric(df["Ano"], errors="coerce")
        df["Mês"] = df["Mês"].str.strip().str.lower()
        
        # Converte para número do mês
        df["Mes_num"] = df["Mês"].map(map_meses)
        
        # Cria coluna Período como datetime
        df["Período"] = pd.to_datetime(
            dict(year=df["Ano"], month=df["Mes_num"], day=1)
        )

    # Tratamento de Praça e UF (se existirem)
    if "UF" in df.columns:
        df["UF"] = _strip_parentheses_nacional(df["UF"])

    if "Praça" in df.columns:
        # Primeiro normaliza (NACIONAL) -> NACIONAL
        praca_limpa = _strip_parentheses_nacional(df["Praça"])
        
        # Renomear Praça -> Praça_base
        df["Praça_base"] = praca_limpa
        df.drop(columns=["Praça"], inplace=True)
        
        # Criar nova coluna Praça com as regras
        def map_praca(val):
            if pd.isna(val): 
                return val
            v = _upper_norm(val)
            if v == "NACIONAL MERCHANDISING":
                return "NACIONAL"
            return _norm_txt(val)  # mantém como está (limpo)
        
        df["Praça"] = df["Praça_base"].apply(map_praca)

    # Limpa nomes de colunas finais
    df.columns = [c.strip() if isinstance(c, str) else c for c in df.columns]

    # Tipagem de 'Período' -> Period[M] quando possível
    if "Período" in df.columns and not isinstance(df["Período"].dtype, pd.PeriodDtype):
        try:
            df["Período"] = pd.to_datetime(df["Período"]).dt.to_period("M")
        except Exception:
            pass

    # Numérico em 'Investimento'
    if "Investimento" in df.columns:
        df["Investimento"] = pd.to_numeric(df["Investimento"], errors="coerce").fillna(0.0)

    return df


# ==============================================================
#   SEÇÃO: Persistência de Paleta
# ==============================================================
PALETA_PATH = "paleta_marcas.json"

def carregar_paleta() -> dict:
    """
    Lê paleta de cores do arquivo JSON `PALETA_PATH`.
    Retorna {marca: cor_hex} ou {} se não existir/der erro.
    """
    try:
        if os.path.exists(PALETA_PATH):
            with open(PALETA_PATH, "r", encoding="utf-8") as f:
                pal = json.load(f)
                return {str(k): str(v) for k, v in pal.items()}
    except Exception:
        pass
    return {}

def salvar_paleta(pal: dict) -> bool:
    """
    Salva a paleta atual no arquivo `PALETA_PATH`.
    Retorna True em caso de sucesso; False caso contrário.
    """
    try:
        with open(PALETA_PATH, "w", encoding="utf-8") as f:
            json.dump(pal, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False

# Estado inicial da paleta na sessão (não duplicar abaixo)
if "PALETA_MARCA" not in st.session_state:
    st.session_state.PALETA_MARCA = carregar_paleta()

# ==============================================================
#   SEÇÃO: Persistência de Paleta — PRAÇAS
# ==============================================================

PALETA_PRACA_PATH = "paleta_pracas.json"

def carregar_paleta_praca() -> dict:
    """
    Lê paleta de cores para Praças.
    Retorna {praca: cor_hex} ou {} se não existir/der erro.
    """
    try:
        if os.path.exists(PALETA_PRACA_PATH):
            with open(PALETA_PRACA_PATH, "r", encoding="utf-8") as f:
                pal = json.load(f)
                return {str(k): str(v) for k, v in pal.items()}
    except Exception:
        pass
    return {}

def salvar_paleta_praca(pal: dict) -> bool:
    """
    Salva a paleta de Praças em `PALETA_PRACA_PATH`.
    """
    try:
        with open(PALETA_PRACA_PATH, "w", encoding="utf-8") as f:
            json.dump(pal, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False

# Estado inicial da paleta de Praças na sessão
if "PALETA_PRACA" not in st.session_state:
    st.session_state.PALETA_PRACA = carregar_paleta_praca()

# ==============================================================
#   SEÇÃO: Persistência de Paleta — MEIOS
# ==============================================================

PALETA_MEIO_PATH = "paleta_meios.json"

def carregar_paleta_meio() -> dict:
    """
    Lê paleta de cores para Meios.
    Retorna {meio: cor_hex} ou {} se não existir/der erro.
    """
    try:
        if os.path.exists(PALETA_MEIO_PATH):
            with open(PALETA_MEIO_PATH, "r", encoding="utf-8") as f:
                pal = json.load(f)
                return {str(k): str(v) for k, v in pal.items()}
    except Exception:
        pass
    return {}

def salvar_paleta_meio(pal: dict) -> bool:
    """
    Salva a paleta de Meios em `PALETA_MEIO_PATH`.
    """
    try:
        with open(PALETA_MEIO_PATH, "w", encoding="utf-8") as f:
            json.dump(pal, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False

# Estado inicial da paleta de Meios na sessão
if "PALETA_MEIO" not in st.session_state:
    st.session_state.PALETA_MEIO = carregar_paleta_meio()


# ==============================================================
#   SEÇÃO: Utilitários (formatação e período)
# ==============================================================
def fmt_mmk(v) -> str:
    """
    Formata valores com abreviação e 2 casas decimais (PT-BR):
    - >= 1_000_000_000 -> 'X,XX B'
    - >= 1_000_000     -> 'X,XX MM'
    - >= 1_000         -> 'X,XX k'
    - Caso contrário, inteiro com separador PT-BR.
    """
    v = float(v)
    av = abs(v)

    def br(x, casas=2):
        s = f"{x:,.{casas}f}"
        # troca . e , para padrão PT-BR
        return s.replace(",", "X").replace(".", ",").replace("X", ".")

    if av >= 1_000_000_000:
        return f"{br(v/1_000_000_000, 2)} B"
    if av >= 1_000_000:
        return f"{br(v/1_000_000, 2)} MM"
    if av >= 1_000:
        return f"{br(v/1_000, 2)} k"

    # abaixo de 1 mil: mantém sem casas decimais (como no original)
    return br(v, 0)

def periodo_label(p1, p2) -> str:
    """
    Rótulo compacto para um intervalo (p1, p2):
    - 'MMM/MMM AAAA' se mesmo ano
    - 'MMM/AA a MMM/AA' se anos diferentes
    """
    d1, d2 = pd.to_datetime(p1), pd.to_datetime(p2)
    MES = ["JAN","FEV","MAR","ABR","MAI","JUN","JUL","AGO","SET","OUT","NOV","DEZ"]
    if d1.year == d2.year:
        return f"{MES[d1.month-1]}/{MES[d2.month-1]} {d1.year}"
    else:
        return f"{MES[d1.month-1]}/{str(d1.year)[-2:]} a {MES[d2.month-1]}/{str(d2.year)[-2:]}"

def coerce_period_to_ts(s: pd.Series) -> pd.Series:
    """
    Converte Série `s` (Período) para timestamps mensais.
    Aceita: Period[M], datetime64, string 'YYYY-MM-01'.
    """
    if isinstance(s.dtype, pd.PeriodDtype):
        return s.dt.to_timestamp()
    try:
        return pd.to_datetime(s)
    except Exception:
        return pd.to_datetime(s.astype(str), errors="coerce")

def make_y_ticks(max_val: float, n: int = 6) -> Tuple[List[float], List[str]]:
    """
    Gera até `n` ticks entre 0 e `max_val`, com rótulos fmt_mmk.
    Retorna (ticks, labels).
    """
    if max_val is None or not np.isfinite(max_val) or max_val <= 0:
        return [0.0], ["0"]
    vals = np.linspace(0, max_val, n)
    labels = [fmt_mmk(v) for v in vals]
    return vals.tolist(), labels

def build_palette(marcas: List[str], paleta_existente: dict) -> dict:
    """
    Constroi paleta para as `marcas` usando a paleta da sessão como base
    e cores fallback quando necessário.
    """
    fallbacks = ["#2b8cbe","#e34a33","#31a354","#756bb1","#fb6a4a",
                 "#fdae6b","#74c476","#9e9ac8","#6baed6","#fd8d3c"]
    palette = {}
    it = iter(fallbacks)
    for m in marcas:
        palette[m] = paleta_existente.get(m, next(it, "#999999"))
    return palette

# ==============================================================
#   SEÇÃO: Configuração de Descontos Editáveis
# ==============================================================

# Inicializa descontos padrão no session_state
if "descontos_config" not in st.session_state:
    st.session_state.descontos_config = {
        "JORNAL": 0.85,
        "TV ABERTA": 0.75,
        "REVISTA": 0.70,
        "DIGITAL": 0.70,
        "PAY TV": 0.65,
        "CINEMA": 0.50,
        "RADIO": 0.35,
        "OOH": 0.35,
        "TV ABERTA/GLOBO": 0.15  # Exceção Globo
    }

# ==============================================================
#   SEÇÃO: Entrada e Carregamento de Dados (MODIFICADO)
# ==============================================================
st.sidebar.header("Entrada de dados")

arquivo = st.sidebar.file_uploader(
    "Envie base_geral.xlsx",
    type=["xlsx"],
    help="Arquivo Excel com dados brutos na primeira aba."
)
usar_local = st.sidebar.checkbox("Usar base_geral.xlsx local", value=False)

#@st.cache_data
def carregar_df(file, usar_local: bool = False, _descontos_config=None) -> pd.DataFrame | None:
    """
    Lê o dataset a partir de:
      - arquivo base_geral.xlsx local (se `usar_local` for True), ou
      - arquivo enviado (XLSX).
    Aplica o processamento completo que estava no trat_monitor_aba.py.
    """
    if usar_local:
        if not os.path.exists("base_geral.xlsx"):
            return None
        df = processar_base_geral("base_geral.xlsx", descontos_config=_descontos_config)
    else:
        if file is None:
            return None
        # Salva temporariamente o arquivo enviado
        with open("temp_base_geral.xlsx", "wb") as f:
            f.write(file.getbuffer())
        df = processar_base_geral("temp_base_geral.xlsx", descontos_config=_descontos_config)
        # Remove arquivo temporário
        try:
            os.remove("temp_base_geral.xlsx")
        except FileNotFoundError:
                pass
        except PermissionError:
                pass
        except OSError:
                pass

    return df

# Carrega DF
df = carregar_df(arquivo, usar_local, st.session_state.get("descontos_config"))


if df is None:
    st.markdown("    ", unsafe_allow_html=True)
    st.markdown("""
    ### 📋 **Instruções para Carregar os Dados**
    
    Para começar a análise, você precisa fornecer o arquivo de dados:

    **1 - Nome do arquivo**
    - Altere o nome do arquivo para "base_geral" 
    - O arquivo deve estar no formato Excel (.xlsx)

    **2 - Upload do Arquivo**
    - Use o botão "Envie base_geral.xlsx" na barra lateral
    - Certifique-se de que o formato do arquivo é o mesmo do modelo.
    
    💡 **Dica:** O sistema processará automaticamente os dados brutos e aplicará todas as transformações necessárias.
    """)
    
    st.markdown("---")
    st.markdown("### ⚙️ **Configuração de Descontos**")
    st.markdown("Ajuste os valores de desconto que serão aplicados por meio de comunicação:")
    
    # Cria colunas para a tabela editável
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.markdown("**Meio de Comunicação**")
    with col2:
        st.markdown("**Desconto (%)**")
    
    # Interface editável para cada desconto
    for meio, desconto_atual in st.session_state.descontos_config.items():
        col1, col2 = st.columns([2, 1])
        with col1:
            st.text(meio)
        with col2:
            # Converte para percentual e permite edição
            novo_desconto = st.number_input(
                f"desconto_{meio}",
                min_value=0.0,
                max_value=100.0,
                value=desconto_atual * 100,
                step=0.1,
                format="%.1f",
                key=f"desc_{meio}",
                label_visibility="collapsed"
            )
            # Atualiza o session_state
            st.session_state.descontos_config[meio] = novo_desconto / 100
    
    st.stop()



# Validações mínimas
requeridas = {"Marca", "Período", "Investimento"}
faltam = requeridas - set(df.columns)
if faltam:
    st.error(f"Faltam colunas: {', '.join(sorted(faltam))}")
    st.stop()

# Limites de período globais (para sliders independentes nas abas)
serie_periodos = df["Período"].dropna()
if isinstance(serie_periodos.dtype, pd.PeriodDtype):
    dt_min = serie_periodos.min().to_timestamp().to_pydatetime()
    dt_max = serie_periodos.max().to_timestamp().to_pydatetime()
else:
    dt_min = pd.to_datetime(serie_periodos.min()).to_pydatetime()
    dt_max = pd.to_datetime(serie_periodos.max()).to_pydatetime()

# ==============================================================
#   SEÇÃO: Cabeçalho da Aplicação
# ==============================================================
st.title("Análise de Investimentos")

# (As funções de gráfico e as abas vêm nas próximas partes)

# ==============================================================
#   SEÇÃO: Funções de Preparação de Dados
# ==============================================================

def preparar_top10(dfe: pd.DataFrame, n: int = 10) -> tuple[pd.DataFrame, float]:
    """
    Agrega por 'Marca', ordena por 'Investimento' desc e retorna Top-N
    com colunas auxiliares para o gráfico de torre 100%.
    """
    agg = dfe.groupby("Marca", as_index=False)["Investimento"].sum()
    top = (agg.sort_values("Investimento", ascending=False)
               .head(n)
               .reset_index(drop=True))
    total = float(top["Investimento"].sum())
    top["pct"] = np.where(total > 0, top["Investimento"] / total, 0.0)
    top["y1"] = top["pct"].cumsum() * 100.0            # topo segmento
    top["y0"] = (top["pct"].cumsum() - top["pct"]) * 100.0  # base segmento
    top["y_mid"] = (top["y0"] + top["y1"]) / 2.0
    top["pct_label"] = (top["pct"] * 100).round(1).astype(str) + "%"
    return top, total


def preparar_por_marcas(dfe: pd.DataFrame, marcas_sel: list[str]) -> tuple[pd.DataFrame, float]:
    """
    Filtra dfe por marcas selecionadas e prepara colunas auxiliares
    para o gráfico de torre 100%.
    """
    base = dfe[dfe["Marca"].isin(marcas_sel)]
    agg = base.groupby("Marca", as_index=False)["Investimento"].sum()
    if agg.empty:
        empty = agg.assign(pct=0.0, y0=0.0, y1=0.0, y_mid=0.0, pct_label="0%")
        return empty, 0.0

    agg = agg.sort_values("Investimento", ascending=False).reset_index(drop=True)
    total = float(agg["Investimento"].sum())
    agg["pct"] = np.where(total > 0, agg["Investimento"] / total, 0.0)
    agg["y1"] = agg["pct"].cumsum() * 100.0
    agg["y0"] = (agg["pct"].cumsum() - agg["pct"]) * 100.0
    agg["y_mid"] = (agg["y0"] + agg["y1"]) / 2.0
    agg["pct_label"] = (agg["pct"] * 100).round(1).astype(str) + "%"
    return agg, total


# ==============================================================
#   SEÇÃO: Gráfico Torre Top-N (Plotly)
# ==============================================================

def torre_top10_plotly(
    dfe: pd.DataFrame,
    paleta_sessao: dict,
    n: int = 10,
    *,
    widget_prefix: str = "topn",
    show_palette_controls: bool = True,
    # ---------------- [AJUSTE] ----------------
    bar_width: float = 0.30,           # espessura da barra
    xdomain: tuple[float, float] = (0.35, 0.65),  # largura da área da barra
    legend_x: float = 0.28,            # proximidade da legenda (0=esq, 1=dir)
    legend_xanchor: str = "left"       # âncora da legenda
) -> tuple[go.Figure, pd.DataFrame]:
    """
    Torre 100% do Top-N (uma única barra empilhada por marca).
    """
    top, total = preparar_top10(dfe, n=n)
    marcas = top["Marca"].tolist()
    colors = build_palette(marcas, paleta_sessao)

    if show_palette_controls:
        with st.sidebar.expander("Ajustar Cores (Top-N)", expanded=False):
            for m in marcas:
                cor_atual = st.session_state.PALETA_MARCA.get(m, colors[m])
                nova_cor = st.color_picker(m, cor_atual, key=f"{widget_prefix}_color_{m}")
                st.session_state.PALETA_MARCA[m] = nova_cor
                colors[m] = nova_cor
            cA, cB = st.columns(2)
            with cA:
                if st.button("Salvar paleta (Top-N)", use_container_width=True, key=f"{widget_prefix}_save"):
                    ok = salvar_paleta(st.session_state.PALETA_MARCA)
                    st.toast("Paleta salva" if ok else "Falha ao salvar", icon="✅" if ok else "⚠️")
            with cB:
                if st.button("Recarregar paleta (Top-N)", use_container_width=True, key=f"{widget_prefix}_reload"):
                    st.session_state.PALETA_MARCA = carregar_paleta()
                    st.toast("Paleta recarregada", icon="🔄")
                    for m in marcas:
                        colors[m] = st.session_state.PALETA_MARCA.get(m, colors[m])

    xcat = ["Total"]
    fig = go.Figure()
    for _, r in top.iterrows():
        fig.add_trace(go.Bar(
            x=xcat,
            y=[r["pct"] * 100.0],
            name=str(r["Marca"]),
            marker_color=colors[r["Marca"]],
            hovertemplate=f"{r['Marca']}<br>Participação: {r['pct']*100:.0f}%<br>Valor: {fmt_mmk(r['Investimento'])}<extra></extra>"
        ))

    # Anotações (% internos) + callouts (direita)
    annotations, shapes = [], []
    for _, r in top.iterrows():
        ymid = r["y_mid"]
        annotations.append(dict(
            x=0.5, xref="x domain", y=ymid, yref="y",
            text=r["pct_label"], showarrow=False,
            font=dict(color="white", size=14),
            bgcolor="black", opacity=0.9, bordercolor="black", borderpad=4
        ))
        shapes.append(dict(
            type="line", xref="x domain", yref="y",
            x0=0.70, x1=0.88, y0=ymid, y1=ymid,
            line=dict(color="black", width=1)
        ))
        annotations.append(dict(
            x=0.90, xref="x domain", y=ymid, yref="y",
            text=fmt_mmk(r["Investimento"]), showarrow=False,
            font=dict(color="black", size=14), xanchor="left"
        ))

    annotations.append(dict(
        x=0.5, xref="x domain", y=105, yref="y",
        text=f"{fmt_mmk(total)}", showarrow=False,
        font=dict(color="black", size=20, family="Arial"), xanchor="center"
    ))

    # ---------------- [AJUSTE] largura da barra ----------------
    fig.update_traces(width=bar_width)

    fig.update_layout(
        barmode="stack",
        showlegend=True,
        legend=dict(
            orientation="v",
            x=legend_x, xanchor=legend_xanchor,  # [AJUSTE] legenda
            y=0.5, yanchor="middle",
            bgcolor="rgba(0,0,0,0)",
            traceorder="normal",
            font=dict(size=15),
            itemwidth=30
        ),
        margin=dict(l=60, r=60, t=110, b=90),
        height=820,
        xaxis=dict(
            showline=False, showticklabels=False, showgrid=False, zeroline=False,
            domain=list(xdomain)                    # [AJUSTE] domínio
        ),
        yaxis=dict(range=[-6, 108], showgrid=False, showticklabels=False, showline=False, zeroline=False),
        plot_bgcolor="white", paper_bgcolor="white",
        title=dict(text=""),
        annotations=annotations,
        shapes=shapes
    )
    return fig, top


# ==============================================================
#   SEÇÃO: Gráfico Torre por Marcas Selecionadas (ÚNICA DEFINIÇÃO)
# ==============================================================

def torre_marcas_plotly(
    dfe: pd.DataFrame,
    marcas_sel: list[str],
    sel_dt_ini, sel_dt_fim,
    paleta_sessao: dict,
    *,
    widget_prefix: str = "marcas",
    show_palette_controls: bool = True,
    # ---------------- [AJUSTE] ----------------
    bar_width: float = 0.30,
    lado_callout: str = "direito",  # "esquerdo" ou "direito"
    # Configurações para lado direito
    xdomain_dir: tuple[float, float] = (0.35, 0.65),
    legend_x_dir: float = 0.28,
    legend_anchor_dir: str = "left",
    # Configurações para lado esquerdo
    xdomain_esq: tuple[float, float] = (0.35, 0.65),
    legend_x_esq: float = 0.72,
    legend_anchor_esq: str = "right"
) -> tuple[go.Figure, pd.DataFrame]:
    """
    Torre 100% das marcas selecionadas (uma única barra empilhada).
    """
    # ------ filtra por período ------
    per_ts = coerce_period_to_ts(dfe["Período"])
    base = dfe.loc[(per_ts >= sel_dt_ini) & (per_ts <= sel_dt_fim)].copy()

    # ------ prepara dados ------
    top, total = preparar_por_marcas(base, marcas_sel)
    marcas = top["Marca"].tolist()
    colors = build_palette(marcas, paleta_sessao)

    # ------ controles de paleta (opcional) ------
    if show_palette_controls:
        with st.sidebar.expander("Ajustar Cores (Marcas)", expanded=False):
            for m in marcas:
                cor_atual = st.session_state.PALETA_MARCA.get(m, colors[m])
                nova_cor = st.color_picker(m, cor_atual, key=f"{widget_prefix}_color_{m}")
                st.session_state.PALETA_MARCA[m] = nova_cor
                colors[m] = nova_cor
            cA, cB = st.columns(2)
            with cA:
                if st.button("Salvar paleta (Marcas)", use_container_width=True, key=f"{widget_prefix}_save"):
                    ok = salvar_paleta(st.session_state.PALETA_MARCA)
                    st.toast("Paleta salva" if ok else "Falha ao salvar", icon="✅" if ok else "⚠️")
            with cB:
                if st.button("Recarregar paleta (Marcas)", use_container_width=True, key=f"{widget_prefix}_reload"):
                    st.session_state.PALETA_MARCA = carregar_paleta()
                    st.toast("Paleta recarregada", icon="🔄")
                    for m in marcas:
                        colors[m] = st.session_state.PALETA_MARCA.get(m, colors[m])

    # ------ gráfico base (1 categoria 'Total') ------
    xcat = ["Total"]
    fig = go.Figure()
    for _, r in top.iterrows():
        fig.add_trace(go.Bar(
            x=xcat,
            y=[r["pct"] * 100.0],
            name=str(r["Marca"]),
            marker_color=colors[r["Marca"]],
            hovertemplate=f"{r['Marca']}<br>Participação: {r['pct']*100:.0f}%<br>Valor: {fmt_mmk(r['Investimento'])}<extra></extra>"
        ))

    # ------ posicionamento por lado ------
    if lado_callout == "esquerdo":
        x_text = 0.10
        x_line_start = 0.30
        x_line_end = 0.12
        anchor = "right"
        legend_x = legend_x_esq
        legend_xanchor = legend_anchor_esq
        domain_x = xdomain_esq          # [AJUSTE] domínio quando à esquerda
    else:
        x_text = 0.90
        x_line_start = 0.70
        x_line_end = 0.88
        anchor = "left"
        legend_x = legend_x_dir
        legend_xanchor = legend_anchor_dir
        domain_x = xdomain_dir          # [AJUSTE] domínio quando à direita

    # ------ anotações e callouts ------
    annotations, shapes = [], []
    for _, r in top.iterrows():
        ymid = r["y_mid"]
        # % interno
        annotations.append(dict(
            x=0.5, xref="x domain", y=ymid, yref="y",
            text=r["pct_label"], showarrow=False,
            font=dict(color="white", size=14),
            bgcolor="black", opacity=0.9, bordercolor="black", borderpad=4
        ))
        # linha do callout
        shapes.append(dict(
            type="line", xref="x domain", yref="y",
            x0=x_line_start, x1=x_line_end, y0=ymid, y1=ymid,
            line=dict(color="black", width=1)
        ))
        # valor do callout
        annotations.append(dict(
            x=x_text, xref="x domain", y=ymid, yref="y",
            text=fmt_mmk(r["Investimento"]), showarrow=False,
            font=dict(color="black", size=14), xanchor=anchor
        ))

    # total no topo e período no rodapé
    annotations.append(dict(
        x=0.5, xref="x domain", y=105, yref="y",
        text=f"{fmt_mmk(total)}", showarrow=False,
        font=dict(color="black", size=20, family="Arial"), xanchor="center"
    ))
    annotations.append(dict(
        x=0.5, xref="x domain", y=-4, yref="y",
        text=periodo_label(sel_dt_ini, sel_dt_fim), showarrow=False,
        font=dict(color="black", size=13), xanchor="center"
    ))

    # ---------------- [AJUSTE] largura da barra ----------------
    fig.update_traces(width=bar_width)

    # ------ layout final ------
    fig.update_layout(
        barmode="stack",
        showlegend=True,
        legend=dict(
            orientation="v",
            x=legend_x, xanchor=legend_xanchor,  # [AJUSTE] proximidade/âncora da legenda
            y=0.5, yanchor="middle",
            bgcolor="rgba(0,0,0,0)",
            traceorder="normal",
            font=dict(size=15),
            itemwidth=30
        ),
        margin=dict(l=80, r=80, t=110, b=90),
        height=820,
        xaxis=dict(
            showline=False, showticklabels=False, showgrid=False, zeroline=False,
            domain=list(domain_x)                 # [AJUSTE] largura da área da barra
        ),
        yaxis=dict(range=[-6, 108], showgrid=False, showticklabels=False, showline=False, zeroline=False),
        plot_bgcolor="white", paper_bgcolor="white",

        # ---------------- [AJUSTE] centralização do título ----------------

        title=dict(text=""), 
        annotations=annotations,
        shapes=shapes
    )
    return fig, top

# ==============================================================
#   SEÇÃO: Gráfico — INVESTIMENTO POR PRAÇA (100% empilhado)
# ==============================================================

def grafico_investimento_por_praca(
    dfe: pd.DataFrame,
    marcas_sel: list[str],
    sel_dt_ini, sel_dt_fim,
    *,
    widget_prefix: str = "pracas",
    show_palette_controls: bool = True,
    bar_width: float = 0.55  # [AJUSTE] espessura das barras (todas as marcas)
) -> tuple[go.Figure, pd.DataFrame]:
    """
    Monta um gráfico de barras verticais 100% empilhadas:
      - Eixo X: Marcas selecionadas (uma barra por marca)
      - Stack: Praças (cores por praça), com % dentro da barra (via annotations)
      - Topo de cada barra: valor absoluto abreviado (MM / k)
      - Legenda horizontal na parte inferior
      - Título principal (caps) + subtítulo com faixa de tempo
    """

    # ---------------- Filtra por período e marcas ----------------
    per_ts = coerce_period_to_ts(dfe["Período"])
    base = dfe.loc[(per_ts >= sel_dt_ini) & (per_ts <= sel_dt_fim)].copy()
    base = base[base["Marca"].isin(marcas_sel)].copy()
    base["Praça_base"] = base["Praça"]

    if base.empty:
        fig = go.Figure()
        fig.update_layout(
            title=dict(
                text="INVESTIMENTO POR PRAÇA<br><span style='font-size:14px;'>Sem dados para os filtros</span>",
                x=0.5, xanchor="center"
            ),
            height=500
        )
        return fig

    # ---------------- Agregações ----------------
    # total por marca (para anotar no topo)
    totais_por_marca = base.groupby("Marca", as_index=False)["Investimento"].sum()

    # --- [INÍCIO DO AJUSTE] Agrupamento de praças pequenas em 'OUTROS' ---
    # Calcula o investimento total para determinar a significância das praças
    investimento_total_geral = base["Investimento"].sum()

    # Calcula a participação de cada praça no investimento total
    participacao_pracas = base.groupby("Praça")["Investimento"].sum()
    participacao_pracas = participacao_pracas / investimento_total_geral

    # Identifica praças com menos de 2% de participação
    pracas_outras = participacao_pracas[participacao_pracas < 0.02].index.tolist()
    # --- [INÍCIO DO AJUSTE] Captura o detalhe das praças agrupadas em 'OUTROS' ---
    df_outros_detalhe = base[base["Praça_base"].isin(pracas_outras)].copy()
    if not df_outros_detalhe.empty:
        df_outros_detalhe = df_outros_detalhe.groupby("Praça_base", as_index=False)["Investimento"].sum()
        df_outros_detalhe["Participação"] = df_outros_detalhe["Investimento"] / investimento_total_geral
        df_outros_detalhe["Participação"] = (df_outros_detalhe["Participação"] * 100).round(2).astype(str) + "%"
        df_outros_detalhe["Investimento"] = df_outros_detalhe["Investimento"].apply(lambda x: f"R$ {x:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        df_outros_detalhe = df_outros_detalhe.rename(columns={"Praça_base": "Praça Agrupada", "Investimento": "Investimento Total"})
    else:
        df_outros_detalhe = pd.DataFrame(columns=["Praça Agrupada", "Investimento Total", "Participação"])
    # --- [FIM DO AJUSTE] Captura o detalhe das praças agrupadas em 'OUTROS' ---

    # Renomeia as praças pequenas para 'OUTROS'
    base["Praça"] = base["Praça"].apply(lambda x: "OUTROS" if x in pracas_outras else x)
    # --- [FIM DO AJUSTE] Agrupamento de praças pequenas em 'OUTROS' ---

    # tabela Marca x Praça com valores (preenche 0)
    mat_val = (
        base.groupby(["Marca", "Praça"], as_index=False)["Investimento"].sum()
            .pivot(index="Marca", columns="Praça", values="Investimento")
            .fillna(0.0)
    )

    # Ordena marcas por total (desc) respeitando a seleção
    ordem_marcas = (
        totais_por_marca.sort_values("Investimento", ascending=False)["Marca"].tolist()
    )
    mat_val = mat_val.reindex(index=ordem_marcas)  # reordena linhas
    pracas = mat_val.columns.tolist()              # colunas -> ordem das pilhas


    # ---------------- Paleta de cores das Praças ----------------
    cores = {}
    fallbacks = ["#e34a33","#2b8cbe","#31a354","#756bb1","#fb6a4a",
                 "#fdae6b","#74c476","#9e9ac8","#6baed6","#fd8d3c",
                 "#636363","#1f78b4","#33a02c","#e31a1c","#ff7f00"]
    it = iter(fallbacks)
    
    # Garante que 'OUTROS' tenha uma cor consistente, se existir
    if "OUTROS" in pracas:
        cores["OUTROS"] = st.session_state.PALETA_PRACA.get("OUTROS", "#A9A9A9") # Cor cinza para 'OUTROS'

    for p in pracas:
        if p != "OUTROS": # Não sobrescreve a cor de 'OUTROS'
            cores[p] = st.session_state.PALETA_PRACA.get(p, next(it, "#999999"))

    # Remove as praças originais que foram agrupadas de st.session_state.PALETA_PRACA
    # para evitar que apareçam nos controles de cor se não estiverem mais ativas
    pracas_atuais_e_outros = set(pracas)
    pracas_para_remover_da_paleta = [p for p in st.session_state.PALETA_PRACA.keys() if p not in pracas_atuais_e_outros]
    for p_rem in pracas_para_remover_da_paleta:
        del st.session_state.PALETA_PRACA[p_rem]


    # --------- Controles de paleta no sidebar (opcional) ---------
    if show_palette_controls:
        with st.sidebar.expander("Ajustar Cores (Praças)", expanded=False):
            for p in pracas:
                cor_atual = st.session_state.PALETA_PRACA.get(p, cores[p])
                nova_cor = st.color_picker(p, cor_atual, key=f"{widget_prefix}_cor_{p}")
                st.session_state.PALETA_PRACA[p] = nova_cor
                cores[p] = nova_cor
            c1, c2 = st.columns(2)
            with c1:
                if st.button("Salvar paleta (Praças)", use_container_width=True, key=f"{widget_prefix}_save"):
                    ok = salvar_paleta_praca(st.session_state.PALETA_PRACA)
                    st.toast("Paleta salva" if ok else "Falha ao salvar", icon="✅" if ok else "⚠️")
            with c2:
                if st.button("Recarregar paleta (Praças)", use_container_width=True, key=f"{widget_prefix}_reload"):
                    st.session_state.PALETA_PRACA = carregar_paleta_praca()
                    st.toast("Paleta recarregada", icon="🔄")
                    for p in pracas:
                        cores[p] = st.session_state.PALETA_PRACA.get(p, cores[p])

    # ---------------- Percentuais (por marca) ----------------
    linha_totais = mat_val.sum(axis=1).replace(0, np.nan)
    mat_pct = mat_val.div(linha_totais, axis=0).fillna(0.0) * 100.0

    # --- [INÍCIO DO AJUSTE] Ordenação das praças por investimento total (maior na base) ---
    # Calcula o investimento total por praça para ordenação
    investimento_por_praca_total = base.groupby("Praça")["Investimento"].sum()
    # Ordena as praças do MAIOR para o MENOR investimento para que as maiores fiquem na base da pilha
    pracas_ordenadas = investimento_por_praca_total.sort_values(ascending=True).index.tolist()
    # --- [FIM DO AJUSTE] Ordenação das praças por investimento total (maior na base) ---

    # ---------------- Gráfico: uma trace por praça ----------------
    x = mat_val.index.tolist()  # marcas no eixo X
    fig = go.Figure()
    # Itera pelas praças na ordem decrescente de investimento para empilhar corretamente
    for p in reversed(pracas_ordenadas): # Usar a lista de praças ordenadas AQUI e INVERTIDA
        y_pct = mat_pct[p].tolist()
        # (Opção 1 com annotations: NÃO colocamos textos embutidos nos traces)
        fig.add_trace(go.Bar(
            x=x,
            y=y_pct,
            name=str(p),
            marker_color=cores[p],
            hovertemplate=f"{p}<br>%{{x}}<br>Participação: %{{y:.0f}}%<extra></extra>"
        ))

    # ---------------- [AJUSTE] rótulos (%) como anotações com fundo preto ----------------
    # Mostra rótulo apenas para segmentos >= THRESH_PCT (evita poluição visual)
    THRESH_PCT = 1  # [AJUSTE] altere p/ 2, 3... se quiser esconder fatias muito pequenas
    annotations = []

    # Para cada barra (marca), acumulamos a pilha e anotamos o centro de cada segmento
    for m in x:
        cum = 0.0
        # Itera pelas praças na mesma ordem em que foram adicionadas ao gráfico (decrescente de investimento)
        for p in reversed(pracas_ordenadas): # Usar a lista de praças ordenadas AQUI e INVERTIDA
            v = float(mat_pct.loc[m, p]) if p in mat_pct.columns else 0.0
            if v < THRESH_PCT or v == 0.0:
                cum += v
                continue
            y_mid = cum + v / 2.0
            annotations.append(dict(
                x=m, y=y_mid, xref="x", yref="y",
                text=f"{v:.1f}%", showarrow=False,
                font=dict(color="white", size=12),
                bgcolor="black", opacity=0.9,
                bordercolor="black", borderpad=3
            ))
            cum += v


    # ---------------- Anotações de total no topo de cada coluna ----------------
    for m in x:
        total_marca = float(totais_por_marca.loc[totais_por_marca["Marca"] == m, "Investimento"].values[0])
        annotations.append(dict(
            x=m, y=105, xref="x", yref="y",
            text=f"{fmt_mmk(total_marca)}", showarrow=False,
            font=dict(color="black", size=16, family="Arial"), xanchor="center"
        ))

    # ---------------- Layout ----------------
    fig.update_traces(width=bar_width)   # [AJUSTE] espessura das barras (todas as marcas)

    # Título + subtítulo (linha abaixo via <br>)
    #sub = periodo_label(sel_dt_ini, sel_dt_fim).replace(" a ", " — ")
    #title_html = f"<b>INVESTIMENTO POR PRAÇA</b><br><span style='font-size:15px;'>{sub}</span>"

    fig.update_layout(
        barmode="stack",
        showlegend=True,
        legend=dict(
            orientation="h",    # [AJUSTE] legenda na parte inferior
            x=0.0, xanchor="left",
            y=-0.15, yanchor="top",
            bgcolor="rgba(0,0,0,0)",
            traceorder="normal",
            font=dict(size=12)
        ),
        margin=dict(l=60, r=40, t=90, b=120),
        height=820,
        xaxis=dict(
            title=None,
            showline=False, showgrid=False, zeroline=False
        ),
        yaxis=dict(
            range=[-6, 108],     # 0 a 100% (com folga para rótulos/topo)
            showgrid=False, showticklabels=False, showline=False, zeroline=False,
            title=None
        ),
        plot_bgcolor="white", paper_bgcolor="white",
        title=dict(text="", x=0.5, xanchor="center", y=0.98, yanchor="top"),
        annotations=annotations
    )

    return fig, df_outros_detalhe


# ==============================================================
#   SEÇÃO: Gráfico — INVESTIMENTO POR MEIO (100% empilhado)
# ==============================================================

def grafico_investimento_por_meio(
    dfe: pd.DataFrame,
    marcas_sel: list[str],
    sel_dt_ini, sel_dt_fim,
    *,
    widget_prefix: str = "meios",
    show_palette_controls: bool = True,
    bar_width: float = 0.55  # [AJUSTE] espessura das barras (todas as marcas)
) -> tuple[go.Figure, pd.DataFrame]:
    """
    Barras verticais 100% empilhadas por 'Meio':
      - Eixo X: Marcas selecionadas (uma barra por marca)
      - Stack: Meios (cores por meio), com % dentro (via annotations)
      - Topo: valor absoluto abreviado (MM / k)
      - Legenda horizontal inferior
      - Título (caps) + subtítulo com faixa de tempo
    """

    # ---------------- Filtra por período e marcas ----------------
    per_ts = coerce_period_to_ts(dfe["Período"])
    base = dfe.loc[(per_ts >= sel_dt_ini) & (per_ts <= sel_dt_fim)].copy()
    base = base[base["Marca"].isin(marcas_sel)].copy()

    if base.empty:
        fig = go.Figure()
        fig.update_layout(
            title=dict(
                text="INVESTIMENTO POR MEIO<br><span style='font-size:14px;'>Sem dados para os filtros</span>",
                x=0.5, xanchor="center"
            ),
            height=500
        )
        return fig, pd.DataFrame()

    # ---------------- Agregações ----------------
    totais_por_marca = base.groupby("Marca", as_index=False)["Investimento"].sum()

    # Tabela Marca x Meio com valores (preenche 0)
    mat_val = (
        base.groupby(["Marca", "Meio"], as_index=False)["Investimento"].sum()
            .pivot(index="Marca", columns="Meio", values="Investimento")
            .fillna(0.0)
    )

    # Ordena marcas por total desc (respeitando seleção)
    ordem_marcas = (
        totais_por_marca.sort_values("Investimento", ascending=False)["Marca"].tolist()
    )
    mat_val = mat_val.reindex(index=ordem_marcas)
    meios = mat_val.columns.tolist()

    # ---------------- Paleta de cores dos Meios ----------------
    cores = {}
    fallbacks = ["#e34a33","#2b8cbe","#31a354","#756bb1","#fb6a4a",
                 "#fdae6b","#74c476","#9e9ac8","#6baed6","#fd8d3c",
                 "#636363","#1f78b4","#33a02c","#e31a1c","#ff7f00"]
    it = iter(fallbacks)
    for m in meios:
        cores[m] = st.session_state.PALETA_MEIO.get(m, next(it, "#999999"))

    # --------- Controles de paleta no sidebar (opcional) ---------
    if show_palette_controls:
        with st.sidebar.expander("Ajustar Cores (Meios)", expanded=False):
            for m in meios:
                cor_atual = st.session_state.PALETA_MEIO.get(m, cores[m])
                nova_cor = st.color_picker(m, cor_atual, key=f"{widget_prefix}_cor_{m}")
                st.session_state.PALETA_MEIO[m] = nova_cor
                cores[m] = nova_cor
            c1, c2 = st.columns(2)
            with c1:
                if st.button("Salvar paleta (Meios)", use_container_width=True, key=f"{widget_prefix}_save"):
                    ok = salvar_paleta_meio(st.session_state.PALETA_MEIO)
                    st.toast("Paleta salva" if ok else "Falha ao salvar", icon="✅" if ok else "⚠️")
            with c2:
                if st.button("Recarregar paleta (Meios)", use_container_width=True, key=f"{widget_prefix}_reload"):
                    st.session_state.PALETA_MEIO = carregar_paleta_meio()
                    st.toast("Paleta recarregada", icon="🔄")
                    for m in meios:
                        cores[m] = st.session_state.PALETA_MEIO.get(m, cores[m])

    # ---------------- Percentuais (por marca) ----------------
    linha_totais = mat_val.sum(axis=1).replace(0, np.nan)
    mat_pct = mat_val.div(linha_totais, axis=0).fillna(0.0) * 100.0

    # ---------------- Gráfico: uma trace por meio ----------------
    x = mat_val.index.tolist()  # marcas no eixo X
    fig = go.Figure()
    for m in meios:
        y_pct = mat_pct[m].tolist()
        fig.add_trace(go.Bar(
            x=x,
            y=y_pct,
            name=str(m),
            marker_color=cores[m],
            hovertemplate=f"{m}<br>%{{x}}<br>Participação: %{{y:.0f}}%<extra></extra>"
        ))

    # ---------------- [AJUSTE] rótulos (%) como anotações com fundo preto ----------------
    THRESH_PCT = 1  # [AJUSTE] altere p/ 2, 3... se quiser esconder fatias muito pequenas
    annotations = []

    # Para cada barra (marca), acumulamos a pilha e anotamos o centro de cada segmento
    for marca in x:
        cum = 0.0
        for meio in meios:
            v = float(mat_pct.loc[marca, meio]) if meio in mat_pct.columns else 0.0
            if v < THRESH_PCT or v == 0.0:
                cum += v
                continue
            y_mid = cum + v / 2.0
            annotations.append(dict(
                x=marca, y=y_mid, xref="x", yref="y",
                text=f"{v:.1f}%", showarrow=False,
                font=dict(color="white", size=12),
                bgcolor="black", opacity=0.9,
                bordercolor="black", borderpad=3
            ))
            cum += v

    # ---------------- Anotações de total no topo de cada coluna ----------------
    for marca in x:
        total_marca = float(totais_por_marca.loc[totais_por_marca["Marca"] == marca, "Investimento"].values[0])
        annotations.append(dict(
            x=marca, y=105, xref="x", yref="y",
            text=f"{fmt_mmk(total_marca)}", showarrow=False,
            font=dict(color="black", size=16, family="Arial"), xanchor="center"
        ))

    # ---------------- Layout ----------------
    fig.update_traces(width=bar_width)   # [AJUSTE] espessura das barras (todas as marcas)

    # Título + subtítulo (linha abaixo via <br>)
    #sub = periodo_label(sel_dt_ini, sel_dt_fim).replace(" a ", " — ")
    #title_html = f"<b>INVESTIMENTO POR MEIO</b><br><span style='font-size:15px;'>{sub}</span>"

    fig.update_layout(
        barmode="stack",
        showlegend=True,
        legend=dict(
            orientation="h",    # [AJUSTE] legenda na parte inferior
            x=0.0, xanchor="left",
            y=-0.15, yanchor="top",
            bgcolor="rgba(0,0,0,0)",
            traceorder="normal",
            font=dict(size=12)
        ),
        margin=dict(l=60, r=40, t=90, b=120),
        height=820,
        xaxis=dict(
            title=None,
            showline=False, showgrid=False, zeroline=False
        ),
        yaxis=dict(
            range=[-6, 108],     # 0 a 100% (com folga para rótulos/topo)
            showgrid=False, showticklabels=False, showline=False, zeroline=False,
            title=None
        ),
        plot_bgcolor="white", paper_bgcolor="white",
        title=dict(text=" ", x=0.5, xanchor="center", y=0.98, yanchor="top"),
        annotations=annotations
    )

    return fig, mat_val


# ==============================================================
#   SEÇÃO: Gráfico — EVOLUÇÃO TEMPORAL (linha)
# ==============================================================

def grafico_evolucao_temporal(
    dfe: pd.DataFrame,
    marcas_sel: list[str],
    sel_dt_ini, sel_dt_fim,
    paleta_sessao: dict,
    *,
    widget_prefix: str = "evolucao",
    show_palette_controls: bool = True
) -> go.Figure:
    """
    Gráfico de linha mostrando a evolução temporal do investimento
    para as marcas selecionadas.
    """
    # Filtra por período e marcas
    per_ts = coerce_period_to_ts(dfe["Período"])
    base = dfe.loc[(per_ts >= sel_dt_ini) & (per_ts <= sel_dt_fim)].copy()
    base = base[base["Marca"].isin(marcas_sel)].copy()

    if base.empty:
        fig = go.Figure()
        fig.update_layout(
            title=dict(
                text="EVOLUÇÃO TEMPORAL<br><span style='font-size:14px;'>Sem dados para os filtros</span>",
                x=0.5, xanchor="center"
            ),
            height=500
        )
        return fig

    # Converte período para timestamp para o gráfico
    base["Período_ts"] = coerce_period_to_ts(base["Período"])

    # Agrega por marca e período
    evolucao = (
        base.groupby(["Marca", "Período_ts"], as_index=False)["Investimento"].sum()
    )

    # Paleta de cores
    marcas = evolucao["Marca"].unique().tolist()
    colors = build_palette(marcas, paleta_sessao)

    # Controles de paleta (opcional)
    if show_palette_controls:
        with st.sidebar.expander("Ajustar Cores (Evolução)", expanded=False):
            for m in marcas:
                cor_atual = st.session_state.PALETA_MARCA.get(m, colors[m])
                nova_cor = st.color_picker(m, cor_atual, key=f"{widget_prefix}_color_{m}")
                st.session_state.PALETA_MARCA[m] = nova_cor
                colors[m] = nova_cor
            cA, cB = st.columns(2)
            with cA:
                if st.button("Salvar paleta (Evolução)", use_container_width=True, key=f"{widget_prefix}_save"):
                    ok = salvar_paleta(st.session_state.PALETA_MARCA)
                    st.toast("Paleta salva" if ok else "Falha ao salvar", icon="✅" if ok else "⚠️")
            with cB:
                if st.button("Recarregar paleta (Evolução)", use_container_width=True, key=f"{widget_prefix}_reload"):
                    st.session_state.PALETA_MARCA = carregar_paleta()
                    st.toast("Paleta recarregada", icon="🔄")
                    for m in marcas:
                        colors[m] = st.session_state.PALETA_MARCA.get(m, colors[m])

    # Cria o gráfico
    fig = go.Figure()

    for marca in marcas:
        dados_marca = evolucao[evolucao["Marca"] == marca]
        fig.add_trace(go.Scatter(
            x=dados_marca["Período_ts"],
            y=dados_marca["Investimento"],
            mode="lines+markers",
            name=marca,
            line=dict(color=colors[marca], width=3),
            marker=dict(color=colors[marca], size=8),
            hovertemplate=f"{marca}<br>%{{x}}<br>Investimento: {fmt_mmk('%{y}')}<extra></extra>"
        ))

    # Calcula ticks do eixo Y
    max_val = evolucao["Investimento"].max() if not evolucao.empty else 0
    y_ticks, y_labels = make_y_ticks(max_val)

    # Layout
    fig.update_layout(
        title=dict(
            text="EVOLUÇÃO TEMPORAL DO INVESTIMENTO",
            x=0.5, xanchor="center"
        ),
        xaxis=dict(
            title="Período",
            showgrid=True,
            gridcolor="lightgray"
        ),
        yaxis=dict(
            title="Investimento",
            tickvals=y_ticks,
            ticktext=y_labels,
            showgrid=True,
            gridcolor="lightgray"
        ),
        legend=dict(
            orientation="v",
            x=1.02, xanchor="left",
            y=1, yanchor="top"
        ),
        margin=dict(l=60, r=120, t=80, b=60),
        height=600,
        plot_bgcolor="white",
        paper_bgcolor="white"
    )

    return fig


# ==============================================================
#   SEÇÃO: Função auxiliar para export PNG
# ==============================================================

def export_plotly_png_current_size(fig: go.Figure) -> io.BytesIO:
    """
    Exporta a figura Plotly para PNG respeitando width/height atuais.
    """
    w = int(fig.layout.width) if fig.layout.width else 900
    h = int(fig.layout.height) if fig.layout.height else 900
    buf = io.BytesIO()
    fig.write_image(buf, format="png", width=w, height=h, scale=1)
    buf.seek(0)
    return buf

# ==============================================================
#   SEÇÃO: Abas e Renderização
# ==============================================================
# Observação:
# - Períodos mínimos/máximos (dt_min/dt_max) já foram calculados na Parte 1.
# - As funções torre_top10_plotly e torre_plotly_por_marcas estão na Parte 2.

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "Torre Top-N",
    "Seleção de Marcas",
    "Comparar Períodos",
    "Séries Temporais",
    "Investimento por Praça",
    "Investimento por Meio"
])


# ==============================================================
#   ABA 1: Torre Top-N
# ==============================================================
with tab1:
    st.subheader("Participação por Marca — Top-N")

    # Filtros próprios desta aba
    sel_dt_ini_1, sel_dt_fim_1 = st.slider(
        "Período (Top-N)",
        min_value=dt_min, max_value=dt_max,
        value=(dt_min, dt_max), format="MM/YYYY",
        key="periodo_topn"
    )

    # Filtra por período
    per_ts_1 = coerce_period_to_ts(df["Período"])
    df_topn = df[(per_ts_1 >= sel_dt_ini_1) & (per_ts_1 <= sel_dt_fim_1)].copy()

    # Top-N
    top_n = st.radio("Top N", [3, 5, 7, 10], index=3, horizontal=True, key="topn_n")

    # Gráfico
    fig1, top_tab = torre_top10_plotly(
        df_topn, st.session_state.PALETA_MARCA, n=top_n,
        widget_prefix="topn1",
        show_palette_controls=True,

        # --------------- [AJUSTE ABA 1] ---------------
        bar_width=0.30,         # espessura da barra
        xdomain=(0.35, 0.65),   # domínio da barra (largura da área)
        legend_x=0.28,          # proximidade da legenda
        legend_xanchor="left"
        # ----------------------------------------------
    )
    st.plotly_chart(fig1, use_container_width=True)

    # Tabela
    df_tabela = top_tab.copy()
    df_tabela["Investimento"] = df_tabela["Investimento"].apply(
        lambda x: f"R$ {x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    )
    df_tabela = df_tabela[["Marca", "Investimento", "pct_label"]].rename(
        columns={"pct_label": "Participação"}
    )
    with st.expander("Ver tabela (Top-N)"):
        st.dataframe(df_tabela, use_container_width=True)

    # Download PNG
    st.download_button(
        "Baixar PNG (tamanho atual)",
        data=export_plotly_png_current_size(fig1),
        file_name="torre_topN.png",
        mime="image/png",
        key="dl_png_tab1",
        use_container_width=True
    )

    # Download Excel
    buf1 = io.BytesIO()
    with pd.ExcelWriter(buf1, engine="openpyxl") as writer:
        df_tabela.to_excel(writer, index=False, sheet_name="TopN")
    buf1.seek(0)
    st.download_button(
        label="Baixar tabela (Excel)",
        data=buf1,
        file_name="topN_marcas.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="dl_xlsx_tab1",
        use_container_width=True
    )


# ==============================================================
#   ABA 2: Seleção de Marcas (Torre 100%)
# ==============================================================
with tab2:
    st.subheader("Seleção de Marcas — Torre 100%")

    # Período desta aba
    sel_dt_ini_2, sel_dt_fim_2 = st.slider(
        "Período (Seleção)",
        min_value=dt_min, max_value=dt_max,
        value=(dt_min, dt_max), format="MM/YYYY",
        key="periodo_sel"
    )

    per_ts_2 = coerce_period_to_ts(df["Período"])
    df_sel = df[(per_ts_2 >= sel_dt_ini_2) & (per_ts_2 <= sel_dt_fim_2)].copy()

    # Seleção de marcas
    df_sel["Marca"] = df_sel["Marca"].astype("string").str.strip()
    marcas_opts = sorted(
    df_sel["Marca"].dropna().unique().tolist(),
    key=lambda s: str(s).casefold()
    )
    sugestao = (
        df_sel.groupby("Marca")["Investimento"].sum()
             .sort_values(ascending=False).head(5).index.tolist()
    )
    sugestao = [m for m in sugestao if m in marcas_opts]

    marcas_sel = st.multiselect(
        "Marcas",
        options=marcas_opts,
        default=sugestao,
        help="Escolha 1 ou mais marcas.",
        key="marcas_sel_tab2"
    )
# NOVO: Salva a seleção principal no estado da sessão
    st.session_state.marcas_selecao_principal = marcas_sel
    if not marcas_sel:
        st.info("Selecione pelo menos uma marca para exibir o gráfico.")
    else:
        fig2, top2 = torre_marcas_plotly(
            df_sel, marcas_sel, sel_dt_ini_2, sel_dt_fim_2,
            st.session_state.PALETA_MARCA,
            lado_callout="direito",
            widget_prefix="sel1",
            show_palette_controls=True,

            # --------------- [AJUSTE ABA 2] ---------------
            bar_width=0.40,               # espessura da barra
            xdomain_dir=(0.32, 0.68),     # domínio da barra (lado direito)
            legend_x_dir=0.20,            # proximidade da legenda
            legend_anchor_dir="left"
            # ----------------------------------------------
        )
        st.plotly_chart(fig2, use_container_width=True)

        # Tabela
        df_tab2 = top2.copy()
        df_tab2["Investimento"] = df_tab2["Investimento"].apply(
            lambda x: f"R$ {x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        )
        df_tab2 = df_tab2[["Marca", "Investimento", "pct_label"]].rename(
            columns={"pct_label": "Participação"}
        )
        with st.expander("Ver tabela (Seleção)"):
            st.dataframe(df_tab2, use_container_width=True)

        # Download Excel
        buf2 = io.BytesIO()
        with pd.ExcelWriter(buf2, engine="openpyxl") as writer:
            df_tab2.to_excel(writer, index=False, sheet_name="Selecao")
        buf2.seek(0)
        st.download_button(
            label="Baixar tabela (Excel)",
            data=buf2,
            file_name="selecionadas_marcas.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="dl_xlsx_tab2",
            use_container_width=True
        )


# ==============================================================
#   ABA 3: Comparar Períodos (mesmas marcas, 2 torres lado a lado)
# ==============================================================
with tab3:
    st.subheader("Comparar Períodos com Mesmas Marcas")

    # Linha de filtros (em cima)
    c_marcas, c_esq, c_dir = st.columns([2, 1, 1])

    with c_marcas:
        marcas_opts_cmp = sorted(
        df["Marca"].dropna().unique().tolist(),
        key=lambda s: str(s).casefold()
        )
        sugestao_cmp = (
            df.groupby("Marca")["Investimento"].sum()
              .sort_values(ascending=False).head(5).index.tolist()
        )
        sugestao_cmp = [m for m in sugestao_cmp if m in marcas_opts_cmp]
        default_cmp = st.session_state.marcas_selecao_principal if st.session_state.marcas_selecao_principal else sugestao_cmp
        marcas_sel_cmp = st.multiselect(
            "Marcas (mesmas nos dois gráficos)",
            options=marcas_opts_cmp,
            default=default_cmp,
            key="marcas_sel_tab3",
            help="As mesmas marcas serão comparadas nos dois períodos."
        )

    with c_esq:
        sel_dt_ini_esq, sel_dt_fim_esq = st.slider(
            "Período (Gráfico Esquerdo)",
            min_value=dt_min, max_value=dt_max,
            value=(dt_min, dt_max), format="MM/YYYY", key="periodo_esq"
        )

    with c_dir:
        sel_dt_ini_dir, sel_dt_fim_dir = st.slider(
            "Período (Gráfico Direito)",
            min_value=dt_min, max_value=dt_max,
            value=(dt_min, dt_max), format="MM/YYYY", key="periodo_dir"
        )

    st.markdown("---")

    col1, col2 = st.columns(2)

    if not marcas_sel_cmp:
        st.info("Selecione ao menos uma marca para comparar os períodos.")
    else:
        df_cmp = df[df["Marca"].isin(marcas_sel_cmp)].copy()

        # -------- Gráfico Esquerdo --------
        with col1:
            per_esq = coerce_period_to_ts(df_cmp["Período"])
            df_esq = df_cmp[(per_esq >= sel_dt_ini_esq) & (per_esq <= sel_dt_fim_esq)].copy()

            fig_esq, _ = torre_marcas_plotly(
                df_esq, marcas_sel_cmp, sel_dt_ini_esq, sel_dt_fim_esq,
                st.session_state.PALETA_MARCA,
                lado_callout="esquerdo",
                widget_prefix="cmpL",
                show_palette_controls=False,

                # --------------- [AJUSTE ESQUERDA] ---------------
                bar_width=0.55,              # engrossa/afina a barra
                xdomain_esq=(0.26, 0.58),    # conter área da barra (afasta da legenda)
                legend_x_esq=0.50,           # proximidade da legenda (menor = mais à esquerda)
                legend_anchor_esq="left"
                # --------------------------------------------------
            )
            st.plotly_chart(fig_esq, use_container_width=True)

        # -------- Gráfico Direito --------
        with col2:
            per_dir = coerce_period_to_ts(df_cmp["Período"])
            df_dir = df_cmp[(per_dir >= sel_dt_ini_dir) & (per_dir <= sel_dt_fim_dir)].copy()

            fig_dir, _ = torre_marcas_plotly(
                df_dir, marcas_sel_cmp, sel_dt_ini_dir, sel_dt_fim_dir,
                st.session_state.PALETA_MARCA,
                lado_callout="direito",
                widget_prefix="cmpR",
                show_palette_controls=False,

                # --------------- [AJUSTE DIREITA] ----------------
                bar_width=0.55,              # engrossa/afina a barra
                xdomain_dir=(0.42, 0.70),    # conter área da barra (afasta da legenda)
                legend_x_dir=0.45,           # proximidade da legenda (maior = mais à direita)
                legend_anchor_dir="right"
                # --------------------------------------------------
            )
            st.plotly_chart(fig_dir, use_container_width=True)


# ==============================================================
#   ABA 4: Séries Temporais (linhas por marca + tabela emendada)
# ==============================================================
with tab4:
    st.subheader("Séries Temporais — Investimento por Marca")

    # Período baseado na coluna 'Período'
    per_all = coerce_period_to_ts(df["Período"])
    dt_min_ts = per_all.min().to_pydatetime()
    dt_max_ts = per_all.max().to_pydatetime()

    sel_dt_ini_ts, sel_dt_fim_ts = st.slider(
        "Período (Série Temporal)",
        min_value=dt_min_ts,
        max_value=dt_max_ts,
        value=(dt_min_ts, dt_max_ts),
        format="MM/YYYY",
        key="periodo_ts"
    )

    mask_ts = (per_all >= sel_dt_ini_ts) & (per_all <= sel_dt_fim_ts)
    df_ts = df.loc[mask_ts].copy()

    # Seleção de marcas
    marcas_opts_ts = sorted(df_ts["Marca"].dropna().unique().tolist())
    sugestao_ts = (
        df_ts.groupby("Marca")["Investimento"].sum()
             .sort_values(ascending=False).head(5).index.tolist()
    )
    sugestao_ts = [m for m in sugestao_ts if m in marcas_opts_ts]
    
    default_cmp = sanitize_default(st.session_state.get("marcas_selecao_principal") or sugestao_ts,
                               marcas_opts_ts, fallback_list=sugestao_ts)
    
    marcas_sel_ts = st.multiselect(
        "Marcas (linhas)",
        options=marcas_opts_ts,
        default=default_cmp,
        help="Cada marca selecionada gera uma linha no gráfico.",
        key="marcas_sel_ts"
    )

    if not marcas_sel_ts:
        st.info("Selecione pelo menos uma marca para exibir a série temporal.")
        st.stop()

    # Agregação mensal respeitando sua coluna 'Período'
    df_ts_sel = df_ts[df_ts["Marca"].isin(marcas_sel_ts)].copy()
    df_ts_sel["Per_ts"] = coerce_period_to_ts(df_ts_sel["Período"]).dt.to_period("M").dt.to_timestamp()

    timeline = df_ts_sel["Per_ts"].dropna().sort_values().unique()
    pivot = (
        df_ts_sel.groupby(["Marca", "Per_ts"], as_index=False)["Investimento"].sum()
                .pivot(index="Marca", columns="Per_ts", values="Investimento")
                .reindex(columns=timeline, fill_value=0.0)
                .reindex(index=marcas_sel_ts)
    )

    # Gráfico de linhas
    cores = build_palette(marcas_sel_ts, st.session_state.PALETA_MARCA)
    fig_ts = go.Figure()
    for m in marcas_sel_ts:
        y_vals = pivot.loc[m].values if m in pivot.index else np.zeros(len(timeline))
        fig_ts.add_trace(go.Scatter(
            x=timeline, y=y_vals, mode="lines+markers",
            name=str(m),
            line=dict(color=cores.get(m, "#999999"), width=3),
            hovertemplate=f"{m}<br>%{{x|%b/%Y}}<br>Investimento: %{{y}}<extra></extra>",
        ))

    y_max = float(np.nanmax(pivot.values)) if pivot.size else 0.0
    yticks, ylabels = make_y_ticks(y_max, n=6)

    fig_ts.update_layout(
        height=520,
        margin=dict(l=60, r=40, t=60, b=40),
        xaxis=dict(
            title=None, tickformat="%b/%Y",
            showgrid=False, showline=False, zeroline=False
        ),
        yaxis=dict(
            title=None,
            tickmode="array", tickvals=yticks, ticktext=ylabels,
            showgrid=True, gridcolor="rgba(0,0,0,0.08)", zeroline=False
        ),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0.0),
        plot_bgcolor="white", paper_bgcolor="white",
        title=dict(text=" ", x=0.5)
    )
    st.plotly_chart(fig_ts, use_container_width=True)

    # Tabela emendada ao eixo X (valores abreviados)
    MES = ["JAN","FEV","MAR","ABR","MAI","JUN","JUL","AGO","SET","OUT","NOV","DEZ"]
    def _fmt_period_label(ts_val) -> str:
        dt = pd.to_datetime(ts_val)
        return f"{MES[dt.month-1]}/{str(dt.year)[-2:]}"
    col_labels = [_fmt_period_label(t) for t in timeline]

    tabela_fmt = pivot.copy()
    for c in tabela_fmt.columns:
        tabela_fmt[c] = tabela_fmt[c].apply(fmt_mmk)

    tabela_fmt.columns = col_labels
    tabela_fmt.reset_index(inplace=True)
    tabela_fmt.rename(columns={"Marca": "Marca"}, inplace=True)

    st.markdown("**Tabela (valores abreviados):**")
    st.dataframe(tabela_fmt, use_container_width=True)

# ==============================================================
#   ABA 5: INVESTIMENTO POR PRAÇA (barras 100% empilhadas)
# ==============================================================
with tab5:
    st.subheader("Investimento por Praça")

    # Período da aba
    sel_dt_ini_p, sel_dt_fim_p = st.slider(
        "Período (Praças)",
        min_value=dt_min, max_value=dt_max,
        value=(dt_min, dt_max), format="MM/YYYY",
        key="periodo_pracas"
    )

    # Filtra período para opções de marcas
    per_ts_p = coerce_period_to_ts(df["Período"])
    df_p = df[(per_ts_p >= sel_dt_ini_p) & (per_ts_p <= sel_dt_fim_p)].copy()

    # Seleção de marcas
    marcas_opts_p = sorted(df_p["Marca"].dropna().unique().tolist())
    sugestao_p = (
        df_p.groupby("Marca")["Investimento"].sum()
            .sort_values(ascending=False).head(6).index.tolist()
    )
    sugestao_p = [m for m in sugestao_p if m in marcas_opts_p]
    
    default_cmp = sanitize_default(st.session_state.get("marcas_selecao_principal") or sugestao_p,
                               marcas_opts_p, fallback_list=sugestao_p)
    
    marcas_sel_p = st.multiselect(
        "Marcas",
        options=marcas_opts_p,
        default=default_cmp,
        help="Cada barra é uma marca; as cores representam as praças.",
        key="marcas_sel_pracas"
    )

    if not marcas_sel_p:
        st.info("Selecione ao menos uma marca para exibir o gráfico por praça.")
    else:
        fig_p, df_outros_detalhe = grafico_investimento_por_praca( # <--- AQUI: Captura os dois retornos
            df_p, marcas_sel_p, sel_dt_ini_p, sel_dt_fim_p,
            widget_prefix="prc",
            show_palette_controls=True,
            bar_width=0.55   # [AJUSTE] espessura das barras
        )
        st.plotly_chart(fig_p, use_container_width=True)

        # --- [INÍCIO DO AJUSTE] Exibe a tabela de detalhe das praças "OUTROS" ---
        if not df_outros_detalhe.empty:
            st.subheader("Detalhe das Praças Agrupadas em \"OUTROS\"")
            st.dataframe(df_outros_detalhe, use_container_width=True)
        # --- [FIM DO AJUSTE] Exibe a tabela de detalhe das praças "OUTROS" ---


# ==============================================================
#   ABA 6: INVESTIMENTO POR MEIO (barras 100% empilhadas)
# ==============================================================
with tab6:
    st.subheader("Investimento por Meio")

    # Período da aba
    sel_dt_ini_m, sel_dt_fim_m = st.slider(
        "Período (Meios)",
        min_value=dt_min, max_value=dt_max,
        value=(dt_min, dt_max), format="MM/YYYY",
        key="periodo_meios"
    )

    # Filtra período para opções de marcas
    per_ts_m = coerce_period_to_ts(df["Período"])
    df_m = df[(per_ts_m >= sel_dt_ini_m) & (per_ts_m <= sel_dt_fim_m)].copy()

    # Seleção de marcas
    marcas_opts_m = sorted(df_m["Marca"].dropna().unique().tolist())
    sugestao_m = (
        df_m.groupby("Marca")["Investimento"].sum()
            .sort_values(ascending=False).head(6).index.tolist()
    )
    sugestao_m = [ma for ma in sugestao_m if ma in marcas_opts_m]
    
    default_cmp = sanitize_default(st.session_state.get("marcas_selecao_principal") or sugestao_m,
                               marcas_opts_m, fallback_list=sugestao_m)
    
    marcas_sel_m = st.multiselect(
        "Marcas",
        options=marcas_opts_m,
        default=default_cmp,
        help="Cada barra é uma marca; as cores representam os Meios.",
        key="marcas_sel_meios"
    )

    if not marcas_sel_m:
        st.info("Selecione ao menos uma marca para exibir o gráfico por Meio.")
    else:
        fig_m, df_meios_detalhe = grafico_investimento_por_meio(
            df_m, marcas_sel_m, sel_dt_ini_m, sel_dt_fim_m,
            widget_prefix="meio",
            show_palette_controls=True,
            bar_width=0.55   # [AJUSTE] espessura das barras
        )
        st.plotly_chart(fig_m, use_container_width=True)
        # --- [NOVO] Exibe a tabela de detalhe dos Meios ---
    if not df_meios_detalhe.empty:
        st.subheader("Investimento por Meio (Valores Absolutos)")
        # Formatação para exibição
        df_meios_display = df_meios_detalhe.copy()
        df_meios_display = df_meios_display.reset_index()
        df_meios_display.rename(columns={"Marca": "Marca"}, inplace=True)
        for col in df_meios_display.columns:
            if col != "Marca":
                # Garante que a coluna não é a coluna de índice antes de tentar formatar
                if col in df_meios_detalhe.columns:
                    # O formato de formatação de moeda deve ser o mesmo usado em outras partes do seu código
                    df_meios_display[col] = df_meios_display[col].apply(lambda x: f"R$ {x:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        st.dataframe(df_meios_display, use_container_width=True)
    # --- [FIM NOVO] Exibe a tabela de detalhe dos Meios ---

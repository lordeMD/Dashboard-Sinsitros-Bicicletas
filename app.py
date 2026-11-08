# -*- coding: utf-8 -*-
"""app.py: Dashboard Interativo de Segurança Viária para Sinistros com Bicicletas.

Cidades atendidas: Santos, São Vicente e Praia Grande (2020-2025).
Pipeline: ETL -> Grafo & Mapa Espacial OSM -> Modelos Estatísticos -> Dashboard Streamlit.
"""

import sys
from pathlib import Path

# Garante que a raiz do projeto esteja no sys.path
RAIZ = Path(__file__).resolve().parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

# =====================================================
# CONFIGURAÇÃO DA PÁGINA
# =====================================================
st.set_page_config(
    page_title="Dashboard de Segurança Viária - Bicicletas",
    page_icon="🚲",
    layout="wide",
    initial_sidebar_state="expanded",
)

PASTA_ESTATISTICAS = RAIZ / "resultados_estatisticos"
PASTA_MAPA = RAIZ / "resultados_mapa_espacial"
ARQUIVO_SINISTROS = RAIZ / "dados" / "processados" / "sinistros_bicicleta.csv"


# =====================================================
# CARREGAMENTO DOS DADOS (COM CACHE)
# =====================================================
@st.cache_data
def carregar_dados():
    kpis = pd.read_csv(PASTA_ESTATISTICAS / "dashboard_kpis.csv", encoding="utf-8-sig")
    modelos = pd.read_csv(PASTA_ESTATISTICAS / "comparacao_modelos.csv", encoding="utf-8-sig")
    irr = pd.read_csv(PASTA_ESTATISTICAS / "irr_municipios.csv", encoding="utf-8-sig")
    ranking = pd.read_csv(PASTA_ESTATISTICAS / "ranking_segmentos.csv", encoding="utf-8-sig")

    df_sinistros = pd.DataFrame()
    if ARQUIVO_SINISTROS.exists():
        df_sinistros = pd.read_csv(ARQUIVO_SINISTROS, encoding="utf-8-sig", low_memory=False)

    return kpis, modelos, irr, ranking, df_sinistros


try:
    kpis, modelos, irr, ranking, df_sinistros = carregar_dados()
except Exception as e:
    st.error(
        f"Erro ao carregar os dados estatísticos: {e}\n\n"
        "Certifique-se de executar os scripts 01_etl.py, 02_mapa_espacial.py e 03_analise_estatistica.py."
    )
    st.stop()


# =====================================================
# BARRA LATERAL (FILTROS)
# =====================================================
st.sidebar.image(
    "https://img.icons8.com/clouds/200/bicycle.png",
    width=110,
)
st.sidebar.title("🚲 Filtros de Navegação")

lista_municipios = sorted(kpis["municipio"].unique().tolist())
opcoes_filtro = ["Todos os Municípios (Comparativo)"] + lista_municipios

municipio_selecionado = st.sidebar.selectbox(
    "Selecione o Município:",
    opcoes_filtro,
    index=1 if len(opcoes_filtro) > 1 else 0,
)

visao_comparativa = (municipio_selecionado == "Todos os Municípios (Comparativo)")

st.sidebar.divider()
st.sidebar.markdown(
    """
    **Sobre o Projeto:**
    - Estudo de sinistros envolvendo **bicicletas** (2020 a 2025).
    - Cidades: **Santos, São Vicente e Praia Grande**.
    - Rede viária extraída do **OpenStreetMap**.
    - Modelagem com modelos de contagem (**Poisson e Binomial Negativa**).
    """
)


# =====================================================
# CABEÇALHO DO DASHBOARD
# =====================================================
titulo_header = (
    "🚲 Painel Geral Comparativo: Santos, São Vicente e Praia Grande"
    if visao_comparativa
    else f"🚲 Painel de Segurança Viária Ciclística — {municipio_selecionado}"
)
st.title(titulo_header)
st.caption("Pipeline Integrado: ETL → Grafo Viário & Centralidades → Modelos Estatísticos → Visualização")


# =====================================================
# FILTRAGEM DOS DADOS SEGUNDO O MUNICÍPIO
# =====================================================
if visao_comparativa:
    kpi_df = kpis.copy()
    modelo_df = modelos.copy()
    irr_df = irr.copy()
    ranking_df = ranking.copy()
    sinistros_sel = df_sinistros.copy()
else:
    kpi_df = kpis[kpis["municipio"] == municipio_selecionado]
    modelo_df = modelos[modelos["municipio"] == municipio_selecionado]
    irr_df = irr[irr["municipio"] == municipio_selecionado]
    ranking_df = ranking[ranking["municipio"] == municipio_selecionado]
    sinistros_sel = df_sinistros[df_sinistros["municipio"] == municipio_selecionado] if not df_sinistros.empty else pd.DataFrame()


# =====================================================
# SEÇÃO 1: KPIS PRINCIPAIS
# =====================================================
st.subheader("Indicadores Gerais da Rede e dos Sinistros")

col1, col2, col3, col4, col5 = st.columns(5)

total_segmentos = int(kpi_df["total_segmentos"].sum())
total_sinistros = int(kpi_df["total_sinistros"].sum())
media_sinistros = float(kpi_df["media_sinistros"].mean())
perc_zero_media = float(kpi_df["perc_zero"].mean())

fatais_total = int(sinistros_sel["vitimas_fatais"].sum()) if "vitimas_fatais" in sinistros_sel.columns else 0

col1.metric("Segmentos Viários", f"{total_segmentos:,}".replace(",", "."))
col2.metric("Sinistros com Bike", f"{total_sinistros:,}".replace(",", "."))
col3.metric("Média / Segmento", f"{media_sinistros:.3f}")
col4.metric("Segmentos sem Sinistro", f"{perc_zero_media:.1f}%")
col5.metric("Vítimas Fatais", f"{fatais_total:,}".replace(",", "."))


# =====================================================
# ABAS DO DASHBOARD
# =====================================================
tab1, tab2, tab3, tab4 = st.tabs([
    "📊 Visão Geral & Estatísticas",
    "🗺️ Mapa Espacial Interativo",
    "📈 Modelagem Estatística & IRR",
    "🚨 Segmentos Críticos & Priorização",
])


# =====================================================
# ABA 1: VISÃO GERAL & PERFIL DOS SINISTROS
# =====================================================
with tab1:
    if visao_comparativa:
        st.markdown("### Comparativo Geral entre os Municípios")
        col_c1, col_c2 = st.columns(2)

        with col_c1:
            fig_comp_sin = px.bar(
                kpi_df,
                x="municipio",
                y="total_sinistros",
                color="municipio",
                text="total_sinistros",
                title="Total de Sinistros Associados à Rede por Município",
                labels={"total_sinistros": "Sinistros", "municipio": "Município"},
                color_discrete_sequence=px.colors.qualitative.Set2,
            )
            fig_comp_sin.update_traces(textposition="outside")
            fig_comp_sin.update_layout(showlegend=False)
            st.plotly_chart(fig_comp_sin, use_container_width=True)

        with col_c2:
            fig_comp_seg = px.bar(
                kpi_df,
                x="municipio",
                y="total_segmentos",
                color="municipio",
                text="total_segmentos",
                title="Extensão da Malha: Total de Segmentos Viários do OSM",
                labels={"total_segmentos": "Segmentos", "municipio": "Município"},
                color_discrete_sequence=px.colors.qualitative.Pastel,
            )
            fig_comp_seg.update_traces(textposition="outside")
            fig_comp_seg.update_layout(showlegend=False)
            st.plotly_chart(fig_comp_seg, use_container_width=True)

    if not sinistros_sel.empty:
        st.markdown("### Perfil e Distribuição dos Sinistros")
        c_a, c_b = st.columns(2)

        with c_a:
            # Distribuição temporal por ano
            if "ano" in sinistros_sel.columns:
                por_ano = sinistros_sel.groupby("ano").size().reset_index(name="quantidade")
                fig_ano = px.line(
                    por_ano,
                    x="ano",
                    y="quantidade",
                    markers=True,
                    title="Evolução Anual dos Sinistros com Bicicleta (2020 a 2025)",
                    labels={"ano": "Ano", "quantidade": "Nº de Sinistros"},
                )
                fig_ano.update_traces(line_color="#1f77b4", line_width=3)
                st.plotly_chart(fig_ano, use_container_width=True)

        with c_b:
            # Gravidade dos sinistros
            if "classe_gravidade" in sinistros_sel.columns:
                grav = sinistros_sel["classe_gravidade"].value_counts().reset_index()
                grav.columns = ["gravidade", "total"]
                fig_grav = px.pie(
                    grav,
                    names="gravidade",
                    values="total",
                    title="Distribuição por Classe de Gravidade",
                    hole=0.4,
                    color="gravidade",
                    color_discrete_map={
                        "Leve": "#2ca02c",
                        "Grave": "#ff7f0e",
                        "Fatal": "#d62728",
                        "Sem vítimas informadas": "#1f77b4",
                    },
                )
                st.plotly_chart(fig_grav, use_container_width=True)

        c_c, c_d = st.columns(2)
        with c_c:
            if "turno" in sinistros_sel.columns:
                turno_df = sinistros_sel["turno"].dropna().value_counts().reset_index()
                turno_df.columns = ["turno", "total"]
                fig_turno = px.bar(
                    turno_df,
                    x="turno",
                    y="total",
                    color="turno",
                    text="total",
                    title="Sinistros por Turno do Dia",
                    labels={"turno": "Turno", "total": "Sinistros"},
                )
                fig_turno.update_traces(textposition="outside")
                fig_turno.update_layout(showlegend=False)
                st.plotly_chart(fig_turno, use_container_width=True)

        with c_d:
            if "dia_da_semana" in sinistros_sel.columns:
                ordem_dias = [
                    "Segunda-feira", "Terça-feira", "Quarta-feira",
                    "Quinta-feira", "Sexta-feira", "Sábado", "Domingo"
                ]
                dias_df = sinistros_sel["dia_da_semana"].value_counts().reindex(ordem_dias).dropna().reset_index()
                dias_df.columns = ["dia", "total"]
                fig_dia = px.bar(
                    dias_df,
                    x="dia",
                    y="total",
                    text="total",
                    title="Sinistros por Dia da Semana",
                    labels={"dia": "Dia da Semana", "total": "Sinistros"},
                    color_discrete_sequence=["#e377c2"],
                )
                fig_dia.update_traces(textposition="outside")
                st.plotly_chart(fig_dia, use_container_width=True)


# =====================================================
# ABA 2: MAPA ESPACIAL INTERATIVO
# =====================================================
with tab2:
    st.markdown("### Mapa da Rede Viária e Localização dos Sinistros")
    st.info(
        "O mapa abaixo representa a rede viária ciclística obtida do OpenStreetMap. "
        "As cores das linhas indicam o número de sinistros associados (cinza = 0, azul = 1-2, laranja = 3-5, vermelho > 5). "
        "Os pontos circulares representam a gravidade de cada sinistro registrado."
    )

    mapa_cidade = municipio_selecionado if not visao_comparativa else "Santos"
    mapa_slug = {
        "Santos": "santos_30m_mapa.html",
        "São Vicente": "sao_vicente_30m_mapa.html",
        "Praia Grande": "praia_grande_30m_mapa.html",
    }.get(mapa_cidade, "santos_30m_mapa.html")

    if visao_comparativa:
        mapa_cidade = st.radio(
            "Visualizar mapa de qual cidade:",
            ["Santos", "São Vicente", "Praia Grande"],
            horizontal=True,
        )
        mapa_slug = {
            "Santos": "santos_30m_mapa.html",
            "São Vicente": "sao_vicente_30m_mapa.html",
            "Praia Grande": "praia_grande_30m_mapa.html",
        }[mapa_cidade]

    caminho_mapa = PASTA_MAPA / mapa_slug

    if caminho_mapa.exists():
        with open(caminho_mapa, "r", encoding="utf-8") as f:
            html_content = f.read()
        components.html(html_content, height=650, scrolling=True)
    else:
        st.warning(f"Arquivo de mapa interativo não encontrado em: {caminho_mapa}")


# =====================================================
# ABA 3: MODELAGEM ESTATÍSTICA & IRR
# =====================================================
with tab3:
    st.markdown("### Diagnóstico e Seleção do Modelo Estatístico")
    st.markdown(
        """
        Para modelar a contagem de sinistros viários por segmento, foram comparados dois modelos GLM:
        - **Modelo de Poisson**: assume igualdade entre média e variância.
        - **Modelo Binomial Negativa (NB)**: incorpora parâmetro de dispersão $\\alpha$, corrigindo a sobredispersão comum em dados viários.
        - **Offset**: $\\ln(\\text{comprimento em km})$, controlando pela extensão de cada trecho.
        """
    )

    for _, mod in modelo_df.iterrows():
        mun = mod["municipio"]
        st.markdown(f"#### Resultados da Modelagem — **{mun}**")
        ca, cb, cc, cd = st.columns(4)
        ca.metric("Modelo Escolhido", mod["modelo_escolhido"])
        cb.metric("AIC Poisson", f"{mod['aic_poisson']:.1f}")
        cc.metric("AIC Binomial Negativa", f"{mod['aic_nb']:.1f}", delta=f"{mod['aic_nb'] - mod['aic_poisson']:.1f} (melhoria)")
        cd.metric("Dispersão de Pearson", f"{mod['dispersao']:.2f}")
        st.divider()

    st.markdown("### Razão de Taxa de Incidência (IRR - Incidence Rate Ratio)")
    st.markdown(
        """
        O **IRR** representa o efeito multiplicativo de cada variável sobre a taxa esperada de sinistros:
        - **IRR > 1.0**: Aumento na taxa de sinistros (fator de risco).
        - **IRR < 1.0**: Redução na taxa de sinistros (fator de proteção).
        - **Linha tracejada em 1.0**: Referência neutra (sem efeito).

        - **Closeness (proximidade)**: Mede o quão perto um nó está de todos os outros da rede, ou seja, o inverso da soma das menores distâncias dele até todos os demais; quanto maior, mais rápido ele alcança a rede toda.
        - **Betweenness (intermediação)**: Mede quantos dos caminhos mais curtos entre pares de outros nós passam por ele, indicando o quanto ele funciona como “ponte” ou ponto de passagem na rede.        
        """
    )

    if not irr_df.empty:
        # Gráfico IRR com intervalo de confiança
        fig_irr = go.Figure()

        for mun in irr_df["municipio"].unique():
            sub = irr_df[irr_df["municipio"] == mun]
            fig_irr.add_trace(go.Bar(
                name=mun,
                x=sub["variavel"],
                y=sub["irr"],
                error_y=dict(
                    type="data",
                    symmetric=False,
                    array=sub["ic_sup"] - sub["irr"],
                    arrayminus=sub["irr"] - sub["ic_inf"],
                ),
                text=[f"IRR: {v:.2f}" for v in sub["irr"]],
                textposition="outside",
            ))

        fig_irr.add_hline(
            y=1.0,
            line_dash="dash",
            line_color="red",
            annotation_text="Referência (IRR = 1.0)",
            annotation_position="bottom right",
        )

        fig_irr.update_layout(
            barmode="group",
            title="Impacto das Variáveis na Taxa de Sinistros (com Intervalo de Confiança 95%)",
            yaxis_title="Razão de Taxa de Incidência (IRR)",
            xaxis_title="Variável Explicativa",
            hovermode="x unified",
        )
        st.plotly_chart(fig_irr, use_container_width=True)

        with st.expander("🔍 Ver Tabela Completa de Coeficientes e P-Valores"):
            cols_exibicao = ["municipio", "variavel", "coeficiente", "irr", "ic_inf", "ic_sup", "p_valor"]
            tabela_irr = irr_df[cols_exibicao].copy()
            tabela_irr["Significativo (p < 0.05)"] = tabela_irr["p_valor"] < 0.05
            tabela_irr = tabela_irr.round({
                "coeficiente": 3,
                "irr": 3,
                "ic_inf": 3,
                "ic_sup": 3,
                "p_valor": 5,
            })
            st.dataframe(tabela_irr, use_container_width=True)


# =====================================================
# ABA 4: RANKING DE SEGMENTOS CRÍTICOS
# =====================================================
with tab4:
    st.markdown("### Segmentos Viários Mais Críticos para Intervenção")
    st.markdown(
        """
        O índice de criticidade é calculado a partir do volume de sinistros associados ao trecho ponderado
        pela centralidade de intermediação (*betweenness centrality*): $\\text{Criticidade} = \\text{Sinistros} \\times (\\text{Betweenness} \\times 100 + 1)$.
        Isso prioriza vias que acumulam sinistros e possuem papel estruturante no fluxo da malha viária.
        """
    )

    col_s1, col_s2 = st.columns([1, 2])
    with col_s1:
        top_n = st.slider(
            "Quantidade de Segmentos Críticos a Exibir:",
            min_value=5,
            max_value=50,
            value=15,
            step=5,
        )

    top_ranking = (
        ranking_df.sort_values("criticidade", ascending=False)
        .head(top_n)
        .copy()
    )

    # Gráfico de barras dos segmentos críticos
    fig_top = px.bar(
        top_ranking,
        x="criticidade",
        y="segmento",
        orientation="h",
        color="sinistros",
        title=f"Top {top_n} Trechos Críticos (Ordenados por Criticidade)",
        labels={"criticidade": "Índice de Criticidade", "segmento": "Trecho Viário", "sinistros": "Sinistros"},
        color_continuous_scale="Reds",
    )
    fig_top.update_layout(yaxis=dict(autorange="reversed"))
    st.plotly_chart(fig_top, use_container_width=True)

    st.markdown("#### Tabela Detalhada dos Segmentos Críticos")
    st.dataframe(
        top_ranking.round({"betweenness": 5, "criticidade": 2}),
        use_container_width=True,
    )

    # Botão de exportação
    csv_bytes = ranking_df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        label=f"📥 Baixar Ranking de Segmentos ({municipio_selecionado}) em CSV",
        data=csv_bytes,
        file_name=f"ranking_segmentos_{municipio_selecionado.lower().replace(' ', '_')}.csv",
        mime="text/csv",
    )

st.divider()
st.caption("Desenvolvido para análise de segurança viária ativa | Santos, São Vicente e Praia Grande")
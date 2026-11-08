# -*- coding: utf-8 -*-
"""03_analise_estatistica.py

Análise estatística dos segmentos viários com sinistros envolvendo bicicletas.
Ajusta modelos de contagem (Poisson e Binomial Negativa) com offset de comprimento,
avalia sobredispersão, calcula Razões de Taxa de Incidência (IRR) e gera ranking de criticidade.

Entradas:
    dataset_segmentos_santos_30M.csv
    dataset_segmentos_sao_vicente_30M.csv
    dataset_segmentos_praia_grande_30M.csv

Saídas (em resultados_estatisticos/):
    dashboard_kpis.csv
    comparacao_modelos.csv
    irr_municipios.csv
    ranking_segmentos.csv
"""

import sys
import warnings
from pathlib import Path

# Garante que a raiz do projeto esteja no sys.path
RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar

import statsmodels.api as sm
import statsmodels.formula.api as smf
from statsmodels.stats.outliers_influence import variance_inflation_factor
from statsmodels.tools.sm_exceptions import ConvergenceWarning, HessianInversionWarning

from config import PASTA_ESTATISTICAS, PASTA_MAPA

# Busca arquivos tanto na raiz quanto na pasta do mapa espacial
ARQUIVOS = {
    "Santos": [
        RAIZ / "dataset_segmentos_santos_30M.csv",
        PASTA_MAPA / "dataset_segmentos_santos_30M.csv",
    ],
    "São Vicente": [
        RAIZ / "dataset_segmentos_sao_vicente_30M.csv",
        PASTA_MAPA / "dataset_segmentos_sao_vicente_30M.csv",
    ],
    "Praia Grande": [
        RAIZ / "dataset_segmentos_praia_grande_30M.csv",
        PASTA_MAPA / "dataset_segmentos_praia_grande_30M.csv",
    ],
}


def preparar_dados(df):
    df = df.copy()

    df = df.rename(
        columns={
            "Segmento": "segmento",
            "Comprimento (m)": "comprimento",
            "Betweenness": "betweenness",
            "Closeness": "closeness",
            "Velocidade da via (km/h)": "velocidade",
            "Ciclovia": "ciclovia",
            "Quantidade de Sinistros": "sinistros",
        }
    )

    colunas_obrigatorias = ["comprimento", "betweenness", "closeness", "velocidade", "sinistros"]
    for c in colunas_obrigatorias:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    # Valores padrão para evitar perda desnecessária de linhas
    df["velocidade"] = df["velocidade"].fillna(30.0)
    df["betweenness"] = df["betweenness"].fillna(0.0)
    df["closeness"] = df["closeness"].fillna(0.0)
    df["sinistros"] = df["sinistros"].fillna(0).round().astype(int)

    df = df.dropna(subset=["comprimento"]).copy()
    df = df[df["comprimento"] > 0].copy()

    if "ciclovia" in df.columns:
        df["ciclovia"] = (
            df["ciclovia"]
            .astype(str)
            .str.strip()
            .str.lower()
            .isin(["sim", "s", "1", "true", "yes"])
            .astype(int)
        )
    else:
        df["ciclovia"] = 0

    df["log_comprimento"] = np.log(df["comprimento"] / 1000.0)
    df["velocidade_10"] = df["velocidade"] / 10.0

    for col in ["betweenness", "closeness"]:
        media = df[col].mean()
        desvio = df[col].std()
        if desvio > 0:
            df[f"{col}_z"] = (df[col] - media) / desvio
        else:
            df[f"{col}_z"] = 0.0

    return df


def calcular_vif(df):
    vars_modelo = ["betweenness_z", "closeness_z", "velocidade_10", "ciclovia"]
    # Verifica se há variância suficiente
    vars_validas = [v for v in vars_modelo if df[v].std() > 1e-8]
    if len(vars_validas) < 2:
        return pd.DataFrame({"variavel": vars_modelo, "vif": [1.0] * len(vars_modelo)})

    x = sm.add_constant(df[vars_validas])
    vifs = []
    for i in range(1, x.shape[1]):
        try:
            v = variance_inflation_factor(x.values, i)
        except Exception:
            v = np.nan
        vifs.append(v)

    return pd.DataFrame({"variavel": vars_validas, "vif": vifs})


def ajustar_poisson(df):
    formula = "sinistros ~ betweenness_z + closeness_z + velocidade_10 + ciclovia"
    modelo = smf.glm(
        formula=formula,
        data=df,
        family=sm.families.Poisson(),
        offset=df["log_comprimento"]
    ).fit()

    robusto = smf.glm(
        formula=formula,
        data=df,
        family=sm.families.Poisson(),
        offset=df["log_comprimento"]
    ).fit(cov_type="HC1")

    return modelo, robusto


def ajustar_nb(df):
    formula = "sinistros ~ betweenness_z + closeness_z + velocidade_10 + ciclovia"

    def ajuste_glm(alpha):
        fam = sm.families.NegativeBinomial(alpha=alpha)
        return smf.glm(
            formula,
            data=df,
            family=fam,
            offset=df["log_comprimento"]
        ).fit()

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", (RuntimeWarning, ConvergenceWarning, HessianInversionWarning))
        try:
            otimo = minimize_scalar(
                lambda x: -ajuste_glm(np.exp(x)).llf,
                bounds=(-8, 5),
                method="bounded"
            )
            alpha = float(np.exp(otimo.x))
            nb = ajuste_glm(alpha)
        except Exception:
            alpha = 1.0
            nb = ajuste_glm(alpha)

    return nb, alpha


def gerar_irr(resultado, municipio):
    params = resultado.params.drop("Intercept", errors="ignore")
    ci = resultado.conf_int()

    nomes_amigaveis = {
        "betweenness_z": "Betweenness (Intermediação Z)",
        "closeness_z": "Closeness (Proximidade Z)",
        "velocidade_10": "Velocidade da Via (+10 km/h)",
        "ciclovia": "Presença de Ciclovia",
    }

    linhas = []
    for var in params.index:
        coef = params[var]
        ic0 = ci.loc[var, 0] if var in ci.index else coef
        ic1 = ci.loc[var, 1] if var in ci.index else coef
        pval = resultado.pvalues[var] if var in resultado.pvalues else 1.0

        linhas.append({
            "municipio": municipio,
            "variavel": nomes_amigaveis.get(var, var),
            "variavel_tecnica": var,
            "coeficiente": float(coef),
            "irr": float(np.exp(coef)),
            "ic_inf": float(np.exp(ic0)),
            "ic_sup": float(np.exp(ic1)),
            "p_valor": float(pval),
        })

    return pd.DataFrame(linhas)


def encontrar_arquivo(lista_candidatos):
    for c in lista_candidatos:
        if c.exists():
            return c
    return None


def main():
    print("=" * 60)
    print("ETAPA 3: ANÁLISE ESTATÍSTICA E MODELAGEM DE SINISTROS")
    print("=" * 60)

    comparacao = []
    kpis = []
    irr_total = []
    ranking_total = []

    for municipio, candidatos in ARQUIVOS.items():
        caminho = encontrar_arquivo(candidatos)
        if caminho is None:
            print(f"AVISO: Arquivo para {municipio} não encontrado em nenhum dos locais esperados.")
            continue

        print(f"\nAnalisando {municipio} a partir de: {caminho.name}")
        df = pd.read_csv(caminho, encoding="utf-8-sig")
        df = preparar_dados(df)

        print(f"  Segmentos viários válidos: {len(df)}")
        print(f"  Total de sinistros associados: {df['sinistros'].sum()}")

        poisson, poisson_rob = ajustar_poisson(df)
        nb, alpha = ajustar_nb(df)

        dispersao = float(poisson.pearson_chi2 / poisson.df_resid)
        melhor = "Binomial Negativa" if nb.aic < poisson.aic else "Poisson"
        modelo_final = nb if melhor == "Binomial Negativa" else poisson_rob

        print(f"  AIC Poisson: {poisson.aic:.1f} | AIC Binomial Negativa: {nb.aic:.1f}")
        print(f"  Dispersão de Pearson: {dispersao:.2f} | Alpha NB: {alpha:.3f}")
        print(f"  Modelo Selecionado: {melhor}")

        comparacao.append({
            "municipio": municipio,
            "aic_poisson": float(poisson.aic),
            "aic_nb": float(nb.aic),
            "bic_poisson": float(poisson.bic_llf),
            "bic_nb": float(nb.bic_llf),
            "alpha": float(alpha),
            "dispersao": float(dispersao),
            "modelo_escolhido": melhor,
        })

        kpis.append({
            "municipio": municipio,
            "total_segmentos": len(df),
            "total_sinistros": int(df["sinistros"].sum()),
            "media_sinistros": float(df["sinistros"].mean()),
            "mediana_sinistros": float(df["sinistros"].median()),
            "perc_zero": float((df["sinistros"] == 0).mean() * 100),
            "modelo_escolhido": melhor,
        })

        irr_total.append(gerar_irr(modelo_final, municipio))

        ranking = df.copy()
        # Índice de criticidade ponderado pela centralidade de intermediação
        ranking["criticidade"] = ranking["sinistros"] * (ranking["betweenness"] * 100 + 1)
        ranking["municipio"] = municipio

        cols_ranking = ["municipio", "segmento", "sinistros", "betweenness", "criticidade"]
        if "nome_via" in ranking.columns:
            cols_ranking.append("nome_via")

        ranking_total.append(ranking[cols_ranking])

    # Exportação dos resultados
    if comparacao:
        pd.DataFrame(comparacao).to_csv(
            PASTA_ESTATISTICAS / "comparacao_modelos.csv",
            index=False,
            encoding="utf-8-sig"
        )
    if kpis:
        pd.DataFrame(kpis).to_csv(
            PASTA_ESTATISTICAS / "dashboard_kpis.csv",
            index=False,
            encoding="utf-8-sig"
        )
    if irr_total:
        pd.concat(irr_total, ignore_index=True).to_csv(
            PASTA_ESTATISTICAS / "irr_municipios.csv",
            index=False,
            encoding="utf-8-sig"
        )
    if ranking_total:
        pd.concat(ranking_total, ignore_index=True).sort_values(
            "criticidade", ascending=False
        ).to_csv(
            PASTA_ESTATISTICAS / "ranking_segmentos.csv",
            index=False,
            encoding="utf-8-sig"
        )

    print("\nProcessamento da Etapa 3 concluído.")
    print("Resultados salvos com sucesso em:", PASTA_ESTATISTICAS)


if __name__ == "__main__":
    main()
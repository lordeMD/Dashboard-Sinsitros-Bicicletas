# -*- coding: utf-8 -*-
"""01_etl.py: Extração, Limpeza e Tratamento dos dados brutos de sinistros."""
import sys
from pathlib import Path

# Garante que a raiz do projeto esteja no sys.path
RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import numpy as np
import pandas as pd

from config import (
    RAW, SEP_RAW, ENCODINGS_RAW, ANO_INICIAL, ANO_FINAL,
    SINISTROS_PARQUET, SINISTROS_CSV,
)

funil = []


def registrar(etapa, df):
    funil.append((etapa, len(df)))
    print(f"{etapa:<45} {len(df):>8}")


def normalizar_colunas(df):
    df.columns = (
        df.columns.astype(str)
        .str.replace("\ufeff", "", regex=False)
        .str.replace("ï»¿", "", regex=False)
        .str.strip()
        .str.lower()
    )
    return df


def ler_e_filtrar_arquivo(caminho):
    """Lê um CSV bruto tentando encodings adequados e filtra cedo por município e bicicleta."""
    municipios_validos = {
        "SANTOS", "SAO VICENTE", "SÃO VICENTE", "PRAIA GRANDE"
    }

    df = None
    for enc in ENCODINGS_RAW:
        try:
            df = pd.read_csv(caminho, sep=SEP_RAW, encoding=enc, low_memory=False)
            break
        except UnicodeDecodeError:
            continue
    if df is None:
        raise ValueError(f"Não foi possível ler {caminho.name} com os encodings suportados.")

    df = normalizar_colunas(df)
    
    # Filtro rápido de município e bicicleta
    if "municipio" in df.columns:
        df["municipio_raw"] = df["municipio"].astype(str).str.strip().str.upper()
        df = df[df["municipio_raw"].isin(municipios_validos)].copy()
    else:
        return pd.DataFrame()

    if "qtd_bicicleta" in df.columns:
        df["qtd_bicicleta"] = pd.to_numeric(df["qtd_bicicleta"], errors="coerce").fillna(0)
        df = df[df["qtd_bicicleta"] > 0].copy()
    else:
        return pd.DataFrame()

    df["arquivo_origem"] = caminho.name
    return df


def ler_raw():
    arquivos = sorted(RAW.glob("*.csv"))
    if not arquivos:
        raise FileNotFoundError(f"Nenhum arquivo CSV encontrado em {RAW}")

    print(f"Lendo {len(arquivos)} arquivos brutos em {RAW}...")
    dfs = []
    for a in arquivos:
        d = ler_e_filtrar_arquivo(a)
        if not d.empty:
            dfs.append(d)

    if not dfs:
        raise ValueError("Nenhum registro encontrado para os municípios selecionados com bicicleta.")

    concatenado = pd.concat(dfs, ignore_index=True)
    return concatenado


def padronizar_municipios(df):
    mapa = {
        "SANTOS": "Santos",
        "SAO VICENTE": "São Vicente",
        "SÃO VICENTE": "São Vicente",
        "PRAIA GRANDE": "Praia Grande",
    }
    df["municipio"] = df["municipio_raw"].map(mapa).fillna(df["municipio"])
    registrar("Municípios padronizados (Santos, SV, PG)", df)
    return df


def tratar_coordenadas(df):
    for c in ("latitude", "longitude"):
        if c in df.columns:
            df[c] = pd.to_numeric(
                df[c].astype(str).str.replace(",", ".", regex=False),
                errors="coerce"
            )

    df = df.dropna(subset=["latitude", "longitude"]).copy()
    registrar("Coordenadas numéricas válidas", df)

    # Limites geográficos aproximados da Baixada Santista
    dentro = (
        df["latitude"].between(-24.30, -23.70)
        & df["longitude"].between(-46.70, -46.00)
    )
    df = df[dentro].copy()
    registrar("Dentro da Baixada Santista", df)
    return df


def derivar_ano_e_filtrar(df):
    df["ano"] = pd.NA
    for c in ("ano_sinistro", "ano"):
        if c in df.columns and df[c].notna().any():
            df["ano"] = pd.to_numeric(df[c], errors="coerce")
            break
    else:
        for c in ("data_sinistro", "data", "dt_sinistro"):
            if c in df.columns:
                df["ano"] = pd.to_datetime(df[c], errors="coerce", dayfirst=True).dt.year
                break

    if df["ano"].notna().any():
        df = df[df["ano"].between(ANO_INICIAL, ANO_FINAL)].copy()
        registrar(f"Ano entre {ANO_INICIAL} e {ANO_FINAL}", df)
    else:
        print("AVISO: Nenhuma coluna de ano encontrada; sem filtro de ano.")
    return df


def achar_coluna_gravidade(df, palavras):
    prefixo = "qtd_gravidade"
    cols = [c for c in df.columns if c.startswith(prefixo)]
    achadas = [c for c in cols if any(p in c[len(prefixo):] for p in palavras)]
    if len(achadas) >= 1:
        return achadas[0]
    return None


def tratar_gravidade(df):
    cols = [c for c in df.columns if c.startswith("qtd_gravidade")]
    if cols:
        df[cols] = df[cols].apply(pd.to_numeric, errors="coerce").fillna(0)

    c_leve = achar_coluna_gravidade(df, ["leve"])
    c_grave = achar_coluna_gravidade(df, ["grave"])
    c_fatal = achar_coluna_gravidade(df, ["fatal", "fatais", "obito", "óbito", "morte"])

    df["vitimas_leves"] = df[c_leve].astype(int) if c_leve else 0
    df["vitimas_graves"] = df[c_grave].astype(int) if c_grave else 0
    df["vitimas_fatais"] = df[c_fatal].astype(int) if c_fatal else 0
    df["total_vitimas"] = df["vitimas_leves"] + df["vitimas_graves"] + df["vitimas_fatais"]

    condicoes = [
        df["vitimas_fatais"] > 0,
        df["vitimas_graves"] > 0,
        df["vitimas_leves"] > 0,
    ]
    escolhas = ["Fatal", "Grave", "Leve"]
    df["classe_gravidade"] = np.select(condicoes, escolhas, default="Sem vítimas informadas")
    return df


def tratar_tipo_sinistro(df):
    cols = [c for c in df.columns if c.startswith("tp_sinistro_") and c != "tp_sinistro_primario"]
    if not cols:
        df["tipo_sinistro"] = df.get("tp_sinistro_primario", "Não informado")
        return df
    marcado = df[cols].apply(lambda s: s.astype(str).str.strip().str.upper().eq("S")).to_numpy()
    nomes = np.array([c.replace("tp_sinistro_", "").replace("_", " ") for c in cols])
    df["tipo_sinistro"] = [", ".join(nomes[m]) or "Não informado" for m in marcado]
    return df


def remover_duplicatas(df):
    if "id_sinistro" in df.columns:
        antes = len(df)
        df = df.drop_duplicates(subset="id_sinistro").copy()
        removidas = antes - len(df)
        if removidas > 0:
            print(f"  -> {removidas} duplicatas removidas por id_sinistro")
        registrar("Sem duplicatas", df)
    return df


def main():
    print("=" * 60)
    print("ETAPA 1: ETL DE SINISTROS ENVOLVENDO BICICLETAS")
    print("=" * 60)
    
    df = ler_raw()
    registrar("Registros filtrados iniciais", df)

    df = padronizar_municipios(df)
    df = tratar_coordenadas(df)
    df = derivar_ano_e_filtrar(df)
    df = remover_duplicatas(df)
    df = tratar_gravidade(df)
    df = tratar_tipo_sinistro(df)

    df = df.reset_index(drop=True)
    df["id_interno"] = df.index

    # Exporta para os formatos finais
    df.to_parquet(SINISTROS_PARQUET, index=False)
    df.to_csv(SINISTROS_CSV, index=False, encoding="utf-8-sig")

    print("\nResumo por Município:")
    print(df["municipio"].value_counts())
    print("\nResumo por Gravidade:")
    print(df["classe_gravidade"].value_counts())
    print(f"\nArquivo salvo com sucesso em: {SINISTROS_CSV}")


if __name__ == "__main__":
    main()

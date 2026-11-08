# -*- coding: utf-8 -*-
"""02_mapa_espacial.py

Processa sinistros envolvendo bicicletas para Santos, São Vicente e Praia Grande.
Gera, para cada município:
- Mapa Folium interativo
- Arquivos de sinistros associados à rede
- Indicadores espaciais e topológicos por segmento da rede viária do OSM
- Datasets formatados para a análise estatística (03_analise_estatistica.py)
"""

import os
import sys
import re
import warnings
import random
from pathlib import Path

# Garante que a raiz do projeto esteja no sys.path
RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import pandas as pd
import geopandas as gpd
import osmnx as ox
import folium
import networkx as nx
from branca.element import Element
from folium.plugins import Fullscreen

from config import (
    SINISTROS_CSV, PASTA_MAPA, DISTANCIA_MAXIMA, CRS_METRICO,
    BETWEENNESS_K, MUNICIPIOS,
)

warnings.filterwarnings("ignore", category=UserWarning)

# Configurações do OSMnx
ox.settings.use_cache = True
ox.settings.log_console = True


def normalizar_texto(valor):
    if pd.isna(valor):
        return ""
    texto = str(valor).strip().upper()
    texto = re.sub(r"\s+", " ", texto)
    return texto


def nome_seguro(texto):
    return re.sub(r"[^A-Z0-9]+", "_", normalizar_texto(texto)).strip("_").lower()


def primeiro_valor(valor, padrao="Não informado"):
    if isinstance(valor, (list, tuple, set)):
        valores = list(valor)
        return str(valores[0]) if valores else padrao
    if pd.isna(valor) if not isinstance(valor, (list, tuple, set, dict)) else False:
        return padrao
    texto = str(valor).strip()
    return texto if texto and texto.lower() not in {"nan", "none"} else padrao


def cor_gravidade(gravidade):
    return {
        "Leve": "green",
        "Grave": "orange",
        "Fatal": "red",
        "Sem vítimas informadas": "blue",
    }.get(gravidade, "blue")


def cor_aresta(qtd):
    if qtd <= 0:
        return "gray"
    if qtd <= 2:
        return "blue"
    if qtd <= 5:
        return "orange"
    return "red"


def espessura_aresta(qtd):
    if qtd <= 0:
        return 1
    if qtd <= 2:
        return 2
    if qtd <= 5:
        return 3
    return 5


def carregar_dados_sinistros(caminho):
    if not os.path.exists(caminho):
        raise FileNotFoundError(
            f"Arquivo de sinistros não encontrado em '{caminho}'. Execute o 01_etl.py primeiro."
        )

    df = pd.read_csv(caminho, encoding="utf-8-sig", low_memory=False)
    df.columns = [str(c).replace("ï»¿", "").replace("\ufeff", "").strip().lower() for c in df.columns]

    df["municipio_norm"] = df["municipio"].map(normalizar_texto)
    df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
    df = df.dropna(subset=["latitude", "longitude"]).copy()

    if "id_interno" not in df.columns:
        df["id_interno"] = range(1, len(df) + 1)
    if "classe_gravidade" not in df.columns:
        df["classe_gravidade"] = "Não informado"

    return df


def filtrar_municipio(df, config_mun):
    aliases = {normalizar_texto(x) for x in config_mun["aliases"]}
    aliases.add(normalizar_texto(config_mun["nome"]))
    return df[df["municipio_norm"].isin(aliases)].copy()


def obter_rede(municipio, lugar_osm):
    print(f"\nBaixando/carregando rede viária ciclística para {municipio} via OSMnx...")
    grafo = ox.graph_from_place(lugar_osm, network_type="bike", simplify=True, retain_all=False)
    try:
        grafo = ox.add_edge_speeds(grafo)
    except Exception as e:
        print(f"Aviso ao calcular velocidades: {e}")
    try:
        grafo = ox.add_edge_travel_times(grafo)
    except Exception as e:
        print(f"Aviso ao calcular tempos de viagem: {e}")

    nos, arestas = ox.graph_to_gdfs(grafo, nodes=True, edges=True, fill_edge_geometry=True)
    if arestas.crs is None:
        arestas = arestas.set_crs("EPSG:4326")
    return grafo, nos, arestas


def associar_sinistros_a_rede(dados, arestas):
    pontos = gpd.GeoDataFrame(
        dados.copy(),
        geometry=gpd.points_from_xy(dados["longitude"], dados["latitude"]),
        crs="EPSG:4326",
    )
    pontos_m = pontos.to_crs(CRS_METRICO)
    arestas_m = arestas.to_crs(CRS_METRICO).reset_index()

    if "key" not in arestas_m.columns:
        arestas_m["key"] = 0

    associados = gpd.sjoin_nearest(
        pontos_m,
        arestas_m[["u", "v", "key", "geometry"]],
        how="left",
        distance_col="distancia_m",
    )
    associados = associados.sort_values("distancia_m").drop_duplicates(subset=["id_interno"], keep="first")
    associados["associado_rede"] = associados["distancia_m"].le(DISTANCIA_MAXIMA)
    associados = associados.drop(columns=[c for c in associados.columns if c == "index_right"], errors="ignore")

    gdf_associados = associados[associados["associado_rede"]].copy()
    gdf_fora = associados[~associados["associado_rede"]].copy()
    return pontos, gdf_associados, gdf_fora


def calcular_closeness_amostrado(grafo, k=200, seed=42):
    """Calcula aproximação de closeness centrality via Dijkstra amostrado para performance."""
    grafo_undir = nx.Graph(grafo)
    nos = list(grafo_undir.nodes)
    if not nos:
        return {}
    random.seed(seed)
    n_sample = min(k, len(nos))
    sample = random.sample(nos, n_sample)

    dists = {n: 0.0 for n in nos}
    counts = {n: 0 for n in nos}

    for s in sample:
        comprimentos = nx.single_source_dijkstra_path_length(grafo_undir, s, weight="length")
        for target, d in comprimentos.items():
            dists[target] += d
            counts[target] += 1

    closeness = {}
    for n in nos:
        if counts[n] > 0 and dists[n] > 0:
            avg_dist = dists[n] / counts[n]
            closeness[n] = float(counts[n] / (n_sample * avg_dist))
        else:
            closeness[n] = 0.0
    return closeness


def calcular_metricas_rede(grafo, arestas, sinistros_associados):
    arestas_m = arestas.to_crs(CRS_METRICO).reset_index()
    if "key" not in arestas_m.columns:
        arestas_m["key"] = 0

    if len(sinistros_associados):
        contagem = (
            sinistros_associados.groupby(["u", "v", "key"], dropna=False)
            .agg(
                qtd_sinistros=("id_interno", "nunique"),
                vitimas_leves=("vitimas_leves", lambda s: pd.to_numeric(s, errors="coerce").fillna(0).sum()),
                vitimas_graves=("vitimas_graves", lambda s: pd.to_numeric(s, errors="coerce").fillna(0).sum()),
                vitimas_fatais=("vitimas_fatais", lambda s: pd.to_numeric(s, errors="coerce").fillna(0).sum()),
            )
            .reset_index()
        )
    else:
        contagem = pd.DataFrame(columns=["u", "v", "key", "qtd_sinistros", "vitimas_leves", "vitimas_graves", "vitimas_fatais"])

    arestas_m = arestas_m.merge(contagem, on=["u", "v", "key"], how="left")
    for col in ["qtd_sinistros", "vitimas_leves", "vitimas_graves", "vitimas_fatais"]:
        arestas_m[col] = pd.to_numeric(arestas_m[col], errors="coerce").fillna(0).astype(int)
    arestas_m["total_vitimas"] = arestas_m["vitimas_leves"] + arestas_m["vitimas_graves"] + arestas_m["vitimas_fatais"]
    arestas_m["comprimento_m"] = arestas_m.geometry.length

    print("Calculando betweenness...")
    try:
        betweenness = nx.edge_betweenness_centrality(grafo, k=BETWEENNESS_K, weight="length", normalized=True, seed=42)
    except TypeError:
        betweenness = nx.edge_betweenness_centrality(grafo, k=BETWEENNESS_K, weight="length", normalized=True)

    arestas_m["betweenness"] = [
        float(betweenness.get((row.u, row.v, row.key), betweenness.get((row.v, row.u, row.key), 0.0)))
        for row in arestas_m[["u", "v", "key"]].itertuples(index=False)
    ]

    print("Calculando closeness das extremidades...")
    closeness = calcular_closeness_amostrado(grafo, k=BETWEENNESS_K, seed=42)
    arestas_m["closeness_media_extremidades"] = [
        (closeness.get(row.u, 0.0) + closeness.get(row.v, 0.0)) / 2
        for row in arestas_m[["u", "v"]].itertuples(index=False)
    ]

    # Atributos viários do OSM
    if "speed_kph" in arestas_m.columns:
        arestas_m["speed_kph"] = pd.to_numeric(arestas_m["speed_kph"], errors="coerce")
    else:
        arestas_m["speed_kph"] = pd.NA
    arestas_m["speed_kph"] = arestas_m["speed_kph"].fillna(30.0)  # Padrão urbano

    arestas_m["nome_via"] = arestas_m.get("name", pd.Series("Sem nome", index=arestas_m.index)).apply(primeiro_valor)
    arestas_m["tipo_via_osm"] = arestas_m.get("highway", pd.Series("Não informado", index=arestas_m.index)).apply(primeiro_valor)
    arestas_m["cycleway"] = arestas_m.get("cycleway", pd.Series("Não informado", index=arestas_m.index)).apply(primeiro_valor)
    arestas_m["surface"] = arestas_m.get("surface", pd.Series("Não informado", index=arestas_m.index)).apply(primeiro_valor)
    arestas_m["lit"] = arestas_m.get("lit", pd.Series("Não informado", index=arestas_m.index)).apply(primeiro_valor)

    # Identificador legível do segmento
    arestas_m["segmento"] = [
        f"{row.nome_via} ({row.u}-{row.v})" if row.nome_via != "Sem nome" else f"Segmento ({row.u}-{row.v})"
        for row in arestas_m[["nome_via", "u", "v"]].itertuples(index=False)
    ]

    # Indicador de ciclovia
    tem_ciclovia = (
        arestas_m["cycleway"].astype(str).str.lower().isin(["yes", "lane", "track", "opposite_lane", "separate"])
        | (arestas_m["tipo_via_osm"].astype(str).str.lower() == "cycleway")
    )
    arestas_m["ciclovia_bin"] = tem_ciclovia.astype(int)
    arestas_m["ciclovia_txt"] = tem_ciclovia.map({True: "Sim", False: "Não"})

    colunas = [
        "u", "v", "key", "segmento", "nome_via", "tipo_via_osm", "cycleway", "ciclovia_txt", "ciclovia_bin",
        "surface", "lit", "comprimento_m", "speed_kph", "qtd_sinistros", "vitimas_leves", "vitimas_graves",
        "vitimas_fatais", "total_vitimas", "betweenness", "closeness_media_extremidades", "geometry"
    ]
    return gpd.GeoDataFrame(arestas_m[colunas].copy(), geometry="geometry", crs=CRS_METRICO)


def adicionar_camadas_pontos(mapa, dados, nome_camada, exibir=True):
    camada = folium.FeatureGroup(name=nome_camada, show=exibir)
    for _, row in dados.iterrows():
        lat = float(row["latitude"])
        lon = float(row["longitude"])
        gravidade = row.get("classe_gravidade", "Sem vítimas informadas")
        cor = cor_gravidade(gravidade)
        rua = row.get("logradouro", "Não informado")
        data = row.get("data_sinistro", "Não informado")
        tipo = row.get("tipo_sinistro", "Não informado")
        distancia = row.get("distancia_m", None)
        distancia_txt = f"{float(distancia):.1f} m" if pd.notna(distancia) else "Não calculada"
        popup_html = f"""
        <div style='width:260px; font-family:sans-serif;'>
          <h4 style='margin-bottom:6px;'>Sinistro de Bicicleta</h4>
          <b>ID:</b> {row.get('id_sinistro', row.get('id_interno'))}<br>
          <b>Data:</b> {data}<br>
          <b>Logradouro:</b> {rua}<br>
          <b>Tipo:</b> {tipo}<br>
          <b>Gravidade:</b> <span style='color:{cor}; font-weight:bold;'>{gravidade}</span><br>
          <b>Distância da rede:</b> {distancia_txt}
        </div>"""
        folium.CircleMarker(
            location=[lat, lon], radius=5 if gravidade != "Fatal" else 7,
            color=cor, fill=True, fill_color=cor, fill_opacity=0.85,
            popup=folium.Popup(popup_html, max_width=320),
            tooltip=f"{gravidade} | {data} | {rua}",
        ).add_to(camada)
    camada.add_to(mapa)


def gerar_mapa(municipio, configuracao, arestas_analise, dados_associados, dados_fora, caminho_html):
    # Projeta para WGS84 para visualização no Folium
    arestas_wgs = arestas_analise.to_crs("EPSG:4326")
    mapa = folium.Map(location=configuracao["centro"], zoom_start=13, control_scale=True, tiles="OpenStreetMap")
    Fullscreen(position="topright", title="Tela cheia", title_cancel="Sair da tela cheia").add_to(mapa)

    camada_rede = folium.FeatureGroup(name="Rede viária colorida por sinistros", show=True)
    print(f"Desenhando segmentos no mapa de {municipio}...")
    for _, row in arestas_wgs.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        geometrias = list(geom.geoms) if geom.geom_type == "MultiLineString" else [geom]
        qtd = int(row["qtd_sinistros"])
        popup_html = f"""
        <div style='width:290px; font-family:sans-serif;'>
          <h4 style='margin-bottom:6px;'>Segmento Viário</h4>
          <b>Via:</b> {row['nome_via']}<br>
          <b>Tipo OSM:</b> {row['tipo_via_osm']}<br>
          <b>Sinistros de bike:</b> <b style='color:{cor_aresta(qtd)}; font-size:14px;'>{qtd}</b><br>
          <b>Vítimas fatais:</b> {int(row['vitimas_fatais'])}<br>
          <b>Vítimas graves:</b> {int(row['vitimas_graves'])}<br>
          <b>Vítimas leves:</b> {int(row['vitimas_leves'])}<br>
          <b>Ciclovia:</b> {row['ciclovia_txt']}<br>
          <b>Comprimento:</b> {float(row['comprimento_m']):.1f} m<br>
          <b>Betweenness:</b> {float(row['betweenness']):.5f}<br>
          <b>Closeness:</b> {float(row['closeness_media_extremidades']):.5f}
        </div>"""
        popup = folium.Popup(popup_html, max_width=330)
        for linha in geometrias:
            coords = [[lat, lon] for lon, lat in linha.coords]
            folium.PolyLine(
                locations=coords, color=cor_aresta(qtd), weight=espessura_aresta(qtd),
                opacity=0.75, popup=popup,
            ).add_to(camada_rede)
    camada_rede.add_to(mapa)

    adicionar_camadas_pontos(mapa, dados_associados, "Sinistros associados à rede", True)
    if len(dados_fora):
        adicionar_camadas_pontos(mapa, dados_fora, "Sinistros fora do limite (30m)", False)
    fatais = dados_associados[dados_associados["classe_gravidade"] == "Fatal"]
    if len(fatais):
        adicionar_camadas_pontos(mapa, fatais, "Sinistros fatais", False)

    folium.LayerControl(collapsed=False).add_to(mapa)
    legenda = f"""
    <div style='position:fixed;bottom:25px;left:25px;width:280px;z-index:9999;
    background:white;border:2px solid #555;border-radius:8px;padding:12px;
    font-size:12px;box-shadow:2px 2px 6px rgba(0,0,0,.25); font-family:sans-serif;'>
      <b style='font-size:14px;'>LEGENDA — {municipio}</b><hr style='margin:6px 0;'>
      <b>REDE (Sinistros associados)</b><br>
      <span style='color:gray;font-size:18px;'>━━━━</span> 0 sinistros<br>
      <span style='color:blue;font-size:18px;'>━━━━</span> 1–2 sinistros<br>
      <span style='color:orange;font-size:18px;'>━━━━</span> 3–5 sinistros<br>
      <span style='color:red;font-size:18px;'>━━━━</span> Mais de 5 sinistros<hr style='margin:6px 0;'>
      <b>GRAVIDADE DOS SINISTROS</b><br>
      <span style='color:green;'>●</span> Leve&nbsp;&nbsp;
      <span style='color:orange;'>●</span> Grave&nbsp;&nbsp;
      <span style='color:red;'>●</span> Fatal&nbsp;&nbsp;
      <span style='color:blue;'>●</span> Sem info<hr style='margin:6px 0;'>
      Tolerância espacial: <b>{DISTANCIA_MAXIMA} m</b> da rede viária.
    </div>"""
    mapa.get_root().html.add_child(Element(legenda))
    mapa.save(caminho_html)


def exportar_gdf_csv(gdf, caminho):
    tabela = gdf.copy()
    if "geometry" in tabela.columns:
        tabela["geometry"] = tabela.geometry.to_wkt()
    tabela.to_csv(caminho, index=False, encoding="utf-8-sig")


def processar_municipio(df_completo, chave_mun, configuracao):
    dados = filtrar_municipio(df_completo, configuracao)
    nome_mun = configuracao["nome"]
    if dados.empty:
        print(f"AVISO: Nenhum sinistro encontrado para {nome_mun}.")
        return

    base = nome_seguro(chave_mun)
    prefixo = PASTA_MAPA / f"{base}_{DISTANCIA_MAXIMA}m"
    print("\n" + "=" * 70)
    print(f"MUNICÍPIO: {nome_mun} ({chave_mun}) | Sinistros válidos: {len(dados)}")
    print("=" * 70)

    grafo, nos, arestas = obter_rede(nome_mun, configuracao["osm"])
    pontos_originais, associados, fora = associar_sinistros_a_rede(dados, arestas)

    # Métricas da rede
    arestas_analise = calcular_metricas_rede(grafo, arestas, associados)

    # Exporta resultados detalhados
    exportar_gdf_csv(associados, f"{prefixo}_sinistros_associados.csv")
    exportar_gdf_csv(fora, f"{prefixo}_sinistros_nao_associados.csv")
    exportar_gdf_csv(arestas_analise, f"{prefixo}_indicadores_segmentos.csv")

    # Exporta no formato exato esperado pela etapa 03 (análise estatística)
    df_para_estatistica = pd.DataFrame({
        "Segmento": arestas_analise["segmento"],
        "Comprimento (m)": arestas_analise["comprimento_m"],
        "Betweenness": arestas_analise["betweenness"],
        "Closeness": arestas_analise["closeness_media_extremidades"],
        "Velocidade da via (km/h)": arestas_analise["speed_kph"],
        "Ciclovia": arestas_analise["ciclovia_txt"],
        "Quantidade de Sinistros": arestas_analise["qtd_sinistros"],
        "nome_via": arestas_analise["nome_via"],
        "tipo_via_osm": arestas_analise["tipo_via_osm"],
    })

    # Salva tanto na pasta do mapa quanto na raiz para compatibilidade total
    caminho_csv_estat = PASTA_MAPA / f"dataset_segmentos_{base}_30M.csv"
    caminho_csv_raiz = RAIZ / f"dataset_segmentos_{base}_30M.csv"
    df_para_estatistica.to_csv(caminho_csv_estat, index=False, encoding="utf-8-sig")
    df_para_estatistica.to_csv(caminho_csv_raiz, index=False, encoding="utf-8-sig")

    # Mapa interativo HTML
    caminho_html = PASTA_MAPA / f"{base}_{DISTANCIA_MAXIMA}m_mapa.html"
    gerar_mapa(nome_mun, configuracao, arestas_analise, associados, fora, str(caminho_html))

    print(f"\nResumo de {nome_mun}:")
    print(f"  Sinistros com coordenadas válidas: {len(dados)}")
    print(f"  Associados a rede (<= {DISTANCIA_MAXIMA} m): {len(associados)} ({len(associados)/len(dados)*100:.1f}%)")
    print(f"  Segmentos viários analisados: {len(arestas_analise)}")
    print(f"  Mapa salvo em: {caminho_html}")
    print(f"  Dataset estatístico salvo em: {caminho_csv_raiz}")


def main():
    print("=" * 60)
    print("ETAPA 2: ANÁLISE ESPACIAL E REDE VIÁRIA")
    print("=" * 60)

    dados = carregar_dados_sinistros(SINISTROS_CSV)
    print(f"Total de registros no CSV consolidado: {len(dados)}")
    print("Contagem por município:")
    print(dados["municipio"].value_counts().to_string())

    for chave_mun, configuracao in MUNICIPIOS.items():
        try:
            processar_municipio(dados, chave_mun, configuracao)
        except Exception as exc:
            import traceback
            print(f"\nERRO ao processar {chave_mun}: {type(exc).__name__}: {exc}")
            traceback.print_exc()

    print("\nProcessamento da Etapa 2 finalizado. Arquivos gerados em:", PASTA_MAPA)


if __name__ == "__main__":
    main()

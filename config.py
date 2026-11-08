"""Configuração central do pipeline. Todos os scripts (e o app.py) importam daqui."""
import argparse
from pathlib import Path

# Raiz do projeto
RAIZ = Path(__file__).resolve().parent

# Diretórios de dados e resultados
RAW = RAIZ / "dados" / "raw"
PROCESSED = RAIZ / "dados" / "processados"
RESULTADOS = RAIZ / "dados" / "resultados"
CACHE = RAIZ / "dados" / "cache"

PASTA_MAPA = RAIZ / "resultados_mapa_espacial"
PASTA_ESTATISTICAS = RAIZ / "resultados_estatisticos"

for _p in (PROCESSED, RESULTADOS, CACHE, PASTA_MAPA, PASTA_ESTATISTICAS):
    _p.mkdir(parents=True, exist_ok=True)

# --- Recorte do estudo ---------------------------------------------------
MUNICIPIOS = {
    "SANTOS": {
        "nome": "Santos",
        "osm": "Santos, São Paulo, Brazil",
        "centro": [-23.9608, -46.3336],
        "aliases": ["SANTOS"],
    },
    "SAO VICENTE": {
        "nome": "São Vicente",
        "osm": "São Vicente, São Paulo, Brazil",
        "centro": [-23.9631, -46.3919],
        "aliases": ["SAO VICENTE", "SÃO VICENTE", "SAO VICENTE (SP)"],
    },
    "PRAIA GRANDE": {
        "nome": "Praia Grande",
        "osm": "Praia Grande, São Paulo, Brazil",
        "centro": [-24.0058, -46.4028],
        "aliases": ["PRAIA GRANDE", "PRAIA GRANDE (SP)"],
    },
}

ANO_INICIAL, ANO_FINAL = 2020, 2025

# --- Leitura dos CSVs brutos --------------------------------------------
SEP_RAW = ";"
ENCODINGS_RAW = ("latin1", "utf-8-sig")

# --- Espacial ------------------------------------------------------------
DISTANCIA_MAXIMA = 30          # metros
CRS_METRICO = "EPSG:31983"     # SIRGAS 2000 / UTM 23S
BETWEENNESS_K = 200

# --- Arquivos ------------------------------------------------------------
SINISTROS_PARQUET = PROCESSED / "sinistros_bicicleta.parquet"
SINISTROS_CSV = PROCESSED / "sinistros_bicicleta.csv"

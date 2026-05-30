import os
import logging
import pandas as pd
from dotenv import load_dotenv
from entsoe import EntsoePandasClient

# Configuration d'un logging standard (remplace les print() pour la traçabilité)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_entsoe_client() -> EntsoePandasClient:
    """Initialise et authentifie le client ENTSO-E."""
    load_dotenv() 
    api_token = os.environ.get('ENTSOE_TOKEN')
    
    if not api_token:
        raise ValueError("La variable d'environnement ENTSOE_TOKEN est introuvable.")
    
    return EntsoePandasClient(api_key=api_token)

def fetch_load_in_chunks(client: EntsoePandasClient, country_code: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    """
    Extrait la charge électrique de manière itérative (année par année).
    Prévient les erreurs HTTP 504 (Timeout) sur les longues périodes.
    """
    logging.info(f"Extraction {country_code} : {start.date()} à {end.date()}")
    
    # Création d'une grille temporelle annuelle
    years = pd.date_range(start, end, freq='YS')
    if start not in years: years = years.insert(0, start)
    if end not in years: years = years.insert(len(years), end)
        
    series_chunks = []
    
    for i in range(len(years) - 1):
        chunk_start = years[i]
        chunk_end = years[i+1]
        logging.info(f" -> Téléchargement de la période {chunk_start.year}...")
        
        try:
            ts_chunk = client.query_load(country_code, start=chunk_start, end=chunk_end)
            series_chunks.append(ts_chunk)
        except Exception as e:
            logging.error(f"Échec sur {country_code} pour {chunk_start.year} : {str(e)}")
            continue
            
    if not series_chunks:
        raise RuntimeError(f"Échec total de l'extraction pour {country_code}.")
        
    # Concaténation et suppression des doublons exacts aux frontières temporelles
    ts_full = pd.concat(series_chunks)
    ts_full = ts_full[~ts_full.index.duplicated(keep='first')]
    
    # Agrégation journalière stricte
    ts_daily = ts_full.resample('D').mean()
    
    # Sécurisation du type de retour : conversion forcée en Series si l'API renvoie un DataFrame
    if isinstance(ts_daily, pd.DataFrame):
        ts_daily = ts_daily.iloc[:, 0]
        
    ts_daily.name = f"{country_code}_Load_MW"
    
    return ts_daily

def enforce_data_quality(df: pd.DataFrame) -> pd.DataFrame:
    """
    Diagnostique et corrige les anomalies de la série temporelle.
    """
    missing_stats = df.isna().sum()
    logging.info(f"Diagnostic des valeurs manquantes (NaN) :\n{missing_stats}")
    
    if missing_stats.sum() > 0:
        logging.info("Application d'une interpolation temporelle pour combler les NaN.")
        # L'interpolation temporelle est mathématiquement appropriée pour la charge électrique
        df = df.interpolate(method='time')
        
    # Vérification finale de l'absence de trous
    assert df.isna().sum().sum() == 0, "Des valeurs manquantes persistent après l'imputation."
    return df

if __name__ == "__main__":
    client = get_entsoe_client()
    tz = 'Europe/Paris'
    
    start_date = pd.Timestamp('2018-01-01', tz=tz)
    end_date = pd.Timestamp('2024-01-01', tz=tz)
    
    # Extraction par pays
    s_fr = fetch_load_in_chunks(client, 'FR', start_date, end_date)
    s_de = fetch_load_in_chunks(client, 'DE', start_date, end_date)
    
    # Consolidation multivariée
    df_conso = pd.concat([s_fr, s_de], axis=1)
    
    # Phase d'assurance qualité (Crucial pour ARIMA)
    df_conso = enforce_data_quality(df_conso)
    
    # Sauvegarde
    output_file = 'data_entsoe_daily.parquet'
    df_conso.to_parquet(output_file)
    logging.info(f"Pipeline terminé. Fichier généré : {output_file}")
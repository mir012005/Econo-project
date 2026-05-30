import logging
import pandas as pd
import holidays
import openmeteo_requests
import requests_cache
from retry_requests import retry

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_openmeteo_client():
    """Initialise le client Open-Meteo avec cache et re-tentatives."""
    cache_session = requests_cache.CachedSession('.cache', expire_after=-1)
    retry_session = retry(cache_session, retries=5, backoff_factor=0.2)
    return openmeteo_requests.Client(session=retry_session)

def generate_calendar_features(index: pd.DatetimeIndex) -> pd.DataFrame:
    """Crée les variables calendaires (Week-end et Jours Fériés)."""
    logging.info("Génération des variables calendaires...")
    
    df_cal = pd.DataFrame(index=index)
    
    # Indicateur Week-end (5 = Samedi, 6 = Dimanche)
    df_cal['Is_Weekend'] = df_cal.index.dayofweek.isin([5, 6]).astype(int)
    
    # Initialisation des calendriers de jours fériés
    fr_holidays = holidays.France(years=index.year.unique().tolist())
    de_holidays = holidays.Germany(years=index.year.unique().tolist())
    
    # Indicateurs Jours Fériés
    df_cal['FR_Holiday'] = df_cal.index.map(lambda d: int(d in fr_holidays))
    df_cal['DE_Holiday'] = df_cal.index.map(lambda d: int(d in de_holidays))
    
    return df_cal

def fetch_weather_data(client, lat: float, lon: float, start_date: str, end_date: str, prefix: str) -> pd.Series:
    """Extrait la température moyenne journalière depuis Open-Meteo Archive."""
    logging.info(f"Extraction météo pour {prefix} ({lat}, {lon}) de {start_date} à {end_date}...")
    
    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start_date,
        "end_date": end_date,
        "daily": "temperature_2m_mean",
        "timezone": "Europe/Paris"
    }
    
    response = client.weather_api(url, params=params)[0]
    daily = response.Daily()
    
    # Reconstruction de l'index temporel
    daily_temperature_2m_mean = daily.Variables(0).ValuesAsNumpy()
    dates = pd.date_range(
        start=pd.to_datetime(daily.Time(), unit="s", utc=True).tz_convert("Europe/Paris"),
        end=pd.to_datetime(daily.TimeEnd(), unit="s", utc=True).tz_convert("Europe/Paris"),
        freq=pd.Timedelta(seconds=daily.Interval()),
        inclusive="left"
    )
    
    # Retrait de la timezone pour correspondre à un index "naive" ou forcer l'alignement
    ts = pd.Series(
        data=daily_temperature_2m_mean, 
        index=dates.normalize(), 
        name=f"{prefix}_Temp_Mean"
    )
    return ts

# Format : { 'Nom_Ville': (Latitude, Longitude, Poids) }
FR_CITIES = {
    'Paris': (48.8566, 2.3522, 0.30),
    'Lyon': (45.7640, 4.8357, 0.20),
    'Marseille': (43.2965, 5.3698, 0.15),
    'Lille': (50.6292, 3.0573, 0.20),
    'Toulouse': (43.6047, 1.4442, 0.15)
}

DE_CITIES = {
    'Berlin': (52.5200, 13.4050, 0.20),
    'Munich': (48.1351, 11.5820, 0.20),
    'Cologne': (50.9375, 6.9603, 0.25),   # Proxy pour la Ruhr (très industriel)
    'Hambourg': (53.5511, 9.9937, 0.15),
    'Francfort': (50.1109, 8.6821, 0.20)
}

def fetch_weighted_weather(client, cities_dict: dict, start_date: str, end_date: str, prefix: str) -> pd.Series:
    """
    Calcule la température moyenne journalière pondérée sur un ensemble de villes.
    """
    logging.info(f"Calcul de la température pondérée pour {prefix}...")
    weighted_series = None
    
    for city, (lat, lon, weight) in cities_dict.items():
        # Appel à votre fonction existante
        ts_city = fetch_weather_data(client, lat, lon, start_date, end_date, f"{prefix}_{city}")
        
        # Pondération
        if weighted_series is None:
            weighted_series = ts_city * weight
        else:
            weighted_series += ts_city * weight
            
    weighted_series.name = f"{prefix}_Temp_Weighted_Mean"
    return weighted_series

if __name__ == "__main__":
    # 1. Chargement de l'index de référence depuis le fichier de consommation
    try:
        df_conso = pd.read_parquet('data_entsoe_daily.parquet')
        ref_index = df_conso.index
    except FileNotFoundError:
        raise RuntimeError("Fichier data_entsoe_daily.parquet introuvable. Exécutez pipeline_extraction.py d'abord.")

    # 2. Variables calendaires
    df_exogenes = generate_calendar_features(ref_index)
    
    # 3. Variables climatiques (Open-Meteo)
    start_str = ref_index.min().strftime('%Y-%m-%d')
    end_str = ref_index.max().strftime('%Y-%m-%d')
    
    client = get_openmeteo_client()
    
    """
    # Utilisation de Paris et Berlin comme proxys initiaux
    s_temp_fr = fetch_weather_data(client, 48.8566, 2.3522, start_str, end_str, "FR")
    s_temp_de = fetch_weather_data(client, 52.5200, 13.4050, start_str, end_str, "DE")
    """
    # Remplacement des proxys uniques par les moyennes pondérées
    s_temp_fr = fetch_weighted_weather(client, FR_CITIES, start_str, end_str, "FR")
    s_temp_de = fetch_weighted_weather(client, DE_CITIES, start_str, end_str, "DE")
    
    # Jointure sur l'index de référence (garantit qu'aucune ligne n'est décalée)
    df_exogenes = df_exogenes.join(s_temp_fr).join(s_temp_de)
    
    # 4. Vérification et Sauvegarde
    missing = df_exogenes.isna().sum()
    if missing.sum() > 0:
        logging.info("Interpolation des données météo manquantes.")
        df_exogenes = df_exogenes.interpolate(method='time')
        
    output_file = 'data_exogenes_daily.parquet'
    df_exogenes.to_parquet(output_file)
    logging.info(f"Pipeline exogène terminé. Fichier généré : {output_file}")
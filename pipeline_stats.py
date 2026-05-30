import pandas as pd
import matplotlib.pyplot as plt
from statsmodels.tsa.stattools import adfuller
from statsmodels.graphics.tsaplots import plot_acf, plot_pacf

def merge_datasets() -> pd.DataFrame:
    """Fusionne la consommation et les variables exogènes sur l'index temporel."""
    df_conso = pd.read_parquet('data_entsoe_daily.parquet')
    df_exo = pd.read_parquet('data_exogenes_daily.parquet')
    
    # Jointure interne stricte pour s'assurer qu'il n'y a pas de décalage de dates
    df_master = df_conso.join(df_exo, how='inner')
    
    # Sauvegarde du livrable final pour les Lots 2 et 3
    df_master.to_parquet('dataset_final.parquet')
    print("Master Dataset généré avec succès : dataset_final.parquet")
    print(f"Dimensions : {df_master.shape}")
    
    return df_master

def run_adf_test(series: pd.Series, name: str):
    """
    Exécute le test de Dickey-Fuller Augmenté (ADF).
    H0 : La série possède une racine unitaire (non stationnaire).
    """
    result = adfuller(series.dropna())
    print(f"\n--- Test ADF pour {name} ---")
    print(f"Statistique de test : {result[0]:.4f}")
    print(f"p-value : {result[1]:.4e}")
    
    if result[1] < 0.05:
        print("-> Rejet de H0 : La série est stationnaire au seuil de 5%.")
    else:
        print("-> Non-rejet de H0 : La série est NON stationnaire (intégration requise).")

def plot_correlograms(series: pd.Series, name: str, lags: int = 40):
    """Trace l'ACF et la PACF pour identifier les composantes AR, MA et la saisonnalité."""
    fig, axes = plt.subplots(2, 1, figsize=(12, 8))
    
    plot_acf(series.dropna(), lags=lags, ax=axes[0], title=f"Autocorrélation (ACF) - {name}")
    plot_pacf(series.dropna(), lags=lags, ax=axes[1], title=f"Autocorrélation Partielle (PACF) - {name}")
    
    plt.tight_layout()
    plt.savefig(f'correlogram_{name}.png', dpi=300)
    plt.close()
    print(f"Corrélogrammes sauvegardés : correlogram_{name}.png")

if __name__ == "__main__":
    # 1. Création du dataset final
    df = merge_datasets()
    
    # 2. Tests de stationnarité sur les variables cibles
    run_adf_test(df['FR_Load_MW'], 'Consommation France')
    run_adf_test(df['DE_Load_MW'], 'Consommation Allemagne')
    
    # 3. Génération des graphiques (on observe sur 40 jours pour voir les cycles hebdomadaires)
    plot_correlograms(df['FR_Load_MW'], 'FR')
    plot_correlograms(df['DE_Load_MW'], 'DE')
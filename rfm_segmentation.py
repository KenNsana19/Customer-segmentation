"""
Segmentation clients (RFM + K-Means) et analyse des produits rentables
Dataset : Online Retail II (UCI / Kaggle)
https://archive.ics.uci.edu/dataset/502/online+retail+ii
"""
import os

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

DATA_PATH = "online_retail_II.xlsx"  # ou un .csv
FIG_DIR = "figures"
RANDOM_STATE = 42
os.makedirs(FIG_DIR, exist_ok=True)


# ==========================================
# 1. CHARGEMENT ET NETTOYAGE
# ==========================================
def load_data(path):
    if path.endswith(".csv"):
        df = pd.read_csv(path, encoding="ISO-8859-1")
    else:
        sheets = pd.read_excel(path, sheet_name=None)  # 2 feuilles : 2009-2010 et 2010-2011
        df = pd.concat(sheets.values(), ignore_index=True)
    return df.rename(columns={"Price": "UnitPrice", "Customer ID": "CustomerID"})


def clean_retail_data(df):
    print("--- Nettoyage des données ---")
    n0 = len(df)

    df = df.dropna(subset=["CustomerID"]).copy()
    df["CustomerID"] = df["CustomerID"].astype(int)
    df["Invoice"] = df["Invoice"].astype(str)

    # Retours (factures 'C...'), quantités / prix invalides
    df = df[~df["Invoice"].str.startswith("C")]
    df = df[(df["Quantity"] > 0) & (df["UnitPrice"] > 0)]

    # Lignes qui ne sont pas des produits (POST, DOT, M, BANK CHARGES, AMAZONFEE...)
    # Les vrais produits ont un StockCode commençant par 5 chiffres
    df = df[df["StockCode"].astype(str).str.match(r"^\d{5}")]

    df = df.drop_duplicates().copy()

    df["TotalSum"] = df["Quantity"] * df["UnitPrice"]
    df["InvoiceDate"] = pd.to_datetime(df["InvoiceDate"])
    df["Description"] = df["Description"].astype(str).str.strip().str.upper()

    print(f"{n0} lignes -> {len(df)} lignes valides")
    return df


# ==========================================
# 2. MATRICE RFM
# ==========================================
def compute_rfm_features(df):
    print("--- Calcul RFM ---")
    snapshot_date = df["InvoiceDate"].max() + pd.Timedelta(days=1)

    rfm = df.groupby("CustomerID").agg(
        Recency=("InvoiceDate", lambda x: (snapshot_date - x.max()).days),
        Frequency=("Invoice", "nunique"),
        Monetary=("TotalSum", "sum"),
    )
    return rfm


# ==========================================
# 3. PRÉTRAITEMENT
# ==========================================
def preprocess_rfm(rfm):
    # log1p pour réduire l'asymétrie, puis standardisation (K-Means = distances euclidiennes)
    rfm_log = np.log1p(rfm[["Recency", "Frequency", "Monetary"]])
    rfm_scaled = StandardScaler().fit_transform(rfm_log)
    return rfm_scaled


# ==========================================
# 4. CHOIX DE K (coude + silhouette)
# ==========================================
def choose_k(rfm_scaled, k_range=range(2, 9)):
    inertias, silhouettes = [], []
    for k in k_range:
        km = KMeans(n_clusters=k, init="k-means++", n_init=10, random_state=RANDOM_STATE)
        labels = km.fit_predict(rfm_scaled)
        inertias.append(km.inertia_)
        silhouettes.append(silhouette_score(rfm_scaled, labels))

    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    axes[0].plot(list(k_range), inertias, "o-")
    axes[0].set(title="Méthode du coude", xlabel="K", ylabel="Inertie")
    axes[1].plot(list(k_range), silhouettes, "o-", color="darkorange")
    axes[1].set(title="Score de silhouette", xlabel="K", ylabel="Silhouette")
    plt.tight_layout()
    plt.savefig(f"{FIG_DIR}/choix_k.png", dpi=150)
    plt.show()

    best_k = list(k_range)[int(np.argmax(silhouettes))]
    print(f"Silhouettes : {dict(zip(k_range, np.round(silhouettes, 3)))}")
    print(f"K suggéré par la silhouette : {best_k} (à confronter au coude et à l'interprétation métier)")
    return best_k


# ==========================================
# 5. K-MEANS
# ==========================================
def apply_kmeans(rfm_scaled, rfm, n_clusters):
    km = KMeans(n_clusters=n_clusters, init="k-means++", n_init=10, random_state=RANDOM_STATE)
    rfm = rfm.copy()
    rfm["Cluster"] = km.fit_predict(rfm_scaled)
    print(f"K={n_clusters} | silhouette = {silhouette_score(rfm_scaled, rfm['Cluster']):.3f}")
    return rfm, km


# ==========================================
# 6. ANALYSE DES CLUSTERS
# ==========================================
def analyze_clusters(rfm):
    summary = rfm.groupby("Cluster").agg(
        Recency=("Recency", "mean"),
        Frequency=("Frequency", "mean"),
        Monetary_mean=("Monetary", "mean"),
        Revenue=("Monetary", "sum"),
        Customers=("Monetary", "count"),
    ).round(1)
    summary["%_clients"] = (100 * summary["Customers"] / summary["Customers"].sum()).round(1)
    summary["%_CA"] = (100 * summary["Revenue"] / summary["Revenue"].sum()).round(1)
    print(summary)
    return summary


# ==========================================
# 7. PRODUITS : RENTABILITÉ GLOBALE ET PAR CLUSTER
# ==========================================
def top_products(df, n=10):
    top = (df.groupby("Description")
             .agg(Revenue=("TotalSum", "sum"), Units=("Quantity", "sum"))
             .nlargest(n, "Revenue"))
    print(f"\n--- Top {n} produits par chiffre d'affaires ---")
    print(top.round(0))

    plt.figure(figsize=(9, 5))
    sns.barplot(x=top["Revenue"], y=top.index, color="steelblue")
    plt.title(f"Top {n} produits par chiffre d'affaires")
    plt.xlabel("CA (£)")
    plt.ylabel("")
    plt.tight_layout()
    plt.savefig(f"{FIG_DIR}/top_produits.png", dpi=150)
    plt.show()
    return top


def top_products_by_cluster(df, rfm, n=5):
    df = df.copy()
    df["Cluster"] = df["CustomerID"].map(rfm["Cluster"])
    df = df.dropna(subset=["Cluster"])

    result = {}
    for c, sub in df.groupby("Cluster"):
        top = sub.groupby("Description")["TotalSum"].sum().nlargest(n)
        result[int(c)] = top
        print(f"\n--- Cluster {int(c)} : top {n} produits (CA) ---")
        print(top.round(0))
    return result


# ==========================================
# 8. VISUALISATIONS
# ==========================================
def plot_pca(rfm_scaled, rfm):
    pca = PCA(n_components=2, random_state=RANDOM_STATE)
    coords = pca.fit_transform(rfm_scaled)
    plt.figure(figsize=(8, 6))
    sns.scatterplot(x=coords[:, 0], y=coords[:, 1], hue=rfm["Cluster"],
                    palette="tab10", s=15, alpha=0.7)
    plt.title(f"Clusters en PCA ({pca.explained_variance_ratio_.sum():.0%} de variance expliquée)")
    plt.xlabel("PC1")
    plt.ylabel("PC2")
    plt.tight_layout()
    plt.savefig(f"{FIG_DIR}/pca_clusters.png", dpi=150)
    plt.show()


def plot_heatmap(rfm_scaled, rfm):
    scaled = pd.DataFrame(rfm_scaled, columns=["Recency", "Frequency", "Monetary"],
                          index=rfm.index)
    scaled["Cluster"] = rfm["Cluster"]
    profile = scaled.groupby("Cluster").mean()
    plt.figure(figsize=(6, 4))
    sns.heatmap(profile, annot=True, fmt=".2f", cmap="RdBu_r", center=0)
    plt.title("Profil RFM par cluster (valeurs standardisées)")
    plt.tight_layout()
    plt.savefig(f"{FIG_DIR}/heatmap_rfm.png", dpi=150)
    plt.show()


# ==========================================
# PIPELINE
# ==========================================
def main(n_clusters=None):
    df = clean_retail_data(load_data(DATA_PATH))
    rfm = compute_rfm_features(df)
    rfm_scaled = preprocess_rfm(rfm)

    k_suggested = choose_k(rfm_scaled)
    k = n_clusters or k_suggested

    rfm, _ = apply_kmeans(rfm_scaled, rfm, k)
    analyze_clusters(rfm)
    plot_pca(rfm_scaled, rfm)
    plot_heatmap(rfm_scaled, rfm)

    top_products(df)
    top_products_by_cluster(df, rfm)
    rfm.to_csv("rfm_clusters.csv")
    return df, rfm


if __name__ == "__main__":
    main(n_clusters=4)

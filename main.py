import streamlit as st
import fiona
import os
import tempfile
from pyproj import CRS, Transformer
from shapely.geometry import shape
from shapely.ops import transform
import folium
from streamlit_folium import st_folium

st.set_page_config(page_title="Geo-Expert Diagnostic", layout="wide")

# --- LOGIQUE MÉTIER ---
def analyze_coherence(src, target_epsg_code):
    issues = []
    score = 100
    try:
        declared_crs = CRS.from_user_input(src.crs if src.crs else "EPSG:4326")
        epsg_str = f"EPSG:{declared_crs.to_epsg()}" if declared_crs.to_epsg() else "Inconnu"
    except:
        declared_crs = CRS.from_user_input("EPSG:4326")
        epsg_str = "WGS84 (Défaut)"
        score -= 20
        issues.append("Axe 0 : Métadonnées de projection absentes.")

    b = src.bounds
    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    
    # Axe 1 : Métrique
    if declared_crs.is_geographic and (abs(cx) > 180 or abs(cy) > 90):
        score -= 40
        issues.append("Axe 1 : Coordonnées métriques dans un système géographique.")

    # Axe 3 : Topologie
    trans = Transformer.from_crs(declared_crs, "EPSG:4326", always_xy=True)
    lon, lat = trans.transform(cx, cy)
    if target_epsg_code == "EPSG:2154" and not (41 < lat < 52 and -5 < lon < 10):
        score -= 30
        issues.append(f"Axe 3 : Décalage spatial (Localisé à {lat:.2f}, {lon:.2f}).")

    return score, issues, epsg_str, (lat, lon)

# --- INTERFACE STREAMLIT ---
st.title("🔍 Geo-Expert : Audit & Conversion")

col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("1. Configuration")
    target_city = st.text_input("Commune cible", "Saint-Lô, France")
    # Pour l'exemple on simplifie le choix EPSG (tu peux garder ta logique Nominatim ici)
    target_epsg = st.selectbox("Système cible", ["EPSG:2154", "EPSG:4326", "EPSG:3857"], index=0)

    uploaded_file = st.file_uploader("Charger un GeoPackage ou Shapefile (ZIP)", type=["gpkg", "zip"])

if uploaded_file:
    # Sauvegarde temporaire pour Fiona
    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded_file.name)[1]) as tmp:
        tmp.write(uploaded_file.getvalue())
        tmp_path = tmp.name
    
    vfs_path = f"zip://{tmp_path}" if tmp_path.endswith('.zip') else tmp_path

    try:
        with fiona.open(vfs_path) as src:
            score, issues, detected_epsg, center = analyze_coherence(src, target_epsg)
            
            with col2:
                st.subheader("2. Diagnostic")
                st.metric("Score de fiabilité", f"{score}%")
                st.progress(score / 100)
                
                for issue in issues:
                    st.error(issue)
                if not issues:
                    st.success("✅ Aucune anomalie majeure détectée.")

                # Affichage de la carte
                m = folium.Map(location=[center[0], center[1]], zoom_start=12)
                folium.Marker([center[0], center[1]], popup=f"Centroïde: {detected_epsg}").add_to(m)
                st_folium(m, height=300, width=None)

            # --- CONVERSION ---
            st.divider()
            if st.button("🚀 Convertir et Télécharger en GPKG"):
                out_path = os.path.join(tempfile.gettempdir(), "converted.gpkg")
                dest_crs = CRS.from_user_input(target_epsg)
                transformer = Transformer.from_crs(src.crs, dest_crs, always_xy=True)
                
                with fiona.open(out_path, 'w', driver='GPKG', crs=dest_crs, schema=src.schema.copy()) as dst:
                    for feat in src:
                        new_geom = transform(transformer.transform, shape(feat['geometry']))
                        dst.write({'geometry': new_geom.__geo_interface__, 'properties': feat['properties']})
                
                with open(out_path, "rb") as f:
                    st.download_button("💾 Télécharger le fichier .gpkg", f, file_name=f"converted_{target_epsg}.gpkg")

    except Exception as e:
        st.error(f"Erreur de lecture : {e}")
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

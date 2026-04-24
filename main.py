import streamlit as st
import fiona
import os
import tempfile
import requests
from pyproj import CRS, Transformer
from shapely.geometry import shape
from shapely.ops import transform
import folium
from streamlit_folium import st_folium

st.set_page_config(page_title="Geo-Expert Pro", layout="wide")

# --- FONCTION DE RECHERCHE DE COMMUNE (Comme en HTML) ---
def get_target_epsg_from_city(city_name):
    try:
        url = f"https://nominatim.openstreetmap.org/search?format=json&q={city_name}&limit=1"
        response = requests.get(url, headers={'User-Agent': 'GeoAuditApp/1.0'})
        data = response.json()
        if data:
            lon = float(data[0]['lon'])
            lat = float(data[0]['lat'])
            display_name = data[0]['display_name']
            
            # Logique d'incrémentation automatique
            if "France" in display_name:
                return "EPSG:2154", display_name
            else:
                utm_zone = int((lon + 180) / 6) + 1
                epsg = (32600 if lat >= 0 else 32700) + utm_zone
                return f"EPSG:{epsg}", display_name
    except Exception as e:
        return "EPSG:4326", f"Erreur recherche : {e}"
    return "EPSG:4326", "Non trouvé (WGS84 par défaut)"

# --- LOGIQUE D'AUDIT ---
def analyze_coherence(src, target_epsg_code):
    issues = []
    score = 100
    
    # 1. Correction de la détection EPSG Entrée
    try:
        # On force la lecture du CRS depuis le fichier
        source_crs = CRS.from_user_input(src.crs)
        detected_epsg = f"EPSG:{source_crs.to_epsg()}" if source_crs.to_epsg() else source_crs.to_string()
    except Exception:
        source_crs = CRS.from_user_input("EPSG:4326")
        detected_epsg = "Inconnu (WGS84 par défaut)"
        score -= 20
        issues.append("Axe 0 : Impossible de lire le système d'origine (.prj manquant ?)")

    # 2. Analyse spatiale
    b = src.bounds
    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    
    # Axe 1 : Cohérence métrique
    if source_crs.is_geographic and (abs(cx) > 180 or abs(cy) > 90):
        score -= 40
        issues.append("Axe 1 : Les coordonnées sont métriques mais le système est en Degrés.")

    # Axe 3 : Cohérence topologique
    try:
        transformer_to_wgs = Transformer.from_crs(source_crs, "EPSG:4326", always_xy=True)
        lon_c, lat_c = transformer_to_wgs.transform(cx, cy)
        
        if target_epsg_code == "EPSG:2154" and not (41 < lat_c < 52 and -5 < lon_c < 10):
            score -= 30
            issues.append(f"Axe 3 : Décalage. Données situées vers {lat_c:.2f}, {lon_c:.2f}")
    except:
        lat_c, lon_c = 0, 0

    return score, issues, detected_epsg, (lat_c, lon_c), source_crs

# --- INTERFACE ---
st.title("🌍 Geo-Expert : Audit & Conversion Automatisée")

col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("1. Paramètres")
    city_input = st.text_input("Tapez une commune (incrémente l'EPSG cible)", "Saint-Lô, France")
    
    # Automatisation de l'EPSG cible
    auto_epsg, full_name = get_target_epsg_from_city(city_input)
    st.info(f"📍 Cible détectée : **{auto_epsg}**\n({full_name})")
    
    # On laisse quand même le choix à l'utilisateur si besoin
    target_epsg = st.text_input("Confirmer l'EPSG cible", value=auto_epsg)

    uploaded_file = st.file_uploader("Fichier (.gpkg ou .zip)", type=["gpkg", "zip"])

if uploaded_file:
    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded_file.name)[1]) as tmp:
        tmp.write(uploaded_file.getvalue())
        tmp_path = tmp.name
    
    vfs_path = f"zip://{tmp_path}" if tmp_path.endswith('.zip') else tmp_path

    try:
        with fiona.open(vfs_path) as src:
            score, issues, det_epsg, center, final_src_crs = analyze_coherence(src, target_epsg)
            
            with col2:
                st.subheader("2. Rapport d'Audit")
                st.metric("Score de fiabilité", f"{score}%")
                st.write(f"**EPSG Source détecté :** `{det_epsg}`")
                
                for issue in issues:
                    st.error(issue)
                
                # Carte
                m = folium.Map(location=[center[0], center[1]], zoom_start=12)
                folium.Marker([center[0], center[1]], popup="Emplacement des données").add_to(m)
                st_folium(m, height=300, width=None)

            # --- CONVERSION ---
            st.divider()
            if st.button("🛠️ Lancer la conversion en GeoPackage"):
                out_path = os.path.join(tempfile.gettempdir(), f"output_{target_epsg.replace(':','_')}.gpkg")
                dst_crs = CRS.from_user_input(target_epsg)
                transformer = Transformer.from_crs(final_src_crs, dst_crs, always_xy=True)
                
                with fiona.open(out_path, 'w', driver='GPKG', crs=dst_crs, schema=src.schema.copy()) as dst:
                    for feat in src:
                        new_geom = transform(transformer.transform, shape(feat['geometry']))
                        dst.write({'geometry': new_geom.__geo_interface__, 'properties': feat['properties']})
                
                with open(out_path, "rb") as f:
                    st.download_button("💾 Télécharger le GPKG corrigé", f, file_name=f"export_{target_epsg}.gpkg")

    except Exception as e:
        st.error(f"Erreur Fiona : {e}")
    finally:
        if os.path.exists(tmp_path): os.unlink(tmp_path)

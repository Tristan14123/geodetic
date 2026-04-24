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

st.set_page_config(page_title="Geo-Expert Pro v3", layout="wide")

# --- RECHERCHE COMMUNE ---
def get_target_epsg_from_city(city_name):
    try:
        url = f"https://nominatim.openstreetmap.org/search?format=json&q={city_name}&limit=1"
        response = requests.get(url, headers={'User-Agent': 'GeoAuditApp/1.0'})
        data = response.json()
        if data:
            lon, lat = float(data[0]['lon']), float(data[0]['lat'])
            display_name = data[0]['display_name']
            if "France" in display_name:
                return "EPSG:2154", display_name
            utm_zone = int((lon + 180) / 6) + 1
            epsg = (32600 if lat >= 0 else 32700) + utm_zone
            return f"EPSG:{epsg}", display_name
    except: pass
    return "EPSG:4326", "WGS84 par défaut"

# --- LOGIQUE D'AUDIT & MÉTADONNÉES ---
def analyze_full(src, target_epsg_code):
    issues = []
    score = 100
    
    # 1. Extraction CRS
    try:
        source_crs = CRS.from_user_input(src.crs)
        detected_epsg = f"EPSG:{source_crs.to_epsg()}" if source_crs.to_epsg() else "Personnalisé"
    except:
        source_crs = CRS.from_user_input("EPSG:4326")
        detected_epsg = "Inconnu (WGS84 assumé)"
        score -= 20
        issues.append("Métadonnées de projection absentes.")

    # 2. Analyse Spatiale
    b = src.bounds
    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    
    # 3. Métadonnées Techniques
    metadata = {
        "Format (Driver)": src.driver,
        "Type de Géométrie": src.schema['geometry'],
        "Nombre d'entités": len(src),
        "Colonnes (Attributs)": ", ".join(list(src.schema['properties'].keys())),
        "Emprise Ouest": round(b[0], 2),
        "Emprise Sud": round(b[1], 2),
        "Emprise Est": round(b[2], 2),
        "Emprise Nord": round(b[3], 2),
    }

    # 4. Vérification Dérive (Axe 3)
    try:
        transformer_to_wgs = Transformer.from_crs(source_crs, "EPSG:4326", always_xy=True)
        lon_c, lat_c = transformer_to_wgs.transform(cx, cy)
        if target_epsg_code == "EPSG:2154" and not (41 < lat_c < 52 and -5 < lon_c < 10):
            score -= 30
            issues.append(f"Décalage spatial détecté ({lat_c:.2f}, {lon_c:.2f}).")
    except: lat_c, lon_c = 0, 0

    return score, issues, detected_epsg, (lat_c, lon_c), source_crs, metadata

# --- INTERFACE ---
st.title("🌍 Geo-Expert : Audit & Rapport Métadonnées")

col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("⚙️ Configuration")
    city_input = st.text_input("Commune du projet", "Saint-Lô, France")
    auto_epsg, full_name = get_target_epsg_from_city(city_input)
    target_epsg = st.text_input("EPSG Cible", value=auto_epsg)
    st.caption(f"Localisation : {full_name}")

    uploaded_file = st.file_uploader("Fichier (.gpkg ou .zip)", type=["gpkg", "zip"])

if uploaded_file:
    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded_file.name)[1]) as tmp:
        tmp.write(uploaded_file.getvalue())
        tmp_path = tmp.name
    
    vfs_path = f"zip://{tmp_path}" if tmp_path.endswith('.zip') else tmp_path

    try:
        with fiona.open(vfs_path) as src:
            score, issues, det_epsg, center, f_src_crs, meta = analyze_full(src, target_epsg)
            
            with col2:
                st.subheader("📊 Diagnostic")
                st.metric("Score de fiabilité", f"{score}%")
                
                # Liste des problèmes
                if issues:
                    for i in issues: st.warning(i)
                else: st.success("Données cohérentes.")

                # Carte
                m = folium.Map(location=[center[0], center[1]], zoom_start=12)
                folium.Marker([center[0], center[1]], popup="Centroïde").add_to(m)
                st_folium(m, height=250, width=None)

            # --- RAPPORT DE MÉTADONNÉES ---
            st.divider()
            with st.expander("📝 Voir le rapport détaillé des métadonnées"):
                c_m1, c_m2 = st.columns(2)
                items = list(meta.items())
                half = len(items) // 2
                
                with c_m1:
                    for k, v in items[:half]: st.write(f"**{k} :** {v}")
                    st.write(f"**CRS Source :** `{det_epsg}`")
                with c_m2:
                    for k, v in items[half:]: st.write(f"**{k} :** {v}")
                    st.write(f"**Centroïde WGS84 :** `{round(center[0],4)}, {round(center[1],4)}`")

            # --- CONVERSION ---
            if st.button("🛠️ Convertir en GeoPackage"):
                out_path = os.path.join(tempfile.gettempdir(), "converted.gpkg")
                dst_crs = CRS.from_user_input(target_epsg)
                transformer = Transformer.from_crs(f_src_crs, dst_crs, always_xy=True)
                
                with fiona.open(out_path, 'w', driver='GPKG', crs=dst_crs, schema=src.schema.copy()) as dst:
                    for feat in src:
                        new_geom = transform(transformer.transform, shape(feat['geometry']))
                        dst.write({'geometry': new_geom.__geo_interface__, 'properties': feat['properties']})
                
                with open(out_path, "rb") as f:
                    st.download_button("💾 Télécharger le GPKG", f, file_name=f"export_{target_epsg}.gpkg")

    except Exception as e: st.error(f"Erreur : {e}")
    finally:
        if os.path.exists(tmp_path): os.unlink(tmp_path)

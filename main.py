import os, shutil, tempfile, uuid
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import fiona
from pyproj import CRS, Transformer
from shapely.geometry import shape
from shapely.ops import transform

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

TEMP_DIR = tempfile.gettempdir()

def get_fiona_path(temp_path):
    return f"zip://{temp_path}" if temp_path.lower().endswith('.zip') else temp_path

def analyze_coherence(src, target_epsg_code):
    issues = []
    score = 100
    
    # Tentative d'extraction CRS
    try:
        declared_crs = CRS.from_user_input(src.crs if src.crs else "EPSG:4326")
        epsg_str = f"EPSG:{declared_crs.to_epsg()}" if declared_crs.to_epsg() else "Inconnu (Défini par texte)"
    except:
        declared_crs = CRS.from_user_input("EPSG:4326")
        epsg_str = "Non défini (WGS84 par défaut)"
        score -= 20
        issues.append("Axe 0 : Absence de métadonnées de projection (.prj manquant).")

    # Calcul du centroïde
    b = src.bounds
    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    
    # Analyse Métrique (Axe 1)
    if declared_crs.is_geographic and (abs(cx) > 180 or abs(cy) > 90):
        score -= 40
        issues.append("Axe 1 : Coordonnées métriques détectées dans un système géographique.")

    # Analyse Topologique (Axe 3)
    try:
        trans = Transformer.from_crs(declared_crs, "EPSG:4326", always_xy=True)
        lon, lat = trans.transform(cx, cy)
        if target_epsg_code == "EPSG:2154" and not (41 < lat < 52 and -5 < lon < 10):
            score -= 30
            issues.append(f"Axe 3 : Décalage spatial majeur (Localisé à {lat:.2f}, {lon:.2f}).")
    except: pass

    metadata = {
        "driver": src.driver,
        "schema": src.schema['geometry'],
        "crs_name": declared_crs.name,
        "is_metric": not declared_crs.is_geographic,
        "bounds": {"min_x": b[0], "min_y": b[1], "max_x": b[2], "max_y": b[3]},
        "center_wgs84": {"lat": lat if 'lat' in locals() else None, "lon": lon if 'lon' in locals() else None}
    }
    
    return score, issues, epsg_str, metadata

@app.post("/audit")
async def audit_file(file: UploadFile = File(...), target_epsg: str = Form(...)):
    suffix = os.path.splitext(file.filename)[1]
    path = os.path.join(TEMP_DIR, f"audit_{uuid.uuid4()}{suffix}")
    with open(path, "wb") as f: shutil.copyfileobj(file.file, f)
    try:
        with fiona.open(get_fiona_path(path)) as src:
            score, issues, epsg, meta = analyze_coherence(src, target_epsg)
            return {
                "status": "success",
                "filename": file.filename,
                "detected_epsg": epsg,
                "confidence_score": max(0, score),
                "issues": issues,
                "feature_count": len(src),
                "metadata": meta
            }
    except Exception as e: return {"status": "error", "message": str(e)}
    finally:
        if os.path.exists(path): os.unlink(path)

@app.post("/convert")
async def convert_file(file: UploadFile = File(...), target_epsg: str = Form(...)):
    suffix = os.path.splitext(file.filename)[1]
    in_path = os.path.join(TEMP_DIR, f"in_{uuid.uuid4()}{suffix}")
    out_name = f"reprojected_{target_epsg.replace(':', '_')}.gpkg"
    out_path = os.path.join(TEMP_DIR, out_name)
    with open(in_path, "wb") as f: shutil.copyfileobj(file.file, f)
    try:
        with fiona.open(get_fiona_path(in_path)) as src:
            source_crs = src.crs
            dest_crs = CRS.from_user_input(target_epsg)
            transformer = Transformer.from_crs(source_crs, dest_crs, always_xy=True)
            with fiona.open(out_path, 'w', driver='GPKG', crs=dest_crs, schema=src.schema.copy()) as dst:
                for feat in src:
                    new_geom = transform(transformer.transform, shape(feat['geometry']))
                    dst.write({'geometry': new_geom.__geo_interface__, 'properties': feat['properties']})
        return FileResponse(path=out_path, filename=out_name)
    except Exception as e: return {"status": "error", "message": str(e)}
    finally:
        if os.path.exists(in_path): os.unlink(in_path)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
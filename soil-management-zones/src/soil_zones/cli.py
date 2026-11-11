"""Interface de linha de comando e exportação dos resultados."""
import argparse
import json
import math
from pathlib import Path

import numpy as np
from rasterio.features import geometry_mask
from rasterio.transform import from_bounds, xy

from .data import load_scenes
from .processing import classify, relative_ndvi, sampling_points, usable_field
from .rendering import render


def main() -> None:
    parser = argparse.ArgumentParser(description="Zonas de manejo por NDVI relativo")
    parser.add_argument("--field", type=Path, required=True)
    parser.add_argument("--seasons", type=int, default=3)
    parser.add_argument("--k", type=int, default=3)
    parser.add_argument("--out", type=Path, default=Path("out"))
    parser.add_argument("--center-radius-m", type=float, default=40)
    parser.add_argument("--edge-buffer-m", type=float, default=20)
    parser.add_argument("--min-patch-area-m2", type=float, default=2500)
    args = parser.parse_args()
    if args.seasons < 1 or args.k < 1 or min(args.center_radius_m, args.edge_buffer_m, args.min_patch_area_m2) < 0:
        parser.error("--seasons e --k devem ser positivos")
    geo = json.loads(args.field.read_text(encoding="utf-8"))
    if geo.get("type") == "FeatureCollection" and len(geo.get("features", [])) == 1:
        geometry = geo["features"][0]["geometry"]
    elif geo.get("type") == "Feature":
        geometry = geo["geometry"]
    else:
        parser.error("O arquivo deve conter um único polígono GeoJSON")
    if geometry["type"] != "Polygon":
        parser.error("O talhão deve ser um polígono GeoJSON em longitude/latitude")
    coordinates = np.array([p for ring in geometry["coordinates"] for p in ring])
    left, bottom = coordinates.min(axis=0)
    right, top = coordinates.max(axis=0)
    dx, dy = (right - left) * .1, (top - bottom) * .1
    bbox = (left - dx, bottom - dy, right + dx, top + dy)
    width_m = (bbox[2] - bbox[0]) * 111320 * math.cos(math.radians((top + bottom) / 2))
    height_m = (bbox[3] - bbox[1]) * 110574
    # Square pixels in the exported map, with a square bounding box.
    side = max(width_m, height_m)
    cx, cy = (left + right) / 2, (bottom + top) / 2
    hx = side / (2 * 111320 * math.cos(math.radians(cy)))
    hy = side / (2 * 110574)
    bbox = (cx - hx, cy - hy, cx + hx, cy + hy)
    size = max(1, math.ceil(side / 10))
    shape = (size, size)
    transform = from_bounds(*bbox, size, size)
    field = geometry_mask([geometry], out_shape=shape, transform=transform, invert=True)
    if not field.any():
        parser.error("O polígono não cobre pixels na resolução de análise")
    try:
        scenes, records, rgb, rgb_date = load_scenes(bbox, shape, args.seasons)
        index = relative_ndvi(scenes, field)
        pixel_size = side / size
        usable = usable_field(field, pixel_size, args.center_radius_m, args.edge_buffer_m)
        zones = classify(index, usable, args.k, max(1, math.ceil(args.min_patch_area_m2 / pixel_size**2)))
    except Exception as exc:
        parser.exit(1, f"Erro ao obter ou processar imagens: {exc}\n")
    points = sampling_points(zones)
    args.out.mkdir(parents=True, exist_ok=True)
    render(rgb, index, zones, points, str(args.out), [record["ano"] for record in records])
    features = []
    for zone, y, x in points:
        lon, lat = xy(transform, y, x)
        features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]}, "properties": {"zona": zone}})
    (args.out / "pontos_coleta.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False, indent=2), encoding="utf-8")
    total = int((zones > 0).sum())
    pixel_ha = (side / size) ** 2 / 10000
    summary = {"fonte": "Sentinel-2 L2A / Microsoft Planetary Computer", "janela_safra": "janeiro a junho", "safras": records,
               "data_cor_real": rgb_date, "resolucao_m": side / size, "area_talhao_ha": round(int(field.sum()) * pixel_ha, 2),
               "area_mapeada_ha": round(total * pixel_ha, 2), "zonas": [
                   {"zona": int(z), "area_ha": round(int((zones == z).sum()) * pixel_ha, 2), "percentual_area_mapeada": round(100 * int((zones == z).sum()) / total, 2), "ndvi_relativo_medio": round(float(index[zones == z].mean()), 4)}
                   for z in np.unique(zones[zones > 0])], "pontos_coleta": len(points)}
    if len(points) == 1:
        summary["aviso"] = "Uma única zona significativa foi identificada."
    (args.out / "resumo.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(points)} zonas; {total * pixel_ha:.1f} ha mapeados em {args.out}")

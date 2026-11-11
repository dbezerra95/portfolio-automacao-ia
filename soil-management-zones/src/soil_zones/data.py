"""Consulta ao catálogo público e leitura das bandas Sentinel-2 L2A."""
from datetime import date

import numpy as np
import planetary_computer
import rasterio
from pystac_client import Client
from rasterio.enums import Resampling
from rasterio.transform import from_bounds
from rasterio.vrt import WarpedVRT

STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"


def load_scenes(bbox: tuple[float, float, float, float], shape: tuple[int, int], seasons: int) -> tuple[np.ndarray, list[dict], np.ndarray, str]:
    """Busca até seis cenas pouco nubladas por ano completo, de janeiro a junho."""
    catalog = Client.open(STAC, modifier=planetary_computer.sign_inplace)
    transform = from_bounds(*bbox, shape[1], shape[0])
    stacks, records = [], []
    best_rgb, best_score, rgb_date = None, -1, ""
    for year in range(date.today().year - seasons, date.today().year):
        search = catalog.search(collections=["sentinel-2-l2a"], bbox=bbox,
                                datetime=f"{year}-01-01/{year}-06-30", query={"eo:cloud_cover": {"lt": 20}})
        candidates = sorted(search.items(), key=lambda item: item.properties.get("eo:cloud_cover", 100))
        items = []
        dates = set()
        for item in candidates:
            day = item.datetime.date()
            if day not in dates:
                items.append(item)
                dates.add(day)
            if len(items) == 6:
                break
        if len(items) < 2:
            raise ValueError(f"Safra {year}: menos de duas cenas com menos de 20% de nuvens")
        images, used = [], []
        for item in items:
            bands = []
            for band in ("B04", "B08", "SCL"):
                with rasterio.open(item.assets[band].href) as src:
                    with WarpedVRT(src, crs="EPSG:4326", transform=transform, width=shape[1], height=shape[0], resampling=Resampling.nearest) as vrt:
                        bands.append(vrt.read(1))
            red, nir, scl = bands
            valid = np.isin(scl, [4, 5]) & ((red.astype(float) + nir) > 0)
            ndvi = np.full(shape, np.nan, dtype=np.float32)
            np.divide(nir.astype(float) - red, nir.astype(float) + red, out=ndvi, where=valid)
            images.append(ndvi)
            used.append({"id": item.id, "data": item.datetime.date().isoformat(), "nuvem_cena_pct": item.properties.get("eo:cloud_cover")})
            score = int(valid.sum())
            if year == date.today().year - 1 and score > best_score:
                with rasterio.open(item.assets["visual"].href) as src:
                    with WarpedVRT(src, crs="EPSG:4326", transform=transform, width=shape[1], height=shape[0]) as vrt:
                        best_rgb = np.moveaxis(vrt.read([1, 2, 3]), 0, -1)
                best_score, rgb_date = score, item.datetime.date().isoformat()
        stacks.append(images)
        records.append({"ano": year, "cenas": used})
    # Pad only if a year has fewer scenes than the others.
    maximum = max(map(len, stacks))
    for stack in stacks:
        stack.extend([np.full(shape, np.nan)] * (maximum - len(stack)))
    if best_rgb is None:
        raise ValueError("Não foi possível obter imagem em cor real")
    return np.asarray(stacks), records, best_rgb, rgb_date

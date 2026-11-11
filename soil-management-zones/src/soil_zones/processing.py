"""Operações numéricas independentes de acesso a dados e apresentação."""
import warnings

import numpy as np
from scipy import ndimage
from sklearn.cluster import KMeans


def relative_ndvi(seasons: np.ndarray, field: np.ndarray) -> np.ndarray:
    """Média dos picos por safra divididos pela mediana do talhão em cada safra."""
    normalized = []
    for scenes in seasons:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="All-NaN slice encountered")
            peak = np.nanmax(scenes, axis=0)
        valid = field & np.isfinite(peak)
        if not valid.any():
            raise ValueError("Safra sem pixels válidos dentro do talhão")
        median = float(np.median(peak[valid]))
        if median <= 0:
            raise ValueError("Mediana de NDVI não positiva; não é possível normalizar")
        normalized.append(np.where(valid, peak / median, np.nan))
    stack = np.stack(normalized)
    count = np.sum(np.isfinite(stack), axis=0)
    # Require observations in at least half the seasons.
    total = np.nansum(stack, axis=0)
    return np.divide(total, count, out=np.full(field.shape, np.nan), where=count >= (len(stack) + 1) // 2)



def usable_field(field: np.ndarray, pixel_size: float, center_radius: float = 40, edge_buffer: float = 20) -> np.ndarray:
    """Exclui o centro do pivô e uma faixa interna junto ao limite."""
    if pixel_size <= 0 or center_radius < 0 or edge_buffer < 0 or not field.any():
        raise ValueError("Máscara ou distâncias inválidas")
    rows, cols = np.where(field)
    cy, cx = (rows.min() + rows.max()) / 2, (cols.min() + cols.max()) / 2
    y, x = np.indices(field.shape)
    edge_distance = ndimage.distance_transform_edt(np.pad(field, 1))[1:-1, 1:-1] * pixel_size
    return field & (np.hypot(y - cy, x - cx) * pixel_size >= center_radius) & (edge_distance > edge_buffer)

def clean_patches(zones: np.ndarray, min_pixels: int) -> np.ndarray:
    """Substitui componentes pequenos pela zona vizinha mais frequente."""
    result = zones.copy()
    structure = ndimage.generate_binary_structure(2, 1)
    for zone in np.unique(zones[zones > 0]):
        components, count = ndimage.label(zones == zone, structure)
        for component in range(1, count + 1):
            patch = components == component
            if patch.sum() >= min_pixels:
                continue
            neighbors = result[ndimage.binary_dilation(patch, structure=structure) & ~patch]
            neighbors = neighbors[(neighbors > 0) & (neighbors != zone)]
            if neighbors.size:
                result[patch] = np.bincount(neighbors).argmax()
    return result


def classify(index: np.ndarray, field: np.ndarray, k: int = 3, min_pixels: int = 25) -> np.ndarray:
    """K-means determinístico, com zona 1 representando o menor NDVI relativo."""
    valid = field & np.isfinite(index)
    # A mediana local elimina linhas de um pixel sem misturar pixels excluídos.
    padded = np.pad(np.where(valid, index, np.nan), 1, constant_values=np.nan)
    windows = np.lib.stride_tricks.sliding_window_view(padded, (3, 3))
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="All-NaN slice encountered")
        filtered = np.nanmedian(windows, axis=(-2, -1))
    values = filtered[valid]
    if not values.size or k < 1:
        raise ValueError("Sem pixels válidos ou número de zonas inválido")
    zones = np.zeros(field.shape, dtype=np.int16)
    if np.ptp(values) < 1e-6:
        zones[valid] = 1
        return zones
    n = min(k, np.unique(values).size)
    model = KMeans(n_clusters=n, random_state=0, n_init=10).fit(values.reshape(-1, 1))
    order = np.argsort(model.cluster_centers_.ravel())
    ranks = np.empty(n, dtype=int)
    ranks[order] = np.arange(1, n + 1)
    zones[valid] = ranks[model.labels_]
    zones = clean_patches(zones, min_pixels)
    # Cleanup can change means; order the remaining zones by their actual values.
    labels = sorted(np.unique(zones[zones > 0]), key=lambda z: float(np.mean(index[zones == z])))
    return np.select([zones == z for z in labels], list(range(1, len(labels) + 1)), default=0).astype(np.int16)


def sampling_points(zones: np.ndarray) -> list[tuple[int, int, int]]:
    """Um ponto no interior de cada zona, no maior componente conectado."""
    points = []
    for zone in np.unique(zones[zones > 0]):
        components, count = ndimage.label(zones == zone)
        sizes = np.bincount(components.ravel(), minlength=count + 1)
        sizes[0] = 0
        patch = components == sizes.argmax()
        distance = ndimage.distance_transform_edt(np.pad(patch, 1))[1:-1, 1:-1]
        y, x = np.unravel_index(distance.argmax(), distance.shape)
        points.append((int(zone), int(y), int(x)))
    return points

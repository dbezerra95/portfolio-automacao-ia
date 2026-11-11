"""Mapas PNG para inspeção do resultado."""
import numpy as np
from PIL import Image, ImageDraw, ImageFont


def render(rgb: np.ndarray, index: np.ndarray, zones: np.ndarray, points: list[tuple[int, int, int]], out: str, years: list[int]) -> None:
    colors = np.array([[210, 60, 45], [235, 181, 55], [45, 145, 80], [74, 120, 195], [170, 80, 180]], dtype=np.uint8)
    font = ImageFont.truetype("DejaVuSans.ttf", 19)
    label_font = ImageFont.truetype("DejaVuSans-Bold.ttf", 25)
    overlay = rgb.copy().astype(float)
    for zone in np.unique(zones[zones > 0]):
        mask = zones == zone
        overlay[mask] = 0.4 * overlay[mask] + 0.6 * colors[(zone - 1) % len(colors)]
    image = Image.fromarray(overlay.astype(np.uint8)).resize((1000, 1000), Image.Resampling.NEAREST)
    draw = ImageDraw.Draw(image)
    for zone, y, x in points:
        px, py = (x + 0.5) * 1000 / zones.shape[1], (y + 0.5) * 1000 / zones.shape[0]
        draw.ellipse((px - 7, py - 7, px + 7, py + 7), fill="black", outline="white", width=2)
        draw.text((px + 10, py - 17), f"Z{zone}", font=label_font, fill="black", stroke_width=3, stroke_fill="white")
    labels = np.unique(zones[zones > 0])
    draw.rectangle((12, 12, 205, 24 + 30 * len(labels)), fill="white", outline="black")
    for i, zone in enumerate(labels):
        y = 20 + 30 * i
        draw.rectangle((22, y, 39, y + 17), fill=tuple(colors[(zone - 1) % len(colors)]))
        pct = 100 * np.count_nonzero(zones == zone) / np.count_nonzero(zones)
        draw.text((48, y - 3), f"Z{zone}: {pct:.1f}%", fill="black", font=font)
    caption = f"Sentinel-2 L2A, safras {min(years)}-{max(years)}, área pública de demonstração"
    draw.rectangle((0, 965, 1000, 1000), fill="white")
    draw.text((12, 972), caption, fill="black", font=font)
    image.save(f"{out}/zonas.png", optimize=True)

    values = index[(zones > 0) & np.isfinite(index)]
    lo, hi = np.percentile(values, [2, 98])
    # Escala simétrica mantém 1,0 na cor central e destaca diferenças relativas.
    span = max(1 - lo, hi - 1, 1e-6)
    t = np.clip((np.nan_to_num(index, nan=1) - 1) / (2 * span) + 0.5, 0, 1)
    palette = np.array([[180, 35, 35], [245, 245, 220], [35, 135, 70]])
    lower = np.minimum((t * 2).astype(int), 1)
    fraction = (t * 2 - lower)[..., None]
    mapped = (palette[lower] * (1 - fraction) + palette[lower + 1] * fraction).astype(np.uint8)
    mapped[zones == 0] = 85
    image = Image.fromarray(mapped).resize((1000, 1000), Image.Resampling.NEAREST)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 925, 1000, 1000), fill="white")
    for x in range(300, 700):
        v = x - 300
        i = min(v // 200, 1)
        f = (v - i * 200) / 200
        draw.line((x, 935, x, 951), fill=tuple((palette[i] * (1 - f) + palette[i + 1] * f).astype(int)))
    draw.text((12, 960), "abaixo da mediana do talhão", fill="black", font=font)
    draw.text((705, 960), "acima", fill="black", font=font)
    draw.text((488, 955), "1,0", fill="black", font=font)
    image.save(f"{out}/ndvi_relativo.png", optimize=True)

"""Static raster map image generation from GPS track data.

Tiles are read from the on-disk cache (app/core/tile_cache) populated by the
interactive map view.  When a tile is missing it is fetched directly from
Google Maps and written to the cache so future calls (and the live map) can
reuse it.
"""
from __future__ import annotations

import math
import os
import urllib.request
from io import BytesIO
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from app.core.tile_cache import get_cache_dir

TILE_SIZE = 256
_SUBDOMAINS = ("mt0", "mt1", "mt2", "mt3")
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124"
)

# RGBA drawing colours
_TRACK = (255, 120, 30, 240)
_START = (40, 210, 70, 255)
_END   = (210, 30,  30, 255)
_PHOTO = (255, 210,  0, 210)
_WIND  = (255, 240,  50, 245)
_WHITE = (255, 255, 255, 255)
_BLACK = (  0,   0,   0, 200)


def _tile_xy(lat: float, lon: float, zoom: int) -> tuple[int, int]:
    lat_r = math.radians(lat)
    n = 2 ** zoom
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.log(math.tan(lat_r) + 1.0 / math.cos(lat_r)) / math.pi) / 2.0 * n)
    return x, y


def _global_px(lat: float, lon: float, zoom: int) -> tuple[float, float]:
    lat_r = math.radians(lat)
    n = 2 ** zoom
    xf = (lon + 180.0) / 360.0 * n * TILE_SIZE
    yf = (1.0 - math.log(math.tan(lat_r) + 1.0 / math.cos(lat_r)) / math.pi) / 2.0 * n * TILE_SIZE
    return xf, yf


def _choose_zoom(lat_min: float, lat_max: float, lon_min: float, lon_max: float,
                 target_px: int) -> int:
    """Largest zoom level where the bbox fits within *target_px* on the long side."""
    for zoom in range(19, 3, -1):
        tx0, ty0 = _tile_xy(lat_max, lon_min, zoom)
        tx1, ty1 = _tile_xy(lat_min, lon_max, zoom)
        w = (tx1 - tx0 + 1) * TILE_SIZE
        h = (ty1 - ty0 + 1) * TILE_SIZE
        if max(w, h) <= target_px:
            return zoom
    return 4


def _get_tile(lyrs: str, z: int, x: int, y: int) -> Optional[Image.Image]:
    """Return tile image from disk cache; fetch from Google Maps if absent."""
    cache_path = get_cache_dir() / lyrs / str(z) / str(x) / f"{y}.png"
    if cache_path.exists():
        try:
            return Image.open(cache_path).convert("RGBA")
        except Exception:
            pass
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    sd = _SUBDOMAINS[(x + y) % 4]
    url = f"https://{sd}.google.com/vt/lyrs={lyrs}&x={x}&y={y}&z={z}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = r.read()
        cache_path.write_bytes(data)
        return Image.open(BytesIO(data)).convert("RGBA")
    except Exception:
        return None


def _load_font(size: int = 13) -> ImageFont.ImageFont:
    """Try Windows Arial, fall back to PIL default."""
    candidates = [
        os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts", "arial.ttf"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()


def _wind_dir_from(vwn: float, vwe: float) -> tuple[float, str]:
    """Return (degrees_from, compass_label) for wind vector (VWN, VWE)."""
    dir_from = (math.degrees(math.atan2(vwe, vwn)) + 180) % 360
    compass = ["С", "СВ", "В", "ЮВ", "Ю", "ЮЗ", "З", "СЗ"]
    cp = compass[int((dir_from + 22.5) % 360 // 45)]
    return dir_from, cp


def _draw_wind_info_box(
    canvas: Image.Image,
    wind_points: list,
) -> None:
    """Draw average wind speed + direction info box in top-right corner.

    Averages VWN/VWE across all provided wind_points so the box always
    shows a representative value regardless of how many arrows are drawn.
    Font is large so the text stays readable when scaled to ~500 px in PDF.
    """
    if not wind_points:
        return
    vwn_avg = sum(wp[2] for wp in wind_points) / len(wind_points)
    vwe_avg = sum(wp[3] for wp in wind_points) / len(wind_points)
    speed = math.hypot(vwn_avg, vwe_avg)
    if speed < 0.05:
        return

    dir_from, cp = _wind_dir_from(vwn_avg, vwe_avg)
    lines = [
        f"Фактический ветер: {speed:.1f} м/с",
        f"Направл.: {cp}  ({dir_from:.0f}°)",
    ]

    big_font = _load_font(28)
    draw = ImageDraw.Draw(canvas)

    pad = 14
    line_boxes = [draw.textbbox((0, 0), l, font=big_font) for l in lines]
    text_w = max(b[2] - b[0] for b in line_boxes)
    line_h = max(b[3] - b[1] for b in line_boxes) + 6

    box_w = text_w + pad * 2
    box_h = line_h * len(lines) + pad * 2
    img_w, img_h = canvas.size
    x0 = img_w - box_w - 12
    y0 = 12

    draw.rectangle((x0 - 2, y0 - 2, x0 + box_w + 2, y0 + box_h + 2),
                   fill=(0, 0, 0, 200))
    for i, (line, bbox) in enumerate(zip(lines, line_boxes)):
        draw.text((x0 + pad, y0 + pad + i * line_h), line,
                  fill=_WIND, font=big_font)


def _draw_wind_arrow(
    draw: ImageDraw.Draw,
    cx: float, cy: float,
    vwn: float, vwe: float,
    label: str = "",
    length: int = 60,
    font: Optional[ImageFont.ImageFont] = None,
) -> None:
    """Draw a wind-direction arrow (points *to* where wind goes) at (cx, cy)."""
    speed = math.hypot(vwn, vwe)
    if speed < 0.05:
        return
    angle = math.atan2(vwe, vwn)          # radians from north
    dx = math.sin(angle) * length
    dy = -math.cos(angle) * length
    x0, y0 = int(cx), int(cy)
    x1, y1 = int(cx + dx), int(cy + dy)

    # Shadow then colour
    for col, w in ((_BLACK, 5), (_WIND, 3)):
        draw.line([(x0, y0), (x1, y1)], fill=col, width=w)

    head = 15
    for off in (math.radians(145), math.radians(-145)):
        ba = angle + off
        hx = int(x1 + math.sin(ba) * head)
        hy = int(y1 - math.cos(ba) * head)
        ax, ay = int(cx + dx * 0.9), int(cy + dy * 0.9)
        for col, w in ((_BLACK, 5), (_WIND, 3)):
            draw.line([(ax, ay), (hx, hy)], fill=col, width=w)

    text = f"{label}: {speed:.1f} м/с" if label else f"{speed:.1f} м/с"
    tx, ty = x1 + 7, y1 - 12
    for ddx, ddy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
        draw.text((tx + ddx, ty + ddy), text, fill=_BLACK, font=font)
    draw.text((tx, ty), text, fill=_WHITE, font=font)


def render_map(
    track: list[tuple[float, float, float]],
    photos: Optional[list[tuple[float, float, float, str]]] = None,
    wind_points: Optional[list[tuple[float, float, float, float, str]]] = None,
    lyrs: str = "s",
    padding_frac: float = 0.15,
    target_px: int = 900,
    zoom_override: Optional[int] = None,
) -> Optional[Image.Image]:
    """
    Render a static satellite map with GPS track overlay.

    Parameters
    ----------
    track       : [(lat, lon, alt_m), ...]
    photos      : [(lat, lon, alt_m, label), ...] – yellow dots
    wind_points : [(lat, lon, vwn, vwe, label), ...] – wind arrows
    lyrs        : Google Maps layer code: 's'=satellite, 'y'=hybrid, 'm'=road
    padding_frac: fraction of bbox size added as padding on each side
    target_px   : largest acceptable canvas dimension before choosing lower zoom
    zoom_override: force a specific zoom level

    Returns
    -------
    PIL Image (RGB) or None if rendering is not possible.
    """
    if len(track) < 2:
        return None

    lats = [p[0] for p in track]
    lons = [p[1] for p in track]
    lat_min, lat_max = min(lats), max(lats)
    lon_min, lon_max = min(lons), max(lons)

    lat_span = max(lat_max - lat_min, 1e-4)
    lon_span = max(lon_max - lon_min, 1e-4)
    lat_pad = lat_span * padding_frac
    lon_pad = lon_span * padding_frac
    lat_min -= lat_pad; lat_max += lat_pad
    lon_min -= lon_pad; lon_max += lon_pad

    zoom = (
        zoom_override
        if zoom_override is not None
        else _choose_zoom(lat_min, lat_max, lon_min, lon_max, target_px)
    )

    tx0, ty0 = _tile_xy(lat_max, lon_min, zoom)
    tx1, ty1 = _tile_xy(lat_min, lon_max, zoom)
    canvas_w = (tx1 - tx0 + 1) * TILE_SIZE
    canvas_h = (ty1 - ty0 + 1) * TILE_SIZE

    canvas = Image.new("RGBA", (canvas_w, canvas_h), (65, 65, 65, 255))
    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            tile = _get_tile(lyrs, zoom, tx, ty)
            if tile:
                canvas.paste(tile, ((tx - tx0) * TILE_SIZE, (ty - ty0) * TILE_SIZE))

    orig_x = tx0 * TILE_SIZE
    orig_y = ty0 * TILE_SIZE

    def cv(lat: float, lon: float) -> tuple[int, int]:
        gx, gy = _global_px(lat, lon, zoom)
        return int(gx - orig_x), int(gy - orig_y)

    draw = ImageDraw.Draw(canvas)
    font = _load_font(13)

    # GPS track polyline (shadow + colour)
    pts = [cv(la, lo) for la, lo, _ in track]
    if len(pts) > 1:
        draw.line(pts, fill=(0, 0, 0, 150), width=5)
        draw.line(pts, fill=_TRACK, width=3)

    # Photo markers
    if photos:
        for la, lo, _al, _lbl in photos:
            cx, cy = cv(la, lo)
            r = 5
            draw.ellipse((cx - r, cy - r, cx + r, cy + r),
                         fill=_PHOTO, outline=(160, 120, 0, 200), width=1)

    # Start (green) / End (red) markers – drawn on top of track
    if pts:
        for (mx, my), col in ((pts[0], _START), (pts[-1], _END)):
            r = 10
            draw.ellipse((mx - r, my - r, mx + r, my + r),
                         fill=col, outline=_WHITE, width=2)

    # Wind direction arrows
    if wind_points:
        for la, lo, vwn, vwe, lbl in wind_points:
            _draw_wind_arrow(draw, *cv(la, lo), vwn, vwe, lbl, font=font)

    # Crop to padded bounding box
    clx, cty = cv(lat_max, lon_min)
    crx, cby = cv(lat_min, lon_max)
    clx = max(0, clx); cty = max(0, cty)
    crx = min(canvas_w - 1, crx)
    cby = min(canvas_h - 1, cby)
    if crx > clx and cby > cty:
        canvas = canvas.crop((clx, cty, crx, cby))

    # Wind info box drawn after crop so it is always in the corner of the final image
    if wind_points:
        _draw_wind_info_box(canvas, wind_points)

    return canvas.convert("RGB")

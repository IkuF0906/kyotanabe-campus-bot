"""地図の描画（Leaflet + OpenStreetMap、無料・APIキー不要）。"""

import folium

from . import services as sv


def _label(text, color, lift=14):
    """lift: 点からラベルを上にずらす量(px)。ピンの上に出すときは大きくする。"""
    return folium.DivIcon(
        icon_size=(0, 0),
        html=f'<div style="transform:translate(-50%,calc(-100% - {lift}px));width:max-content;white-space:nowrap;font:500 13px Noto Sans JP,sans-serif;'
        f"color:#fff;background:{color};padding:2px 6px;border-radius:4px;"
        f'box-shadow:0 1px 2px rgba(0,0,0,.15)">{text}</div>',
    )


def make_map(targets, origin=None):
    """targets: 目的地（強調色）、origin: 出発地（濃いグレー）。他の建物と駅は薄く表示する。"""
    m = folium.Map(tiles="OpenStreetMap", zoom_control=True, scrollWheelZoom=False)
    highlighted = {p["id"] for p in targets} | ({origin["id"]} if origin else set())

    for b in sv.BUILDINGS.values():  # 他の建物: 灰色の点（ホバーで名前）
        if b["id"] not in highlighted:
            folium.CircleMarker(
                [b["lat"], b["lng"]], radius=5, color="#666", fill=True, fill_opacity=0.6, tooltip=b["name"]
            ).add_to(m)
    for s in sv.STATIONS.values():  # 駅: 常に名前を表示
        if s["id"] not in highlighted:
            folium.Marker([s["lat"], s["lng"]], icon=_label(s["name"], "#525252")).add_to(m)
            folium.CircleMarker([s["lat"], s["lng"]], radius=5, color="#525252", fill=True).add_to(m)

    if origin:
        folium.Marker([origin["lat"], origin["lng"]], icon=folium.Icon(color="black", icon="user", prefix="fa")).add_to(
            m
        )
        folium.Marker(
            [origin["lat"], origin["lng"]], icon=_label(f"今ここ（推定）{origin['name']}", "#404040", lift=44)
        ).add_to(m)
    for p in targets:
        folium.Marker([p["lat"], p["lng"]], icon=folium.Icon(color="darkpurple", icon="flag", prefix="fa")).add_to(m)
        folium.Marker([p["lat"], p["lng"]], icon=_label(p["name"], "#550071", lift=44)).add_to(m)

    # 目的地（と出発地）が収まるように表示範囲を合わせる
    pts = [[p["lat"], p["lng"]] for p in targets] + ([[origin["lat"], origin["lng"]]] if origin else [])
    if len(pts) == 1:
        m.location, m.options["zoom"] = pts[0], 16
    else:
        m.fit_bounds(pts, padding=(40, 40), max_zoom=17)
    return m.get_root().render()

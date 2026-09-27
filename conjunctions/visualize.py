"""Visualisation 3D interactive des résultats, en fichiers HTML (plotly).

Les positions sont tracées dans le repère TEME de SGP4 (axes fixes par rapport
aux étoiles). La Terre est dessinée avec ses méridiens et parallèles tournés
comme elle l'est à l'instant représenté.
"""

import json
import math
from datetime import datetime
from functools import cache
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from sgp4.api import SatrecArray
from sgp4.propagation import gstime

from .catalog import SpaceObject
from .fetch import fetch_coastlines
from .propagate import julian_date, propagate_catalog

# Couleurs sur fond sombre : les 3 premières teintes de la palette catégorielle
# de référence (distinguables deux à deux, y compris par les daltoniens),
# et une couleur "alerte" réservée aux rapprochements.
COLORS = {"Starlink": "#3987e5", "satellite": "#d95926", "débris": "#199e70"}
OBJECT_COLORS = ("#3987e5", "#d95926")  # vue d'un rapprochement : objet 1, objet 2
ALERT_COLOR = "#d03b3b"
BACKGROUND = "#1a1a19"
EARTH_COLOR = "#383835"
GRID_COLOR = "#52514e"
COAST_COLOR = "#898781"
TEXT_COLOR = "#c3c2b7"

EARTH_MEAN_RADIUS_KM = 6371.0

# Objets remarquables mis en évidence dans la vue d'ensemble : numéro NORAD -> nom affiché.
# (Les modules et vaisseaux amarrés aux stations partagent leur position : on n'en montre qu'un.)
NOTABLE_OBJECTS = {
    "25544": "ISS",
    "48274": "Tiangong",  # station spatiale chinoise
    "20580": "Hubble",
}
NOTABLE_COLOR = "#ffffff"


def earth_traces(t: datetime) -> list:
    """La Terre (sphère), ses méridiens / parallèles tous les 30° et ses côtes, orientés à l'instant t."""
    lon, lat = np.meshgrid(np.linspace(0, 2 * np.pi, 73), np.linspace(-np.pi / 2, np.pi / 2, 37))
    R = EARTH_MEAN_RADIUS_KM
    sphere = go.Surface(
        x=R * np.cos(lat) * np.cos(lon), y=R * np.cos(lat) * np.sin(lon), z=R * np.sin(lat),
        colorscale=[[0, EARTH_COLOR], [1, EARTH_COLOR]], showscale=False, hoverinfo="skip",
    )

    # Les lignes sont tournées de l'angle de rotation de la Terre (voir propagate.teme_to_geodetic)
    theta = gstime(sum(julian_date(t)))
    graticule = [(np.full(181, la), np.linspace(0, 360, 181)) for la in range(-60, 61, 30)]  # parallèles
    graticule += [(np.linspace(-90, 90, 91), np.full(91, lo)) for lo in range(0, 360, 30)]  # méridiens
    return [
        sphere,
        lines_on_sphere(graticule, theta, GRID_COLOR, width=1),
        lines_on_sphere(load_coastlines(), theta, COAST_COLOR, width=2),
    ]


def lines_on_sphere(lines: list[tuple[np.ndarray, np.ndarray]], theta: float,
                    color: str, width: int) -> go.Scatter3d:
    """Dessine des lignes (latitudes, longitudes en degrés) à la surface de la Terre.

    theta : angle de rotation de la Terre à l'instant représenté (radians).
    """
    r = EARTH_MEAN_RADIUS_KM * 1.002  # juste au-dessus de la surface pour rester visible
    xs, ys, zs = [], [], []
    for line_lat, line_lon in lines:
        la, lo = np.radians(line_lat), np.radians(line_lon) + theta
        xs += [*(r * np.cos(la) * np.cos(lo)), None]  # None = "lever le crayon" entre deux lignes
        ys += [*(r * np.cos(la) * np.sin(lo)), None]
        zs += [*(r * np.sin(la)), None]
    return go.Scatter3d(x=xs, y=ys, z=zs, mode="lines", line={"color": color, "width": width},
                        hoverinfo="skip", showlegend=False)


@cache
def load_coastlines() -> list[tuple[np.ndarray, np.ndarray]]:
    """Côtes des continents, sous forme de lignes (latitudes, longitudes) en degrés.

    Dans le GeoJSON, chaque ligne de côte est une liste de points [longitude, latitude].
    @cache : le fichier n'est lu qu'une fois, même si on dessine plusieurs Terres.
    """
    features = json.loads(fetch_coastlines().read_text(encoding="utf-8"))["features"]
    lines = []
    for feature in features:
        geometry = feature["geometry"]
        parts = [geometry["coordinates"]] if geometry["type"] == "LineString" else geometry["coordinates"]
        for points in parts:
            lon, lat = np.array(points).T
            lines.append((lat, lon))
    return lines


def save_html(fig: go.Figure, path: Path) -> None:
    """Enregistre la figure en page HTML plein écran, sur fond sombre.

    La librairie plotly est incluse dans le fichier : la page s'ouvre hors ligne.
    """
    html = fig.to_html(full_html=True, default_width="100%", default_height="100vh")
    html = html.replace("<body>", f'<body style="margin:0;background:{BACKGROUND}">', 1)
    path.write_text(html, encoding="utf-8")


def hidden_axes_scene() -> dict:
    """Scène 3D sans axes, à l'échelle réelle (1 km = 1 km dans les trois directions)."""
    hidden = {"visible": False}
    return {"xaxis": hidden, "yaxis": hidden, "zaxis": hidden, "aspectmode": "data", "bgcolor": BACKGROUND}


def camera_facing(positions: np.ndarray, objects: list[SpaceObject], norad_id: str,
                  distance: float = 1.4) -> dict:
    """Position de la caméra pour que l'objet `norad_id` soit face à nous (près du centre de la vue).

    On place l'œil dans la direction de l'objet vu depuis le centre de la Terre, légèrement
    décalée vers le nord : sans ce décalage, l'épingle de l'objet pointerait droit sur nous
    et serait invisible. `distance` est exprimée dans l'unité de plotly (relative à la scène).
    """
    k = next((k for k, obj in enumerate(objects) if obj.norad_id == norad_id), None)
    if k is None or np.isnan(positions[k]).any():
        return {"x": 0.9, "y": 0.9, "z": 0.5}  # vue par défaut si l'objet est absent
    direction = positions[k] / np.linalg.norm(positions[k]) + np.array([0.0, 0.0, 0.5])
    direction /= np.linalg.norm(direction)
    return dict(zip("xyz", (distance * direction).tolist()))


def add_notable_objects(fig: go.Figure, objects: list[SpaceObject], positions: np.ndarray,
                        errors: np.ndarray, start: datetime) -> None:
    """Met en évidence les objets de NOTABLE_OBJECTS : orbite, point, et nom au bout d'une "épingle".

    L'épingle est un trait qui part de l'objet vers l'extérieur : le nom est ainsi
    écrit hors du nuage dense de satellites, où il resterait illisible.
    """
    for k, obj in enumerate(objects):
        if obj.norad_id not in NOTABLE_OBJECTS or errors[k] != 0:
            continue
        name = NOTABLE_OBJECTS[obj.norad_id]
        position = positions[k]
        # Bout de l'épingle : au-delà de la coquille de satellites (~1,3 rayon terrestre)
        tip = position / np.linalg.norm(position) * EARTH_MEAN_RADIUS_KM * 1.6

        # Un tour complet d'orbite à partir de l'instant représenté
        period_s = 2 * math.pi / obj.satrec.no_kozai * 60
        orbit, _, _ = propagate_catalog(SatrecArray([obj.satrec]), start, np.linspace(0, period_s, 300))
        fig.add_trace(go.Scatter3d(
            x=orbit[0, :, 0], y=orbit[0, :, 1], z=orbit[0, :, 2], mode="lines",
            line={"color": NOTABLE_COLOR, "width": 2}, opacity=0.6,
            legendgroup=name, name=name, hoverinfo="skip",
        ))
        fig.add_trace(go.Scatter3d(  # l'épingle, de l'objet vers l'extérieur
            x=[position[0], tip[0]], y=[position[1], tip[1]], z=[position[2], tip[2]], mode="lines",
            line={"color": NOTABLE_COLOR, "width": 4}, legendgroup=name, showlegend=False, hoverinfo="skip",
        ))
        fig.add_trace(go.Scatter3d(  # l'objet lui-même
            x=[position[0]], y=[position[1]], z=[position[2]], mode="markers",
            marker={"size": 9, "color": NOTABLE_COLOR, "line": {"color": BACKGROUND, "width": 2}},
            legendgroup=name, showlegend=False, text=[name], hovertemplate="%{text}<extra></extra>",
        ))
        fig.add_trace(go.Scatter3d(  # le nom, au bout de l'épingle
            x=[tip[0]], y=[tip[1]], z=[tip[2]], mode="text", text=[f"<b>{name}</b>"],
            textposition="top center", textfont={"color": NOTABLE_COLOR, "size": 20},
            legendgroup=name, showlegend=False, hoverinfo="skip",
        ))


def plot_overview(objects: list[SpaceObject], start: datetime, events: pd.DataFrame,
                  path: Path, n_events: int = 20) -> None:
    """Tous les objets à l'instant `start`, et le lieu des rapprochements les plus proches."""
    r, _, errors = propagate_catalog(SatrecArray([obj.satrec for obj in objects]), start, np.array([0.0]))
    positions = r[:, 0, :]

    fig = go.Figure(earth_traces(start))
    for kind, color in COLORS.items():
        idx = [k for k, obj in enumerate(objects) if obj.kind == kind and errors[k, 0] == 0]
        fig.add_trace(go.Scatter3d(
            x=positions[idx, 0], y=positions[idx, 1], z=positions[idx, 2],
            mode="markers", marker={"size": 1.5, "color": color}, opacity=0.8,
            name=f"{kind} ({len(idx)})",
            text=[objects[k].name for k in idx], hovertemplate="%{text}<extra></extra>",
        ))

    add_notable_objects(fig, objects, positions, errors[:, 0], start)

    # Lieu de chaque rapprochement, à son propre instant (TCA)
    by_norad = {obj.norad_id: obj for obj in objects}
    top = events.head(n_events)
    points, labels = [], []
    for row in top.itertuples():
        _, r_tca, _ = by_norad[row.norad_1].satrec.sgp4(*julian_date(row.tca_utc))
        points.append(r_tca)
        labels.append(f"{row.object_1} / {row.object_2}<br>{row.miss_distance_km * 1000:.0f} m à "
                      f"{row.relative_speed_km_s:.1f} km/s<br>TCA {row.tca_utc:%d/%m %H:%M:%S} UTC")
    if points:
        points = np.array(points)
        fig.add_trace(go.Scatter3d(
            x=points[:, 0], y=points[:, 1], z=points[:, 2], mode="markers",
            marker={"size": 5, "color": ALERT_COLOR, "symbol": "diamond"},
            name=f"{len(points)} rapprochements les plus proches (lieu au TCA)",
            text=labels, hovertemplate="%{text}<extra></extra>",
        ))

    fig.update_layout(
        title=f"{len(objects)} objets en orbite basse le {start:%d/%m/%Y à %H:%M} UTC",
        paper_bgcolor=BACKGROUND, font={"color": TEXT_COLOR},
        scene={**hidden_axes_scene(), "camera": {"eye": camera_facing(positions, objects, "25544")}},
        legend={"itemsizing": "constant", "x": 0.01, "y": 0.95, "bgcolor": "rgba(26,26,25,0.7)"},
        margin={"l": 0, "r": 0, "t": 50, "b": 0},
    )
    save_html(fig, path)


def plot_event(objects: list[SpaceObject], event: pd.Series, path: Path) -> None:
    """Zoom sur un rapprochement : les deux orbites, et la géométrie du croisement vue de près."""
    by_norad = {obj.norad_id: obj for obj in objects}
    a, b = by_norad[event["norad_1"]], by_norad[event["norad_2"]]
    tca = event["tca_utc"].to_pydatetime()
    satrecs = SatrecArray([a.satrec, b.satrec])

    # Gauche : un tour complet de chaque orbite, centré sur le TCA
    period_s = 2 * math.pi / min(a.satrec.no_kozai, b.satrec.no_kozai) * 60  # no_kozai : radians/minute
    t_orbit = np.linspace(-period_s / 2, period_s / 2, 400)
    r_orbit, _, _ = propagate_catalog(satrecs, tca, t_orbit)

    # Droite : quelques instants autour du TCA, positions exprimées par rapport au milieu des deux
    # objets au TCA. La fenêtre est choisie pour que chaque objet parcoure ~10 fois la distance
    # minimale : le segment de distance minimale reste ainsi visible (entre 0,01 s et 1 s).
    half_window_s = float(np.clip(10 * event["miss_distance_km"] / event["relative_speed_km_s"], 0.01, 1.0))
    t_close = np.linspace(-half_window_s, half_window_s, 201)  # l'indice 100 correspond au TCA
    r_close, _, _ = propagate_catalog(satrecs, tca, t_close)
    center = (r_close[0, 100] + r_close[1, 100]) / 2
    local = r_close - center

    fig = make_subplots(
        rows=1, cols=2, specs=[[{"type": "scene"}, {"type": "scene"}]],
        subplot_titles=("Les deux orbites (un tour)",
                        f"Vue rapprochée : ±{half_window_s:.2f} s autour du TCA (km)"),
    )
    for trace in earth_traces(tca):
        fig.add_trace(trace, row=1, col=1)

    for k, (obj, color) in enumerate(zip((a, b), OBJECT_COLORS)):
        label = f"{obj.name} ({obj.norad_id}, {obj.kind})"
        fig.add_trace(go.Scatter3d(
            x=r_orbit[k, :, 0], y=r_orbit[k, :, 1], z=r_orbit[k, :, 2], mode="lines",
            line={"color": color, "width": 3}, name=label, legendgroup=label, hoverinfo="skip",
        ), row=1, col=1)
        fig.add_trace(go.Scatter3d(
            x=local[k, :, 0], y=local[k, :, 1], z=local[k, :, 2], mode="lines",
            line={"color": color, "width": 5}, legendgroup=label, showlegend=False,
            customdata=t_close, hovertemplate=f"{obj.name}<br>t = %{{customdata:+.2f}} s<extra></extra>",
        ), row=1, col=2)
        # Point de départ de la fenêtre pour montrer le sens du déplacement
        fig.add_trace(go.Scatter3d(
            x=[local[k, 0, 0]], y=[local[k, 0, 1]], z=[local[k, 0, 2]], mode="markers+text",
            marker={"size": 4, "color": color}, text=["départ"], textfont={"color": TEXT_COLOR},
            legendgroup=label, showlegend=False, hoverinfo="skip",
        ), row=1, col=2)

    # Le point de croisement (à gauche) et le segment de distance minimale (à droite)
    crossing = r_orbit[0, np.argmin(np.abs(t_orbit))]
    fig.add_trace(go.Scatter3d(
        x=[crossing[0]], y=[crossing[1]], z=[crossing[2]], mode="markers",
        marker={"size": 6, "color": ALERT_COLOR, "symbol": "diamond"},
        name="Point de rapprochement", hoverinfo="skip",
    ), row=1, col=1)
    miss = local[:, 100]
    fig.add_trace(go.Scatter3d(
        x=miss[:, 0], y=miss[:, 1], z=miss[:, 2], mode="lines+markers",
        line={"color": ALERT_COLOR, "width": 6}, marker={"size": 4, "color": ALERT_COLOR},
        name=f"Distance minimale : {event['miss_distance_km'] * 1000:.0f} m", hoverinfo="skip",
    ), row=1, col=2)

    km_axis = {"title": "km", "color": TEXT_COLOR, "gridcolor": GRID_COLOR, "backgroundcolor": BACKGROUND}
    fig.update_layout(
        title=(f"{a.name} / {b.name} : {event['miss_distance_km'] * 1000:.0f} m à "
               f"{event['relative_speed_km_s']:.2f} km/s, TCA {tca:%d/%m/%Y %H:%M:%S} UTC "
               f"(TLE âgé de {event['tle_age_days']:.1f} j)"),
        paper_bgcolor=BACKGROUND, font={"color": TEXT_COLOR},
        scene=hidden_axes_scene(),
        scene2={"xaxis": km_axis, "yaxis": km_axis, "zaxis": km_axis,
                "aspectmode": "data", "bgcolor": BACKGROUND},
        legend={"orientation": "h", "y": -0.05}, margin={"l": 0, "r": 40, "t": 80, "b": 40},
    )
    save_html(fig, path)

"""Data and copy checks behind the DEPORT UI: vehicle icons, real Coimbatore coordinates, cached road
geometry for every route, and no old product name or jargon in what users read."""
import ast
import re
from pathlib import Path

import pytest

from modules import geometry, live_map, store, ui
from modules.data_loader import load_all, load_branches, load_partners, load_places

ROOT = Path(__file__).resolve().parent.parent
UI_FILES = [ROOT / "app.py", *sorted((ROOT / "views").rglob("*.py")),
            *(ROOT / "modules" / name for name in ("ui.py", "login_ui.py", "manager_ui.py", "report_ui.py", "live_map.py"))]


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("RIPPLE_DB", str(tmp_path / "data.db"))
    store.init_db()


def test_every_partner_has_a_vehicle_type_and_icon(db):
    partners = store.partners_df()
    assert len(partners) == 6
    for p in partners.to_dict("records"):
        assert p["vehicle_type"] in {"bike", "car", "van", "truck"}
        assert ui.VEHICLE_EMOJI[p["vehicle_type"]] and live_map.VEHICLE_EMOJI[p["vehicle_type"]]
        assert ui.VEHICLE_ICON[p["vehicle_type"]].startswith(":material/")
    assert {"bike", "car", "van", "truck"} <= set(load_all()["vehicles"]["type"])   # every kind is in the demo


def test_all_coordinates_are_in_coimbatore():
    data = load_all()
    points = list(zip(data["deliveries"]["lat"], data["deliveries"]["lng"]))
    points += list(zip(data["vehicles"]["current_lat"], data["vehicles"]["current_lng"]))
    points += list(zip(load_places()["lat"], load_places()["lng"]))
    points += list(zip(load_branches()["lat"], load_branches()["lng"]))
    points += [tuple(p) for road in data["roads"]["points"] for p in road]
    points += [tuple(p) for entry in geometry.load_cache_file().values() for p in entry["points"]]
    outside = [p for p in points if not geometry.in_coimbatore(*p)]
    assert len(points) > 500 and outside == []


def test_cached_geometry_covers_every_route(db):
    shapes = store.route_geometry()
    data = load_all()
    for road in data["roads"].itertuples():
        assert len(shapes[f"road:{road.road_id}"]) > len(road.points)          # real streets, not waypoints
    for v in data["vehicles"].itertuples():
        assert geometry.in_coimbatore(*shapes[f"snap:{v.vehicle_id}"][0])
    # every seeded stop sequence (vehicle -> stop 1 -> stop 2 ...) is a cached driving leg
    deliveries = store.deliveries_df()
    for v in store.vehicles_df().itertuples():
        stops = deliveries[deliveries["vehicle_id"] == v.vehicle_id].sort_values("eta_min")
        points = [(v.current_lat, v.current_lng)] + list(zip(stops["lat"], stops["lng"]))
        for a, b in zip(points, points[1:]):
            if geometry.point_key(*a) != geometry.point_key(*b):  # a stop right where the vehicle stands
                assert geometry.leg_key(a, b) in shapes, (v.vehicle_id, a, b)
    assert all(geometry.in_coimbatore(*p) for pts in shapes.values() for p in pts)


def test_map_never_calls_the_network(db, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("the map must read the cache only")

    monkeypatch.setattr(geometry, "_get", no_network)
    html = live_map.build(store.partners_df("CBE-E"), store.deliveries_df(branch_id="CBE-E"), load_all()["roads"],
                          [{"type": "accident", "road_id": "R1", "road_name": "Avinashi Road", "severity": "critical"}],
                          ["R9"], selected="DP102", states={"DP102": "critical"}).get_root().render()
    assert "DP102 · Karthik · 🏍️ · Critical" in html


def _ui_strings(path):
    """String constants a user can see: everything except docstrings."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = {id(node.body[0].value) for node in ast.walk(tree)
                  if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)) and node.body
                  and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)}
    return [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and id(n) not in docstrings]


def test_no_old_product_name_in_the_ui():
    old_name = re.compile(r"\b(Ripple|RIPPLE)\b(?! Impact)")  # 'Ripple Impact' is a feature name
    found = {f"{path.relative_to(ROOT)}: {text[:60]!r}" for path in UI_FILES for text in _ui_strings(path)
             if old_name.search(text)}
    found |= {str(p.relative_to(ROOT)) for p in (ROOT / "assets").glob("*.svg")
              if old_name.search(p.read_text(encoding="utf-8"))}
    assert found == set()
    assert ui.APP_NAME == "DEPORT" and ui.TAGLINE == "From Disruption to Decision."


def test_no_jargon_in_the_ui():
    jargon = re.compile(r"\b(payload|JSON|cascade|node)\b", re.IGNORECASE)
    found = {f"{path.relative_to(ROOT)}: {text[:60]!r}" for path in UI_FILES for text in _ui_strings(path)
             if jargon.search(text) and not text.startswith(("<style>", "\n<style>"))}
    assert found == set()


def test_demo_partners_are_spread_over_branches():
    partners = load_partners()
    assert set(partners["branch_id"]) == {"CBE-E", "CBE-C", "CBE-S"}

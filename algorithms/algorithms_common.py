from __future__ import annotations
from typing import List, Tuple, Dict, Any, Optional, Literal
from tkinter import messagebox
from models import ModelParams
import random, math, re
import networkx as nx

Individual = List[Dict]

directions = ["top", "right", "bottom", "left"]
vertical_sides = {"right", "left"}
horizontal_sides = {"top", "bottom"}

opposite = {
    "top": "bottom",
    "bottom": "top",
    "left": "right",
    "right": "left"
}

def is_rotated(a, b):
    return b != a and b != opposite[a]

def _normalize_name(s: str) -> str:
    return s.strip().lower().replace(" ", "_")

def _to_number(x):
        if x is None: return None
        if isinstance(x, (int, float)): return float(x)
        s = str(x).strip().replace(",", ".")
        m = re.search(r"-?\d+(?:\.\d+)?", s)
        return float(m.group()) if m else None

def _bbox(x, y, w, d): return (x, y, x + w, y + d)

def _ordered_sides(box, cw, cd ):
    xmin, ymin, xmax, ymax = box
    dists = [
        ("top", abs(ymin - 0.0)),
        ("right", abs(cw - xmax)),
        ("bottom", abs(cd - ymax)),
        ("left", abs(xmin - 0.0)),
    ]
    dists.sort(key=lambda kv: kv[1])
    return [side for side, _ in dists]

def _clamp_layout(indiv: Individual, room_w: float, room_h: float) -> None:
    """It keeps the furniture in the room."""
    for p in indiv:
        p["x"] = max(0.0, min(p["x"], room_w - p["w"]))
        p["y"] = max(0.0, min(p["y"], room_h - p["d"]))
        if p["reserved_w"] > 0: reserved_zone(p, room_w, room_h)

def _clip_in_room_xy(x: float, y: float, w: float, d: float,
                     room_w: float, room_h: float, margin: float = 0.0) -> Tuple[float, float]:
    x = min(max(margin, x), max(margin, room_w - w - margin))
    y = min(max(margin, y), max(margin, room_h - d - margin))
    return x, y

def overlap_area(b1, b2) -> float:
    l1, t1, r1, b1b = b1
    l2, t2, r2, b2b = b2
    dx = max(0.0, min(r1, r2) - max(l1, l2))
    dy = max(0.0, min(b1b, b2b) - max(t1, t2))
    return dx * dy

def build_structure_graph(components):
    G = nx.DiGraph()

    for item in components:
        child_name = item.get("Name", item.get("name", ""))
        if child_name == "room":
            G.add_node(child_name)
            continue

        if item.get("Overlaps", item.get("overlaps", "")) == "":
            overlaps = "room"
        else:
            overlaps = item.get("Overlaps", item.get("overlaps", ""))

        G.add_node(child_name)

        if overlaps:
            container_names = [t.strip() for t in overlaps.split(",") if t.strip()]
            for container_name in container_names:
                G.add_node(container_name)
                G.add_edge(container_name, child_name)

    return G

def component_xy(cx, cy, cw, cd, c_direction, relx, rely, relw, reld):
    '''return component"s x, y coordinates and width, height attributes'''
    if   c_direction == "top":    return cx + relx, cy + rely, relw, reld
    elif c_direction == "right":   return cx + cw - rely - reld, cy + relx, reld, relw
    elif c_direction == "bottom": return cx + cw - relx - relw, cy + cd - rely - reld, relw, reld
    elif c_direction == "left":  return cx + rely, cy + cd - relx - relw, reld, relw
    else: return 0, 0, 0, 0

def _to_float(value, default=0.0):
    try:
        return float(str(value).replace(",", "."))
    except Exception:
        return default

def choose_orientation_and_extents(a_w, a_d, w, d, rng):
    """
    Returns: orientation (0 or 90), eff_w, eff_d: the width/depth of the oriented rectangle in container coordinates.
    """
    fits_0  = (w <= a_w) and (d <= a_d)
    fits_90 = (d <= a_w) and (w <= a_d)

    if fits_0 and fits_90:
        orientation = 0 if rng.random() < 0.5 else 90
    elif fits_0:
        orientation = 0
    elif fits_90:
        orientation = 90
    else:
        # if it doesn't fit at all – we choose based on more overlaps
        overlap_0  = min(w, a_w) * min(d, a_d)
        overlap_90 = min(d, a_w) * min(w, a_d)
        orientation = 0 if overlap_0 >= overlap_90 else 90

    if orientation == 0:
        eff_w, eff_d = w, d
    else:
        eff_w, eff_d = d, w

    return orientation, eff_w, eff_d

def _effective_size_for_individual(comp):
    """Returns the effective (w,d) of the component according to the orientation."""
    w = comp["w"]
    d = comp["d"]
    ori = comp.get("orientation", 0) % 180
    if ori == 0:
        return w, d
    else:
        return d, w

def _get_global_center_from_individual(name: str, individual_dict: Dict[str, Dict[str, Any]]):
    """
    Recursively calculates the global center of the component based on the already constructed individual_dict.
    """
    comp = individual_dict[name]
    a_name = comp.get("a_name") or ""

    # If there is no contener -> room or root item
    if a_name == "":
        return comp["x"], comp["y"]

    # the global center and size of the container
    pcx, pcy = _get_global_center_from_individual(a_name, individual_dict)
    parent = individual_dict[a_name]
    pw, pd = _effective_size_for_individual(parent)

    # container global top left corner
    p_left = pcx - pw / 2.0
    p_top  = pcy - pd / 2.0

    # global coordinate of own center:
    cx = p_left + comp["x"]
    cy = p_top  + comp["y"]
    return cx, cy

def random_center_in_container(a_w, a_d, eff_w, eff_d, wall_fit_enable, wall_flag, connection_side, rng, preferred_side=None):
    """
    a_w, a_d: container width/depth
    eff_w, eff_d: component oriented width/depth
    mode: "", "overlaps", "wall"
    wall_flag: component "Wall" attribute: 1 (to wall), 0 (away from walls), -1 (arbitrary)
    connection_side: e.g. "long", if it should connect to a wall with the long side
    x, y: container's local coordinate system center point (0..a_w, 0..a_d)
    """

    # stay inside the container
    min_x = eff_w / 2.0
    max_x = a_w - eff_w / 2.0
    min_y = eff_d / 2.0
    max_y = a_d - eff_d / 2.0

    # If it doesn't fit, put it in the middle.
    if min_x > max_x or min_y > max_y:
        return a_w / 2.0, a_d / 2.0

    # "", "overlaps" mode has no extra condition - in both cases, the only thing that matters is which container it is.
    if not wall_fit_enable:
        x = rng.uniform(min_x, max_x)
        y = rng.uniform(min_y, max_y)
        return x, y

    # "wall" mode – according to wall_flag
    if wall_flag == 1:
        # to lean against the wall
        sides = ["top", "right", "bottom", "left"]

        # if it is necessary to connect to the wall with the LONG side
        if connection_side in ("long", "short"):
            # eff_w: horizontal extent, eff_d: vertical
            if eff_w > eff_d:
                # horizontal on the longer side
                if connection_side == "long":
                    # long side on the wall -> horizontal walls
                    sides = ["top", "bottom"]
                else:  # "short"
                    # short side on the wall -> vertical walls
                    sides = ["left", "right"]
            elif eff_d > eff_w:
                # vertical on the longer side
                if connection_side == "long":
                    # long side on the wall -> vertical walls
                    sides = ["left", "right"]
                else:  # "short"
                    # short side on the wall -> horizontal walls
                    sides = ["top", "bottom"]
            else:
                # square – keep all four
                sides = ["top", "right", "bottom", "left"]

        # if preferred_side exists and is compatible with the above, then we use it
        if preferred_side in sides:
            side = preferred_side
        else:
            side = rng.choice(sides)

        if side == "top":
            y = eff_d / 2.0
            x = rng.uniform(min_x, max_x)
        elif side == "bottom":
            y = a_d - eff_d / 2.0
            x = rng.uniform(min_x, max_x)
        elif side == "left":
            x = eff_w / 2.0
            y = rng.uniform(min_y, max_y)
        else:  # "right"
            x = a_w - eff_w / 2.0
            y = rng.uniform(min_y, max_y)
        return x, y

    elif wall_flag == 0:
        # away from walls: draw a "safety strip" from the walls, half the depth of the component
        clearance = eff_d / 2.0
        min_x = max(min_x, clearance + eff_w / 2.0)
        max_x = min(max_x, a_w - clearance - eff_w / 2.0)
        min_y = max(min_y, clearance + eff_d / 2.0)
        max_y = min(max_y, a_d - clearance - eff_d / 2.0)

        # if the kitchen is very small: to the middle
        if min_x > max_x or min_y > max_y:
            return a_w / 2.0, a_d / 2.0

        x = rng.uniform(min_x, max_x)
        y = rng.uniform(min_y, max_y)
        return x, y

    else:  # wall_flag == -1 – same as before
        x = rng.uniform(min_x, max_x)
        y = rng.uniform(min_y, max_y)
        return x, y

def compute_reserved_zone(component, bbox, preferred_side=None):
    """
    Calculates the global rectangle RZ (reserved zone) of the component.
    Args:
        component: dict
        bbox: (x_min, y_min, x_max, y_max) – the global rectangle of the component
        preferred_side: "top" / "bottom" / "left" / "right" vagy None
    Returns:
        (res_x_min, res_y_min, res_x_max, res_y_max)
        If there is no meaningful RZ (e.g. res_w/res_d <= 0 or unknown location), it returns None.
    """
    x_min, y_min, x_max, y_max = bbox
    cx = (x_min + x_max) / 2.0
    cy = (y_min + y_max) / 2.0

    w_eff = x_max - x_min   # effective width of furniture (global x direction)
    d_eff = y_max - y_min   # effective depth of furniture (global y direction)

    # RZ paraméterek a komponensből
    res_location = (component.get("res_location") or "").strip().lower()
    res_w = float(component.get("res_w") or 0.0)
    res_d = float(component.get("res_d") or 0.0)

    # no or 0 size RZ -> nothing to calculate
    if res_w <= 0.0 and res_d <= 0.0:
        return None

    # ------------- AROUND -------------
    if res_location == "around":
        # goal: the center of the RZ should coincide with the center of the furniture, and the longer sides should be parallel.
        # decide whether to swap res_w / res_d so that the longer sides fall along the same axis.

        # longer direction on furniture
        if abs(w_eff - d_eff) < 1e-9:
            # square – arbitrary: no change in res_w/res_d
            rz_w_eff = res_w
            rz_d_eff = res_d
        else:
            comp_long_is_x = w_eff > d_eff
            rz_long_is_x = res_w >= res_d

            if comp_long_is_x == rz_long_is_x:
                # the longer sides are now parallel
                rz_w_eff = res_w
                rz_d_eff = res_d
            else:
                # swap it to make it parallel
                rz_w_eff = res_d
                rz_d_eff = res_w

        res_cx = cx
        res_cy = cy

        res_x_min = res_cx - rz_w_eff / 2.0
        res_x_max = res_cx + rz_w_eff / 2.0
        res_y_min = res_cy - rz_d_eff / 2.0
        res_y_max = res_cy + rz_d_eff / 2.0

        return res_x_min, res_y_min, res_x_max, res_y_max

    # ------------- FRONT -------------
    if res_location == "front" and preferred_side in ("top", "bottom", "left", "right"):
        # preferred_side: the side that faces the wall.
        # FRONT = the side that faces the wall.
        if preferred_side == "top":
            front_side = "bottom"
        elif preferred_side == "bottom":
            front_side = "top"
        elif preferred_side == "left":
            front_side = "right"
        else:  # "right"
            front_side = "left"

        # We use the following geometry:
        # - RZ is connected on the given front side,
        # - the length of the connecting side == the length of the corresponding side of the furniture,
        # - in the outward direction, res_d gives the depth.
        # We do not use res_w for the length of the connecting side, just adjust it to the length of the side of the furniture.

        if front_side in ("top", "bottom"):
            # connected along horizontal edge, length: w_eff
            rz_w_eff = w_eff
            rz_d_eff = res_d if res_d > 0 else 0.0

            if front_side == "top":
                # above furniture, upwards (y decreases)
                res_x_min = x_min
                res_x_max = x_max
                res_y_max = y_min
                res_y_min = y_min - rz_d_eff
            else:  # "bottom"
                # under furniture, downwards (y increases)
                res_x_min = x_min
                res_x_max = x_max
                res_y_min = y_max
                res_y_max = y_max + rz_d_eff

        else:
            # front_side in ("left", "right")
            # connected along vertical edge, length: d_eff
            rz_d_eff = d_eff
            rz_w_eff = res_d if res_d > 0 else 0.0

            if front_side == "left":
                # on the left side of the furniture, to the left (x decreases)
                res_y_min = y_min
                res_y_max = y_max
                res_x_max = x_min
                res_x_min = x_min - rz_w_eff
            else:  # "right"
                # on the right side of the furniture, to the right (x increases)
                res_y_min = y_min
                res_y_max = y_max
                res_x_min = x_max
                res_x_max = x_max + rz_w_eff

        return res_x_min, res_y_min, res_x_max, res_y_max

    # If RZ location is not interpreted
    return None

Side = Literal["left", "right", "top", "bottom"]

def preferred_container_side_for_component(
    container_bbox: Tuple[float, float, float, float],
    component_bbox: Tuple[float, float, float, float],
    connection_side: Optional[str] = None,
    eps: float = 1e-9,
) -> Side:
    """
    Determines which wall of the CONTAINER (left/right/top/bottom) is the 'preferred' wall for the component, taking into account:
        - the component's long/short side expectation (connection_side),
        - and the distance measured from the container walls.
    Args:
        - container_bbox: (cx_min, cy_min, cx_max, cy_max)
        - component_bbox: (px_min, py_min, px_max, py_max)
        - connection_side:
        - eps: tolerance
    Returns
        'left', 'right', 'top', 'bottom'
    """
    cx_min, cy_min, cx_max, cy_max = container_bbox
    px_min, py_min, px_max, py_max = component_bbox

    # component dimensions in the global system
    w = px_max - px_min
    d = py_max - py_min

    # distances from the container walls (negatives are converted to 0)
    dist_left   = max(px_min - cx_min, 0.0)
    dist_right  = max(cx_max - px_max, 0.0)
    dist_top    = max(py_min - cy_min, 0.0)
    dist_bottom = max(cy_max - py_max, 0.0)

    distances = {
        "left":   dist_left,
        "right":  dist_right,
        "top":    dist_top,
        "bottom": dist_bottom,
    }

    # --- selecting candidate walls based on connection_side ---
    conn = (connection_side or "").strip().lower()

    if conn in ("left", "right", "top", "bottom"):
        candidate_sides = [conn]

    elif conn in ("long", "short"):
        # put the longer / shorter side on the wall
        if abs(w - d) < eps:
            # square - arbitrary, any wall is good
            candidate_sides = ["top", "right", "bottom", "left"] #["left", "right", "top", "bottom"]
        else:
            long_is_x = w > d  # Is it longer horizontally?
            if long_is_x:
                # long edges: top/bottom (horizontal edges)
                if conn == "long":
                    candidate_sides = ["top", "bottom"]
                else:  # 'short'
                    candidate_sides = ["right", "left"]
            else:
                # long edges: left/right (vertical edges)
                if conn == "long":
                    candidate_sides = ["right", "left"]
                else:  # 'short'
                    candidate_sides = ["top", "bottom"]
    else:
        # no restrictions: any wall is ok
        candidate_sides = ["top", "right", "bottom", "left"] #["left", "right", "top", "bottom"]

    # --- selecting the closest wall from the candidates ---
    filtered = {side: distances[side] for side in candidate_sides}
    min_val = min(filtered.values())

    # deterministic selection: fixed order, within which the min distance
    side_order = ["top", "right", "bottom", "left"] #["left", "right", "top", "bottom"]
    best_candidates = [
        side for side in side_order
        if side in filtered and abs(filtered[side] - min_val) <= eps
    ]

    return best_candidates[0]

def random_individual(selected_components, room, overlap_enabled, wallfit_enabled, seed=42):
    """
    Returns: individual = list of component dicts, "x","y" is the center point within the container, "a_name" is the name of the container.
    """
    rng = random.Random(seed)

    # name -> original row
    name_to_row = {c["Name"]: c for c in selected_components}

    # structural graph
    G = build_structure_graph(selected_components)

    # assumption: edge direction <-> child -> container
    ordered_names = list(nx.topological_sort(G))

    individual = []
    individual_dict = {}

    for name in ordered_names:
        row = name_to_row[name]

        # --- dimensions (cm -> m) ---
        w = max(_to_float(row.get("Width"), 0.0) / 100.0, 0.05)
        d = max(_to_float(row.get("Depth"), 0.0) / 100.0, 0.05)

        # wall flag: -1 / 0 / 1
        try:
            wall_flag = int(float(row.get("Wall", -1)))
        except Exception:
            wall_flag = -1

        fixed = str(row.get("Fixed", "0")).strip() in ("1", "1.0", "True", "true")
        con_side = row.get("ConnectedSide")
        overlaps = row.get("Overlaps")
        forbidden_overlaps = row.get("ForbiddenOverlaps")

        # -----------------
        # ROOM component
        # -----------------
        if name.lower() == "room":
            # romm dimensions from Room object
            w = room.w
            d = room.h
            component = {
                "name": name,
                "rel_x" : w / 2.0,
                "rel_y" : d/2.0,
                "rel_o" : 0,
                "rel_preferred_side" : "top",
                "coord" : "top-left",
                "x": w / 2.0,
                "y": d / 2.0,
                "orientation": 0,
                "w": w,
                "d": d,
                "a_name": "",
                "fixed": True,
                "wall_flag": wall_flag,
                "changed": 0,
                "res_location": "",
                "res_w": 0,
                "res_d": 0,
                "preferred_side": "top",
                "connection_side" : con_side,
                "overlaps": overlaps,
                "forbidden_overlaps": forbidden_overlaps,
                "x_min" : 0,
                "y_min" : 0,
                "x_max" : w,
                "y_max" : d,
                "res_x_min" : 0,
                "res_y_min" : 0,
                "res_x_max" : 0,
                "res_y_max" : 0,
                "debug": ""
            }
            individual.append(component)
            individual_dict[name] = component
            continue

        # -----------------
        # Select CONTAINER
        # -----------------
        if overlap_enabled:
            pred = list(G.predecessors(name))  # if there is a successor: container; if there is none: room
            if pred: container_name = pred[0]
            else:    container_name = "room"
        else:        container_name = "room" # "" mode –> all item to room

        parent = individual_dict[container_name]
        a_x, a_y = parent["x"], parent["y"]
        a_pside = parent["preferred_side"]
        a_o = parent.get("orientation", 0) % 180
        if    a_o == 0: a_w, a_d = parent["w"], parent["d"]
        else: a_w, a_d = parent["d"], parent["w"] # for a 90° container, the global width/depth is swapped

        res_location = row.get("RZ location")
        try:
            res_w = (_to_number(row.get("Reserved zone").split("x", 1)[0]) or 0)/100
            res_d = (_to_number(row.get("Reserved zone").split("x", 1)[1]) or 0)/100
        except: res_w = 0; res_d = 0

        # window, door
        if name == "door":
            if room.door_wall == "left": o_rel = orientation = 90; x = x_rel = d/2; y = y_rel = room.door_x + w/2; eff_w = d; eff_d = w
            elif room.door_wall == "right": o_rel = orientation = 90; x = x_rel = room.w-d/2; y = y_rel = room.door_x + w/2; eff_w = d; eff_d = w
            elif room.door_wall == "top": o_rel = orientation = 0; x = x_rel =  room.door_x + w/2; y = y_rel = d/2; eff_w = w; eff_d = d
            elif room.door_wall == "bottom": o_rel = orientation = 0; x = x_rel = room.door_x + w/2; y = y_rel = room.h-d/2; eff_w = w; eff_d = d
        elif name == "window":
            if room.window_wall == "left": o_rel = orientation = 90; x = x_rel = d/2; y = y_rel = room.window_x + w/2; eff_w = d; eff_d = w
            elif room.window_wall == "right": o_rel = orientation = 90; x = x_rel = room.w-d/2; y = y_rel = room.window_x + w/2; eff_w = d; eff_d = w
            elif room.window_wall == "top": o_rel = orientation = 0; x = x_rel =  room.window_x + w/2; y = y_rel = d/2; eff_w = w; eff_d = d
            elif room.window_wall == "bottom": o_rel = orientation = 0; x = x_rel = room.window_x + w/2; y = y_rel = room.h-d/2; eff_w = w; eff_d = d
        else:
            # Selecting a component global orientation
            orientation, eff_w, eff_d = choose_orientation_and_extents(a_w, a_d, w, d, rng)

            # Calculating component relative orientation
            o_rel = (a_o + orientation) % 180

            # Generate center point within container
            if a_o == 0: ta_w, ta_d, teff_w, teff_d = a_w, a_d, eff_w, eff_d
            else:        ta_w, ta_d, teff_w, teff_d = a_d, a_w, eff_d, eff_w
            x_rel, y_rel = random_center_in_container(ta_w, ta_d, teff_w, teff_d, wallfit_enabled,
                wall_flag=wall_flag, connection_side=con_side, rng=rng, preferred_side=a_pside)

            # Global x, y definition
            if a_pside == "top":
                x = a_x - a_w / 2 + x_rel
                y = a_y - a_d / 2 + y_rel
            elif a_pside == "right":
                x = a_x + a_w / 2 - y_rel
                y = a_y - a_d / 2 + x_rel
            elif a_pside == "bottom":
                x = a_x + a_w / 2 - x_rel
                y = a_y + a_d / 2 - y_rel
            elif a_pside == "left":
                x = a_x - a_w / 2 + y_rel
                y = a_y + a_d / 2 - x_rel

        x_min = x - eff_w / 2.0
        y_min = y - eff_d / 2.0
        x_max = x + eff_w / 2.0
        y_max = y + eff_d / 2.0

        rel_preferred_side = preferred_container_side_for_component((a_x - a_w/2, a_y - a_d/2, a_x + a_w/2, a_y + a_d/2),
                                                                (x_min, y_min, x_max, y_max) , con_side)
        preferred_side = rel_preferred_side
        # -----------------
        # Component dict compilation
        # -----------------
        component = {
            "name": name,
            "rel_x": x_rel,
            "rel_y": y_rel,
            "rel_o": o_rel,
            "rel_preferred_side" : rel_preferred_side,
            "x": x,
            "y": y,
            "orientation": orientation,
            "w": w,
            "d": d,
            "a_name": container_name,
            "fixed": fixed,
            "wall_flag": wall_flag,
            "changed": 0,
            "res_location": res_location,
            "res_w": res_w,
            "res_d": res_d,
            "preferred_side": preferred_side,
            "connection_side": con_side,
            "overlaps": overlaps,
            "forbidden_overlaps": forbidden_overlaps,
            "x_min" : x_min,
            "y_min" : y_min,
            "x_max" : x_max,
            "y_max" : y_max,
            "res_x_min" : 0,
            "res_y_min" : 0,
            "res_x_max" : 0,
            "res_y_max" : 0,
            "debug" : ""
        }

        rz = compute_reserved_zone(component, (x_min, y_min,x_max,y_max), preferred_side)
        if rz is not None:
            res_x_min, res_y_min, res_x_max, res_y_max = rz
            component["res_x_min"] = res_x_min
            component["res_y_min"] = res_y_min
            component["res_x_max"] = res_x_max
            component["res_y_max"] = res_y_max
        individual.append(component)
        individual_dict[name] = component

    return individual

def build_global_bboxes(individual):
    """
    Returns a dict: name -> (x_min, y_min, x_max, y_max), where the coordinates are global
    """
    # name -> components
    by_name = {c["name"]: c for c in individual}

    # cache for global centers
    global_center = {}
    # cache for bboxs
    global_bbox = {}

    def _effective_size(comp):
        """Returns the effective (w,d) of the component according to the orientation."""
        w = comp["w"]
        d = comp["d"]
        ori = comp.get("orientation", 0) % 180
        if ori == 0:
            return w, d
        else:
            return d, w

    def _get_global_center(name):
        """Recursively calculates the global center of the component."""
        if name in global_center:
            return global_center[name]

        comp = by_name[name]
        a_name = comp.get("a_name") or ""

        # If there is no container -> room or root element: (x,y) is already global
        if a_name == "":
            cx = comp["x"]
            cy = comp["y"]
            global_center[name] = (cx, cy)
            return cx, cy

        #Otherwise, we first calculate the global center and size of the container
        pcx, pcy = _get_global_center(a_name)
        parent = by_name[a_name]
        pw, pd = _effective_size(parent)

        # container global top left corner
        p_left = pcx - pw / 2.0
        p_top  = pcy - pd / 2.0

        # global coordinate of own center: container top left + local (x,y)
        cx = p_left + comp["x"]
        cy = p_top  + comp["y"]

        global_center[name] = (cx, cy)
        return cx, cy

    def _get_global_bbox(name):
        """Recursively calculates the global bbox of the component."""
        if name in global_bbox:
            return global_bbox[name]

        comp = by_name[name]
        cx, cy = _get_global_center(name)
        ew, ed = _effective_size(comp)

        x_min = cx - ew / 2.0
        y_min = cy - ed / 2.0
        x_max = cx + ew / 2.0
        y_max = cy + ed / 2.0

        global_bbox[name] = (x_min, y_min, x_max, y_max)
        return x_min, y_min, x_max, y_max

    # we calculate for each component
    for comp in individual:
        _get_global_bbox(comp["name"])

    return global_bbox

def reserved_zone_around(p: Dict[str, Any], room_w, room_h):
    """
    For the 'table-like' case only: the reserved zone is around the object, and the object is in the middle of the zone.
    Sets the values of p['reserved_x'], p['reserved_y']."""

    rw, rd = float(p.get("reserved_w", 0) or 0), float(p.get("reserved_d", 0) or 0)
    if (rw == 0) or (rd == 0):
        p["reserved_x"] = 0.0
        p["reserved_y"] = 0.0
        return 0.0, 0.0, 0.0, 0.0

    x, y = float(p["x"]), float(p["y"])
    w, d = float(p["w"]), float(p["d"])

    # center of the table
    Cx = x + w / 2.0
    Cy = y + d / 2.0

    # Reserved zone with the table in the middle
    Lz = Cx - rw / 2.0
    Tz = Cy - rd / 2.0

    p["reserved_x"] = Lz
    p["reserved_y"] = Tz

    Rz = Lz + rw
    Bz = Tz + rd
    return Lz, Tz, Rz, Bz

def reserved_zone(p: Dict[str, Any], room_w, room_h):

    def place_on(side: str):
        if side == "right":
            Lz = x + w
            Rz = Lz + rw
            Cy = y + d / 2.0
            Tz = Cy - rd / 2.0
            Bz = Cy + rd / 2.0
        elif side == "left":
            Rz = x
            Lz = Rz - rw
            Cy = y + d / 2.0
            Tz = Cy - rd / 2.0
            Bz = Cy + rd / 2.0
        elif side == "bottom":
            Tz = y + d
            Bz = Tz + rd
            Cx = x + w / 2.0
            Lz = Cx - rw / 2.0
            Rz = Cx + rw / 2.0
        elif side == "top":
            Bz = y
            Tz = Bz - rd
            Cx = x + w / 2.0
            Lz = Cx - rw / 2.0
            Rz = Cx + rw / 2.0
        else:
            messagebox.showinfo("Error", "The value of side: " + side)
        return Lz, Tz, Rz, Bz

    rw, rd = float(p["reserved_w"]), float(p["reserved_d"])
    if (rw != 0) and (rd != 0):

        x, y = p["x"], p["y"]
        w, d = p["w"], p["d"]
        bbox = _bbox(x, y, w, d)
        side_order = _ordered_sides(bbox, room_w, room_h)

        # --- Applying LONG/SHORT preference ---
        side_pref = str(p.get("connection_side", "")).strip().lower()  # "long" | "short" | ""
        if w >= d:  # long edge: top/bottom; short edge: left/right
            long_sides = {"top", "bottom"}
            short_sides = {"left", "right"}
        else:  # long edge: left/right; short edge: top/bottom
            long_sides = {"left", "right"}
            short_sides = {"top", "bottom"}

        allowed = long_sides if side_pref == "long" else short_sides
        side_order = [s for s in side_order if s in allowed]

        # the reserved zone must be adjusted towards the far side
        side_order.reverse()

        Lz, Tz, Rz, Bz = place_on(side_order[0])
        p["reserved_x"] = Lz
        p["reserved_y"] = Tz
        return Lz, Tz, Rz, Bz
    else:
        p["reserved_x"] = 0
        p["reserved_y"] = 0
        return 0, 0, 0, 0

def center(rect):
    x1, y1, x2, y2 = rect
    cx = (x1 + x2) / 2
    cy = (y1 + y2) / 2
    return cx, cy

def _get_container_size(indiv, p):
    """
    Returns the effective (w,d) of the container (taking into account orientation) and the name of the container itself.
    """
    a_name = p.get("a_name") or "room"

    # searching the parent component in individual
    by_name = {c["name"]: c for c in indiv}
    parent = by_name.get(a_name)

    a_w, a_d = _effective_size_for_individual(parent)
    return a_name, a_w, a_d

def create_relation_df(indiv):
    overlaps_forbidden = {}
    overlaps_mandatory = {}
    idx_indiv = {p["name"]: p for p in indiv}

    for p in indiv:
        forbidden = p.get("forbidden_overlaps")
        if forbidden != "":
            parts = forbidden.split(",")
            overlaps_forbidden[p["name"]] = {part.strip() for part in parts}

        mandatory = p.get("overlaps") or []
        if mandatory:
            parts = mandatory.split(",")
            mandatory = {part.strip() for part in parts}
        if not isinstance(mandatory, (list, tuple, set)):
            mandatory = [mandatory]

        overlaps_mandatory[(p.get("name"))] = {x for x in mandatory}

    # Compute transitive closure (simplified version of Warshall's algorithm)
    changed = True
    wall = {p.get("name"): p.get("wall_flag") for p in indiv}
    while changed:
        changed = False
        for a in list(overlaps_mandatory.keys()):
            current = overlaps_mandatory[a].copy()
            for b in current:
                overlaps_mandatory[a].update(overlaps_mandatory.get(b, set()))
                # Synchronize Wall values
                item_a = idx_indiv.get(a)  # in advance, idx_indiv: name->element
                item_b = idx_indiv.get(b)
                if item_a is not None and item_b is not None:  # if it can't reach the wall or whatever, it has to be handled
                    if item_a.get("wall_flag") == "1" and item_b.get("wall_flag") == "0":
                        wall[item_b["name"]] = "1"
                        changed = True
                    elif item_b.get("wall_flag") == "1" and item_a.get("wall_flag") == "0":
                        wall[item_b["name"]] = "1"
                        changed = True

                #Propagating wall values from/to wall dict
                if wall.get(a) == "1" and wall.get(b) != "1":
                    wall[b] = "1"
                    changed = True
                elif wall.get(b) == "1" and wall.get(a) != "1":
                    wall[a] = "1"
                    changed = True

            if overlaps_mandatory[a] != current:
                changed = True

    for key, forbidden_set in overlaps_forbidden.items():
        if key in overlaps_mandatory:
            overlaps_mandatory[key] -= forbidden_set
        for om_key, mandatory_set in overlaps_mandatory.items():
            if key in mandatory_set:
                overlaps_mandatory[om_key] -= forbidden_set

    return overlaps_mandatory, wall

def diagonal_intersection_distance(rect1, rect2):
    cx1, cy1 = center(rect1)
    cx2, cy2 = center(rect2)
    return math.sqrt((cx1 - cx2)**2 + (cy1 - cy2)**2)

class PlanView:
    def __init__(self, plan: List[Dict[str, Any]]):
        self.by_name = {_normalize_name(o["name"]): o for o in plan}

    def get(self, name: str) -> Dict[str, Any] | None:
        return self.by_name.get(_normalize_name(name))

class fitnessfunction:
    def __init__(self, room_w, room_h, rules, model_params:ModelParams, constraints_doc: Dict[str, Any]):
        self.usages = 0
        self.room_w = room_w
        self.room_h = room_h
        self.model_params = model_params
        self.constraints = constraints_doc
        self.rules = rules

    def reset_usages(self) -> None:
        self.usages = 0

    def get_usages(self) -> int:
        return self.usages

    def edge_distance(self, a: Dict[str, Any], b: Dict[str, Any]) -> float:
        # minimum "edge distance" between two boxes (0 if they touch or overlap)
        ax1, ay1, ax2, ay2 = self.bbox_(a)
        bx1, by1, bx2, by2 = self.bbox_(b)
        dx = max(bx1 - ax2, ax1 - bx2, 0.0)
        dy = max(by1 - ay2, ay1 - by2, 0.0)
        # edge-sharing: 0 if dx==0 and they are at least tangent to each other on the other axis
        return math.hypot(dx, dy)

    def pred_exists(self, pv, x):
        ok = pv.get(x) is not None
        satisf = 1.0 if ok else 0.0
        mag = 0.0 if ok else 1.0
        return (satisf, {_normalize_name(x)}, mag)

    def pred_has_property(self, pv, x, prop):
        o = pv.get(x)
        ok = bool(o and prop in (o.get("properties") or {}))
        satisf = 1.0 if ok else 0.0
        mag = 0.0 if ok else 1.0
        return (satisf, {_normalize_name(x)}, mag)

    def pred_next_to(self, pv, x, y, tol=1e-3):
        a, b = pv.get(x), pv.get(y)
        actors = {_normalize_name(x), _normalize_name(y)}
        if not a or not b:
            return (0.0, actors, 1.0)  # teljes sértés

        dx = max(0.0, max(a["x_min"], b["x_min"]) - min(a["x_max"], b["x_max"]))
        dy = max(0.0, max(a["y_min"], b["y_min"]) - min(a["y_max"], b["y_max"]))
        dist = dx + dy
        if dist <= tol:
            return (1.0, actors, 0.0)

        # soft scale: scale 0..1 (e.g. up to 0.5 m)
        tau = 0.5
        satisf = max(0.0, 1.0 - dist / tau)
        return (satisf, actors, dist)

    def pred_parallel(self, pv: PlanView, x: str, y: str):
        """Checking parallelism between two rectangles"""
        a, b = pv.get(x), pv.get(y)
        actors = {_normalize_name(x), _normalize_name(y)}

        if a is None or b is None:
            # if there is none, it is a complete insult
            return (0.0, actors, 1.0)

        def orient(o):
            return "landscape" if o["w"] >= o["d"] else "portrait"

        same = orient(a) == orient(b)
        satisf = 1.0 if same else 0.0
        penalty_mag = 0.0 if same else 1.0
        return (satisf, actors, penalty_mag)

    def pred_distance(self, pv: PlanView, x: str, y: str, dmin: float, dmax: float):
        a, b = pv.get(x), pv.get(y)
        actors = {_normalize_name(x), _normalize_name(y)}

        if a is None or b is None:
            return (0.0, actors, 1.0)

        dist = self.edge_distance(a, b)

        dmin = float(dmin)
        dmax = float(dmax)

        if dmin <= dist <= dmax:
            return (1.0, actors, 0.0)

        if dist < dmin:
            mag = dmin - dist
        else:
            mag = dist - dmax

        tau = max(1e-9, dmax - dmin, 0.5)
        satisf = max(0.0, 1.0 - mag / tau)
        return (satisf, actors, mag)

    def pred_on_wall(self, pv: PlanView, x: str, w: str, tol: float = 0.05):
        o = pv.get(x)
        actors = {_normalize_name(x)}

        if o is None:
            return (0.0, actors, 1.0)

        wall = str(w).lower()

        if wall == "left":
            dist = abs(o["x_min"] - 0.0)
        elif wall == "right":
            dist = abs(self.room_w - o["x_max"])
        elif wall == "top":
            dist = abs(o["y_min"] - 0.0)
        elif wall == "bottom":
            dist = abs(self.room_h - o["y_max"])
        else:
            return (0.0, actors, 1.0)

        if dist <= tol:
            return (1.0, actors, 0.0)

        tau = 0.3
        satisf = max(0.0, 1.0 - dist / tau)
        return (satisf, actors, dist)

    def pred_between(self, pv: PlanView, x: str, y: str, z: str):
        ox, oy, oz = pv.get(x), pv.get(y), pv.get(z)
        actors = {_normalize_name(x), _normalize_name(y), _normalize_name(z)}

        if ox is None or oy is None or oz is None:
            return (0.0, actors, 1.0)

        px = ((ox["x_min"] + ox["x_max"]) / 2.0, (ox["y_min"] + ox["y_max"]) / 2.0)
        py = ((oy["x_min"] + oy["x_max"]) / 2.0, (oy["y_min"] + oy["y_max"]) / 2.0)
        pz = ((oz["x_min"] + oz["x_max"]) / 2.0, (oz["y_min"] + oz["y_max"]) / 2.0)

        vx, vy = pz[0] - py[0], pz[1] - py[1]
        wx, wy = px[0] - py[0], px[1] - py[1]
        seg2 = vx * vx + vy * vy

        if seg2 < 1e-12:
            return (0.0, actors, 1.0)

        t = (wx * vx + wy * vy) / seg2
        t_clamped = max(0.0, min(1.0, t))
        proj = (py[0] + t_clamped * vx, py[1] + t_clamped * vy)
        perp = math.hypot(px[0] - proj[0], px[1] - proj[1])

        # it is considered "between" if the projection is inside and the perpendicular deviation is small
        inside = 0.0 <= t <= 1.0
        if inside and perp <= 0.2:
            return (1.0, actors, 0.0)

        mag = perp + (0.0 if inside else min(abs(t), abs(t - 1)))
        satisf = max(0.0, 1.0 - mag / 1.0)
        return (satisf, actors, mag)

    def pred_value_range(self, pv: PlanView, x: str, a: str, vmin: float, vmax: float):
        o = pv.get(x)
        actors = {_normalize_name(x)}

        if o is None or a not in o:
            return (0.0, actors, 1.0)

        try:
            val = float(o[a])
            vmin = float(vmin)
            vmax = float(vmax)
        except Exception:
            return (0.0, actors, 1.0)

        if vmin <= val <= vmax:
            return (1.0, actors, 0.0)

        if val < vmin:
            dist = vmin - val
        else:
            dist = val - vmax

        tau = max(1e-9, vmax - vmin, 1.0)
        satisf = max(0.0, 1.0 - dist / tau)
        return (satisf, actors, dist)

    def pred_part_of(self, pv: PlanView, x: str, y: str, tol: float = 1e-9):
        """
        Geometrical 'part_of': the smaller object should be completely covered by the larger one.
        - if area(y) >= area(x), then x should be completely in y
        - if area(x) > area(y), then y should be completely in x
        Returns:
        - (satisf, actors, mag): satisf in [0,1], mag = the proportion of missing coverage (0 if satisfied)
        """
        a = pv.get(x)
        b = pv.get(y)
        actors = {_normalize_name(x), _normalize_name(y)}

        if a is None or b is None:
            return (0.0, actors, 1.0)

        # use the already calculated global bboxes
        bbox_a = (
            float(a["x_min"]),
            float(a["y_min"]),
            float(a["x_max"]),
            float(a["y_max"]),
        )
        bbox_b = (
            float(b["x_min"]),
            float(b["y_min"]),
            float(b["x_max"]),
            float(b["y_max"]),
        )

        area_a = max(0.0, (bbox_a[2] - bbox_a[0]) * (bbox_a[3] - bbox_a[1]))
        area_b = max(0.0, (bbox_b[2] - bbox_b[0]) * (bbox_b[3] - bbox_b[1]))

        # impossible cases
        if area_a <= tol or area_b <= tol:
            return (0.0, actors, 1.0)

        inter = overlap_area(bbox_a, bbox_b)

        # we always examine the full coverage of the smaller object
        target_area = min(area_a, area_b)
        cover_ratio = inter / target_area

        # # numerical stability
        cover_ratio = max(0.0, min(1.0, cover_ratio))

        satisf = cover_ratio
        mag = 1.0 - cover_ratio
        return (satisf, actors, mag)

    PREDICATES = {
        "exists": pred_exists,
        "has_property": pred_has_property,
        "next_to": pred_next_to,
        "parallel": pred_parallel,
        "part_of": pred_part_of,
        "value_range": pred_value_range,
        "between": pred_between,
        "on_wall": pred_on_wall,
        "distance": pred_distance,
    }

    def eval_ast(self, ast_node, pv):
        node = ast_node.get("node")
        if node == "pred":
            pred = ast_node["pred"]
            args = ast_node["args"]
            fn = self.PREDICATES.get(pred)
            if fn is None:
                return (0.0, set(), None)
            return fn(self, pv, *args)
        else:  # op
            op = ast_node["op"]
            sats, actors_sets, mags = [], [], []
            for ch in ast_node["args"]:
                s, a, m = self.eval_ast(ch, pv)
                sats.append(s);
                actors_sets.append(a);
                mags.append(m)
            # Zadeh
            if op == "AND":
                s = min(sats)
                actors = set().union(*actors_sets)
                return (s, actors, None)
            if op == "OR":
                s = max(sats)
                # union is ok; vagy vedd annak az actors-át, amelyik a maxot adta
                actors = set().union(*actors_sets)
                return (s, actors, None)
            # Algebraic
            # if op == "AND":
            #     s = 1.0
            #     for v in sats:
            #         s *= float(v)
            #     actors = set().union(*actors_sets)
            #     return (s, actors, None)
            #
            # if op == "OR":
            #     s = 0.0
            #     for v in sats:
            #         v = float(v)
            #         s = s + v - s * v
            #     actors = set().union(*actors_sets)
            #     return (s, actors, None)
            if op == "NOT":
                s = 1.0 - sats[0]
                return (s, actors_sets[0], None)
            return (0.0, set(), None)

    def bbox_(self, p: Dict[str, Any]) -> Tuple[float, float, float, float]:
        return (p["x"], p["y"], p["x"] + p["w"], p["y"] + p["d"])

    def _min_distance_to_wall(self, b, room_w, room_h) -> float:
        l, t, r, btm = b # b: (left, top, right, bottom)
        return min(l, t, room_w - r, room_h - btm)

    def get_usages(self):
        return self.usages

    def calculate_weight_sum(self, individual,  current_gen = 1, overlaps_mandatory = {}, wall = {}, areas = {} ):

        # 1) initialization
        total_area = 0
        total = 0.0
        bboxes = {}
        individual_dict = {}
        l_areas ={}
        for comp in individual:
            comp["overlaps_points"] = 0
            comp["overlaps_reserved_points"] = 0
            comp["connection_points"] = 0
            comp["llm_points"] = 0
            total_area += comp["w"] * comp["d"]
            l_areas[comp["name"]] = float(comp["w"] * comp["d"])
            bboxes[comp["name"]] = (float(comp["x_min"]), float(comp["y_min"]), float(comp["x_max"]), float(comp["y_max"]))
            individual_dict[comp["name"]] = comp

        names = [n for n in bboxes if n != "room"]
        pairs = [(names[i], names[j]) for i in range(len(names)) for j in range(i + 1, len(names))]

        w_overlap, w_wall = self.model_params.overlap_penalty, self.model_params.wall_dist_dir

        # 2) evaluation
        self.usages += 1

        for comp in individual:
            if comp["name"] == "room": continue
            if self.model_params.need_wall_dist_dir:
                if wall[comp["name"]] == 1:
                    # 1) if he has to stand against the wall of the ancestor, then if he doesn't stand there, he is punished
                    x1, y1, x2, y2 = bboxes[comp["name"]]
                    w_eff = x2 - x1
                    d_eff = y2 - y1

                    dist_left = x1
                    dist_right = self.room_w - x2
                    dist_top = y1
                    dist_bottom = self.room_h - y2

                    distances = {
                        "left": max(dist_left, 0.0),
                        "right": max(dist_right, 0.0),
                        "top": max(dist_top, 0.0),
                        "bottom": max(dist_bottom, 0.0),
                    }

                    preferred_side = comp.get("preferred_side")
                    if preferred_side not in distances:
                        conn = str(comp.get("connection_side", "")).strip().lower()
                        candidate_sides = ["left", "right", "top", "bottom"]
                        if conn in ("long", "short"):
                            if abs(w_eff - d_eff) < 1e-9:
                                candidate_sides = ["left", "right", "top", "bottom"]
                            else:
                                long_is_x = w_eff > d_eff
                                if long_is_x:
                                    candidate_sides = ["top", "bottom"] if conn == "long" else ["left", "right"]
                                else:
                                    candidate_sides = ["left", "right"] if conn == "long" else ["top", "bottom"]
                        preferred_side = min({s: distances[s] for s in candidate_sides}, key=lambda s: distances[s])

                    dist = distances.get(preferred_side, 0.0)
                    if preferred_side in ("left", "right"):
                        max_dist = max(self.room_w - w_eff, 1e-6)
                    else:
                        max_dist = max(self.room_h - d_eff, 1e-6)

                    comp["connection_points"] += round((dist / max_dist) * w_wall, 4)
                    total += round((dist / max_dist) * w_wall, 4)

                elif wall[comp["name"]] == 0:  #  wall=0 .
                    d = self._min_distance_to_wall(bboxes[comp["name"]], self.room_w, self.room_h)
                    if d < 0.6:  # it's good if d >= tol; if it's too close/touching, penalize
                        wall_pref = (0.6 - d) / 0.6

                        total += round(wall_pref * w_wall, 4)
                        comp["connection_points"] += round(wall_pref * w_wall, 4)
                else:  # -1; no matter if there is a connection
                    total += 0
                    comp["connection_points"] += 0

            # If someone is in the reserved area, they will be punished.

            if (comp["res_w"] > 0) and self.model_params.need_reserved_zone:

                ind_reserved_box = (comp["res_x_min"], comp["res_y_min"], comp["res_x_max"], comp["res_y_max"])
                for intruder in individual: # betolakodó
                    if (comp["name"] == intruder["name"]) or (intruder["name"] == "room"): continue
                    ov = overlap_area(ind_reserved_box, bboxes[intruder["name"]])
                    if ov == 0: continue
                    ov = ov / (l_areas[intruder["name"]])
                    total += round(ov * self.model_params.overlap_penalty, 4)
                    intruder["overlaps_reserved_points"] += round(ov * self.model_params.overlap_penalty,4)

        if self.model_params.need_llm_constraints:
            for c in self.constraints:
                pv = PlanView(individual)
                ast = c.get("ast") or {}
                weight = float(c.get("weight", 1.0))
                cid = str(c.get("id", "?"))

                # eval_ast (satisf, actors, magnitude) should return a triple
                satisf, actors, magnitude = self.eval_ast(ast, pv)  # pl. AND/OR/NOT + pred_* composition

                # penalty: soft-score (1 - satisf) * weight
                penalty = weight * max(0.0, 1.0 - float(satisf))

                # if magnitude is not None:
                #     penalty *= float(magnitude)  # vagy más formula
                present_names = {_normalize_name(o.get("name", "")) for o in individual}
                matched_actors = set(actors or set()) & present_names

                if matched_actors:
                    share = penalty / len(matched_actors)
                    distributed = 0.0

                    for o in individual:
                        key = _normalize_name(o.get("name", ""))
                        if key in matched_actors:
                            o["llm_points"] += share
                            distributed += share

                    total += distributed
                else:
                    total += 0.0

        # if overlap is not allowed, then penalize; if mandatory and there is no overlap, then penalize
        if self.model_params.need_overlap_penalty:
            for a, b in pairs:
                if ("under the" in a) or ("under the" in b):
                    pass
                ov = overlap_area(bboxes[a], bboxes[b])
                mandatory = (b in overlaps_mandatory.get(a, set())) or (a in overlaps_mandatory.get(b, set()))
                if mandatory:
                    # which is the subcomponent? -> item
                    if b in overlaps_mandatory.get(a, set()):  item = individual_dict[a]
                    else:                                      item = individual_dict[b]

                    # normalised overlap points [0-1], only the subcomponent get penalty
                    if ov > 0:              # Penalty:  if overlaps mandatory and there is real overlap, but 100%?
                        norm = min(l_areas[a], l_areas[b])
                        missing_rate = 1 - min(1, ov/norm)
                    elif ov == 0:           # Penalty: if overlaps allowed and there is no real overlap
                        ax1, ay1, ax2, ay2 = bboxes[a]
                        bx1, by1, bx2, by2 = bboxes[b]
                        center_distance = diagonal_intersection_distance(bboxes[a], bboxes[b])
                        norm = math.sqrt((self.room_w-(ax2-ax1)/2-(bx2-bx1)/2)**2 + (self.room_h-(ay2-ay1)/2-(by2-by1)/2)**2)
                        missing_rate = 1 + (center_distance/norm)

                    total += round(missing_rate * w_overlap, 4)
                    item["overlaps_points"] += round(missing_rate * w_overlap, 4)
                else:
                    if ov > 0: # Penalty: if overlaps forbidden and there is real overlap, both of them get penalty
                        item_a = individual_dict[a]
                        diff_a = ov/l_areas[a]
                        item_a["overlaps_points"] += round(diff_a * w_overlap, 4)
                        total += round(diff_a * w_overlap, 4)

                        item_b = individual_dict[b]
                        diff_b = ov/l_areas[b]
                        item_b["overlaps_points"] += round(diff_b * w_overlap, 4)
                        total += round(diff_b * w_overlap, 4)

        return total, current_gen, self.usages
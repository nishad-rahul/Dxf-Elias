from fastapi import FastAPI, Body
import ezdxf
import os
import base64
import math

app = FastAPI()

# =========================================================
# Pattern Configuration
# =========================================================
PATTERN_MAP = {
    "Squares 10x10mm": {"pattern": "square", "hole_size": 10, "spacing": 10, "offset": "half"},
    "Squares Grouped": {
        "pattern": "square", "hole_size": 10, "spacing": 10, "offset": "none",
        "grouping": {"base_col_count": 8, "gap_range": [60.0, 75.0]}
    },
    "Check 10x10mm": {"pattern": "diamond", "hole_size": 10, "spacing": 5.1, "offset": "half"},
    "Round hole 10mm": {"pattern": "circle", "hole_diameter": 10, "spacing": 10, "offset": "half"},
    
    "Slotted hole 35x10mm": {
        "pattern": "slot", 
        "slot_length": 29.9,
        "slot_width": 8.5,
        "spacing": 8.5, 
        "offset": "half"
    },
}

# =========================================================
# Helper: Natural Layout Finder (For Standard Patterns)
# =========================================================
def get_natural_layout(available_length, item_size, pitch, min_m=16.0, max_m=26.0):
    max_c = math.floor((available_length - item_size) / pitch) + 1
    if max_c % 2 == 0:
        max_c -= 1

    best_c = max(1, max_c)
    best_margin = (available_length - (item_size + (best_c - 1) * pitch)) / 2
    best_dist = 9999

    target_mid = (min_m + max_m) / 2.0

    for c in range(max_c, 0, -2):
        margin = (available_length - (item_size + (c - 1) * pitch)) / 2

        if margin < min_m:
            # Below hard floor — skip, stepping down will increase margin
            continue

        if margin > max_m:
            # Above ceiling — record only if nothing better found yet, keep looping
            dist = abs(margin - target_mid)
            if dist < best_dist:
                best_dist = dist
                best_c = c
                best_margin = margin
            continue

        # Inside the valid zone [min_m, max_m]
        dist = abs(margin - target_mid)
        if dist < best_dist:
            best_dist = dist
            best_c = c
            best_margin = margin

    # Safety net: if no valid layout found (extremely small sheet), use single centered hole
    if best_dist == 9999:
        best_c = 1
        best_margin = (available_length - item_size) / 2

    return best_c, best_margin

# =========================================================
# Layout Logic
# =========================================================
def calculate_layout_params(sheet_length, sheet_width, item_size, spacing, pattern_type, cfg):
    grouping = cfg.get("grouping")

    # ---------------------------------------------------------
    # 1. LONG SLOTHOLE (Muster L)
    # ---------------------------------------------------------
    if pattern_type == "slot":
        SLOT_L = 29.9
        SLOT_H = cfg.get("slot_width", 8.5)

        # --- X-AXIS ---
        best_cx = 1
        best_mx = (sheet_length - SLOT_L) / 2.0
        PITCH_X = SLOT_L + 7.5

        max_cx = math.floor((sheet_length - SLOT_L) / (SLOT_L + 7.0)) + 1
        if max_cx % 2 == 0:
            max_cx -= 1

        for cx in range(max(1, max_cx), 0, -2):
            max_possible_margin = (sheet_length - (SLOT_L + (cx - 1) * (SLOT_L + 7.0))) / 2

            if max_possible_margin >= 16.0:
                best_cx = cx
                best_dist = 9999

                for test_gap in [x * 0.1 for x in range(70, 81)]:
                    mx = (sheet_length - (SLOT_L + (cx - 1) * (SLOT_L + test_gap))) / 2
                    if 16.0 <= mx <= 26.0:
                        dist = abs(mx - 21.0)
                        if dist < best_dist:
                            best_dist = dist
                            best_mx = mx
                            PITCH_X = SLOT_L + test_gap

                if best_dist != 9999:
                    break

                best_mx = 21.0
                if best_cx > 1:
                    PITCH_X = (sheet_length - 2 * 21.0 - SLOT_L) / (best_cx - 1)
                break

        # --- Y-AXIS ---
        best_cy = 1
        best_my = (sheet_width - SLOT_H) / 2.0
        PITCH_Y = (SLOT_H + 24.5) / 2.0

        max_cy = math.floor((sheet_width - SLOT_H) / ((SLOT_H + 24.0) / 2.0)) + 1
        if max_cy % 2 == 0:
            max_cy -= 1

        for cy in range(max(1, max_cy), 0, -2):
            max_possible_margin_y = (sheet_width - (SLOT_H + (cy - 1) * ((SLOT_H + 24.0) / 2.0))) / 2

            if max_possible_margin_y >= 16.0:
                best_cy = cy
                best_dist = 9999

                for test_gap in [x * 0.1 for x in range(240, 251)]:
                    test_pitch_y = (SLOT_H + test_gap) / 2.0
                    my = (sheet_width - (SLOT_H + (cy - 1) * test_pitch_y)) / 2
                    if 16.0 <= my <= 26.0:
                        dist = abs(my - 21.0)
                        if dist < best_dist:
                            best_dist = dist
                            best_my = my
                            PITCH_Y = test_pitch_y

                if best_dist != 9999:
                    break

                best_my = 21.0
                if best_cy > 1:
                    PITCH_Y = (sheet_width - 2 * 21.0 - SLOT_H) / (best_cy - 1)
                break

        # --- DELTA ENFORCEMENT ---
        if abs(best_mx - best_my) > 10.0:
            best_mx = 21.0
            best_my = 21.0
            if best_cx > 1:
                PITCH_X = (sheet_length - 2 * 21.0 - SLOT_L) / (best_cx - 1)
            if best_cy > 1:
                PITCH_Y = (sheet_width - 2 * 21.0 - SLOT_H) / (best_cy - 1)

        return {
            "pattern": "slot", "is_grouped": False, "count_x": best_cx, "count_y": best_cy,
            "pitch_x": PITCH_X, "pitch_y": PITCH_Y,
            "margin_x": best_mx, "margin_y": best_my
        }

    # ---------------------------------------------------------
    # 2. GROUPED SQUARES (Q+)
    # ---------------------------------------------------------
    if grouping:
        pitch_y = item_size + spacing
        c_y, m_y = get_natural_layout(sheet_width, item_size, pitch_y)

        base_col = grouping.get("base_col_count", 8)
        min_gap, max_gap = grouping.get("gap_range", [60.0, 75.0])

        best_c = base_col
        best_gap = min_gap
        best_ng = 1
        best_mx = 0
        best_dist = 9999

        for c in range(base_col, 100):
            gw = (c * item_size) + ((c - 1) * spacing)
            for gap_int in range(int(min_gap * 10), int(max_gap * 10) + 1):
                test_gap = gap_int / 10.0
                stride = gw + test_gap

                ng = max(1, math.floor((sheet_length + test_gap) / stride))
                total_w = (ng * gw) + ((ng - 1) * test_gap)
                mx = (sheet_length - total_w) / 2

                # Enforce 16 mm hard floor for grouped squares
                if mx < 16.0:
                    continue

                dist = abs(mx - 21.0)
                if dist < best_dist:
                    best_dist = dist
                    best_c = c
                    best_gap = test_gap
                    best_ng = ng
                    best_mx = mx

        # Safety net if no valid grouped layout found
        if best_dist == 9999:
            best_mx = 21.0

        g_w = (best_c * item_size) + ((best_c - 1) * spacing)

        if abs(best_mx - m_y) > 10.0:
            m_y = best_mx
            if c_y > 1:
                pitch_y = (sheet_width - 2 * m_y - item_size) / (c_y - 1)

        return {
            "is_grouped": True, "num_groups": best_ng, "cols_per_group": best_c,
            "group_stride": g_w + best_gap, "pitch_x": item_size + spacing, "pitch_y": pitch_y,
            "margin_x": best_mx, "margin_y": m_y, "count_y": c_y
        }

    # ---------------------------------------------------------
    # 3. STANDARD LOGIC (Diamond, Square, Circle)
    # ---------------------------------------------------------
    if pattern_type == "diamond":
        pitch_x = (item_size + spacing) * math.sqrt(2)
        pitch_y = pitch_x / 2
        bounding_size = item_size * math.sqrt(2)
    else:
        pitch_x = item_size + spacing
        pitch_y = item_size + spacing
        bounding_size = item_size

    c_x, m_x = get_natural_layout(sheet_length, bounding_size, pitch_x)
    c_y, m_y = get_natural_layout(sheet_width, bounding_size, pitch_y)

    if abs(m_x - m_y) > 10.0:
        m_x = 21.0
        m_y = 21.0
        if c_x > 1:
            pitch_x = (sheet_length - 2 * m_x - bounding_size) / (c_x - 1)
        if c_y > 1:
            pitch_y = (sheet_width - 2 * m_y - bounding_size) / (c_y - 1)

    return {
        "is_grouped": False, "count_x": c_x, "count_y": c_y,
        "pitch_x": pitch_x, "pitch_y": pitch_y,
        "margin_x": m_x, "margin_y": m_y
    }

# =========================================================
# DXF Generator Endpoint
# =========================================================
@app.post("/generate_dxf")
async def generate_dxf(payload: dict = Body(...)):
    if isinstance(payload, list):
        payload = payload[0]

    raw_pattern = payload.get("pattern", "Squares 10x10mm")

    cfg = PATTERN_MAP.get(raw_pattern, PATTERN_MAP["Squares 10x10mm"])
    pattern = cfg["pattern"]

    customer = str(payload.get("customer", "Standard")).replace(" ", "_")
    length, width = float(payload.get("length", 500)), float(payload.get("width", 300))
    bent_top = payload.get("bent_top", False)

    hole_w = cfg.get("slot_length", 35) if pattern == "slot" else cfg.get("hole_size", 10)
    hole_h = cfg.get("slot_width", 10) if pattern == "slot" else hole_w

    layout = calculate_layout_params(length, width, hole_w, cfg["spacing"], pattern, cfg)

    final_width = width + 5.1 if bent_top else width

    os.makedirs("output_dxf", exist_ok=True)
    filename = f"output_dxf/{customer}_{int(length)}x{int(final_width)}.dxf"
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()

    R = 3.0
    L, W = length, final_width
    BULGE = 0.41421356
    points = [
        (L-R, 0, 0, 0, BULGE), (L, R, 0, 0, 0), (L, W-R, 0, 0, BULGE), (L-R, W, 0, 0, 0),
        (R, W, 0, 0, BULGE), (0, W-R, 0, 0, 0), (0, R, 0, 0, BULGE), (R, 0, 0, 0, 0)
    ]
    msp.add_lwpolyline(points, format="xyseb", dxfattribs={"layer": "OUTLINE", "closed": True})

    if "PATTERN" not in doc.layers:
        doc.layers.new(name="PATTERN")

    draw_hole_w = 29.9 if pattern == "slot" else hole_w
    draw_hole_h = 8.5 if pattern == "slot" else hole_h

    y = layout["margin_y"]
    for row in range(layout["count_y"]):

        if pattern == "slot":
            is_offset_row = (row % 2 != 0)
            row_off = (layout["pitch_x"] / 2) if is_offset_row else 0
        else:
            is_offset_row = (cfg["offset"] == "half" and row % 2 != 0)
            row_off = (layout["pitch_x"] / 2) if is_offset_row else 0

        if layout.get("is_grouped", False):
            for g in range(layout["num_groups"]):
                g_start = layout["margin_x"] + (g * layout["group_stride"])
                for c in range(layout["cols_per_group"]):
                    x = g_start + (c * layout["pitch_x"])
                    msp.add_lwpolyline(
                        [(x, y), (x+draw_hole_w, y), (x+draw_hole_w, y+draw_hole_h), (x, y+draw_hole_h), (x, y)],
                        dxfattribs={"layer": "PATTERN"}
                    )
        else:
            x_start = layout["margin_x"] + row_off

            current_count = layout["count_x"]
            if is_offset_row:
                current_count -= 1

            for c in range(current_count):
                x = x_start + (c * layout["pitch_x"])

                # Boundary guards
                if x + draw_hole_w > length:
                    continue
                if y + draw_hole_h > width:
                    continue

                if pattern == "square":
                    msp.add_lwpolyline(
                        [(x, y), (x+draw_hole_w, y), (x+draw_hole_w, y+draw_hole_h), (x, y+draw_hole_h), (x, y)],
                        dxfattribs={"layer": "PATTERN"}
                    )
                elif pattern == "slot":
                    r = draw_hole_h / 2
                    msp.add_line((x+r, y), (x+draw_hole_w-r, y), dxfattribs={"layer": "PATTERN"})
                    msp.add_line((x+r, y+draw_hole_h), (x+draw_hole_w-r, y+draw_hole_h), dxfattribs={"layer": "PATTERN"})
                    msp.add_arc((x+r, y+r), r, 90, 270, dxfattribs={"layer": "PATTERN"})
                    msp.add_arc((x+draw_hole_w-r, y+r), r, 270, 90, dxfattribs={"layer": "PATTERN"})
                elif pattern == "diamond":
                    diag_w = draw_hole_w * math.sqrt(2)
                    diag_h = draw_hole_h * math.sqrt(2)
                    cx, cy = x + diag_w / 2, y + diag_h / 2
                    msp.add_lwpolyline(
                        [(cx, y), (x+diag_w, cy), (cx, y+diag_h), (x, cy), (cx, y)],
                        dxfattribs={"layer": "PATTERN"}
                    )
                elif pattern == "circle":
                    r = draw_hole_w / 2
                    msp.add_circle((x+r, y+r), r, dxfattribs={"layer": "PATTERN"})

        y += layout["pitch_y"]

    doc.saveas(filename)
    with open(filename, "rb") as f:
        return {"status": "ok", "file_name": os.path.basename(filename), "file_base64": base64.b64encode(f.read()).decode()}

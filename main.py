from fastapi import FastAPI, Body
import ezdxf
import os
import base64
import math

app = FastAPI()

# =========================================================
# Pattern Configuration (shared by Variant A and Variant W)
# =========================================================
PATTERN_MAP = {
    "Squares 10x10mm": {
        "pattern": "square", "hole_size": 10, "spacing": 10, "offset": "half"
    },
    "Squares Grouped": {
        "pattern": "square", "hole_size": 10, "spacing": 10, "offset": "none",
        "grouping": {"base_col_count": 8, "gap_range": [60.0, 75.0]}
    },
    "Check 10x10mm": {
        "pattern": "diamond", "hole_size": 10, "spacing": 5.1, "offset": "half"
    },
    "Round hole 10mm": {
        "pattern": "circle", "hole_diameter": 10, "spacing": 10, "offset": "half"
    },
    "Slotted hole 35x10mm": {
        "pattern": "slot",
        "slot_length": 45.0,
        "slot_width": 8.5,
        "spacing": 8.5,
        "offset": "half"
    },
}

PATTERN_CODE_MAP = {
    "Squares 10x10mm":      "Q",
    "Squares Grouped":      "Q+",
    "Check 10x10mm":        "K",
    "Round hole 10mm":      "O",
    "Slotted hole 35x10mm": "L",
}

# =========================================================
# Helper: Natural Layout Finder (shared)
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
            continue

        if margin > max_m:
            dist = abs(margin - target_mid)
            if dist < best_dist:
                best_dist = dist
                best_c = c
                best_margin = margin
            continue

        dist = abs(margin - target_mid)
        if dist < best_dist:
            best_dist = dist
            best_c = c
            best_margin = margin

    if best_dist == 9999:
        best_c = 1
        best_margin = (available_length - item_size) / 2

    return best_c, best_margin

# =========================================================
# Layout Logic (shared)
# =========================================================
def calculate_layout_params(sheet_length, sheet_width, item_size, spacing, pattern_type, cfg):
    grouping = cfg.get("grouping")

    # ---------------------------------------------------------
    # 1. LONG SLOTHOLE (Muster L)
    # ---------------------------------------------------------
    if pattern_type == "slot":
        SLOT_L = cfg["slot_length"]
        SLOT_H = cfg["slot_width"]

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

                # Hard wall override
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

                # Hard wall override
                best_my = 21.0
                if best_cy > 1:
                    PITCH_Y = (sheet_width - 2 * 21.0 - SLOT_H) / (best_cy - 1)
                break

        # --- Delta enforcement ---
        if abs(best_mx - best_my) > 10.0:
            best_mx = 21.0
            best_my = 21.0
            if best_cx > 1:
                PITCH_X = (sheet_length - 2 * 21.0 - SLOT_L) / (best_cx - 1)
            if best_cy > 1:
                PITCH_Y = (sheet_width - 2 * 21.0 - SLOT_H) / (best_cy - 1)

        return {
            "pattern": "slot", "is_grouped": False,
            "count_x": best_cx, "count_y": best_cy,
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

                if mx < 16.0:
                    continue

                dist = abs(mx - 21.0)
                if dist < best_dist:
                    best_dist = dist
                    best_c = c
                    best_gap = test_gap
                    best_ng = ng
                    best_mx = mx

        if best_dist == 9999:
            best_mx = 21.0

        g_w = (best_c * item_size) + ((best_c - 1) * spacing)

        if abs(best_mx - m_y) > 10.0:
            m_y = best_mx
            if c_y > 1:
                pitch_y = (sheet_width - 2 * m_y - item_size) / (c_y - 1)

        return {
            "is_grouped": True, "num_groups": best_ng, "cols_per_group": best_c,
            "group_stride": g_w + best_gap, "pitch_x": item_size + spacing,
            "pitch_y": pitch_y, "margin_x": best_mx, "margin_y": m_y,
            "count_y": c_y
        }

    # ---------------------------------------------------------
    # 3. STANDARD LOGIC (Diamond, Square, Circle)
    # ---------------------------------------------------------
    if pattern_type == "diamond":
        pitch_x       = (item_size + spacing) * math.sqrt(2)
        pitch_y       = pitch_x / 2
        bounding_size = item_size * math.sqrt(2)
    else:
        pitch_x       = item_size + spacing
        pitch_y       = item_size + spacing
        bounding_size = item_size

    c_x, m_x = get_natural_layout(sheet_length, bounding_size, pitch_x)
    c_y, m_y = get_natural_layout(sheet_width,  bounding_size, pitch_y)

    if abs(m_x - m_y) > 10.0:
        m_x = 21.0
        m_y = 21.0
        if c_x > 1:
            pitch_x = (sheet_length - 2 * m_x - bounding_size) / (c_x - 1)
        if c_y > 1:
            pitch_y = (sheet_width  - 2 * m_y - bounding_size) / (c_y - 1)

    return {
        "is_grouped": False, "count_x": c_x, "count_y": c_y,
        "pitch_x": pitch_x, "pitch_y": pitch_y,
        "margin_x": m_x, "margin_y": m_y
    }

# =========================================================
# Outline Builder — Variant A
# All four corners: 3 mm rounded
# =========================================================
def draw_outline_a(msp, L, W, R=3.0):
    BULGE = 0.41421356
    points = [
        (R,   0,   0, 0, 0),
        (L-R, 0,   0, 0, BULGE),
        (L,   R,   0, 0, 0),
        (L,   W-R, 0, 0, BULGE),
        (L-R, W,   0, 0, 0),
        (R,   W,   0, 0, BULGE),
        (0,   W-R, 0, 0, 0),
        (0,   R,   0, 0, BULGE),
    ]
    msp.add_lwpolyline(
        points,
        format="xyseb",
        dxfattribs={"layer": "OUTLINE", "closed": True}
    )

# =========================================================
# Outline Builder — Variant W
#
# Outer sheet dimensions: L_outer x W_outer
# Notch cutout at top-left and top-right: bend x bend
# This leaves the inner perforation zone: L_inner x W_inner
# where:
#   L_inner = L_outer - 2 * bend  (horizontal)
#   W_inner = W_outer - bend       (vertical, bend only at top)
#
# Shape (origin at bottom-left):
#
#   (0, W_outer) ← not a point, notch cuts here
#
#   (0, W_outer)          (L_outer, W_outer)   <- does not exist (notch cuts)
#
#   (bend, W_outer) ────────── (L_outer-bend, W_outer)   <- top edge between notches
#       |                               |
#   (bend, W_inner) ──────────── (L_outer-bend, W_inner) <- notch inner corners
#       |                               |
#   (0, W_inner)                 (L_outer, W_inner)      <- sides resume
#       |                               |
#   rounded                         rounded               <- bottom corners (R=3mm)
#
# Bottom-left:  (0, R) arc to (R, 0)
# Bottom-right: (L_outer-R, 0) arc to (L_outer, R)
# =========================================================
def draw_outline_w(msp, L_outer, W_outer, bend, R=3.0):
    """
    L_outer  = L_inner + 2 * bend  (full sheet width including both flanges)
    W_outer  = W_inner + bend       (full sheet height including top flange)
    bend     = actual_bend = stated_thickness - 1.2
    """
    W_inner = W_outer - bend   # bottom of the notch / top of perforation zone

    points = [
    (0,              0,        0, 0, 0),
    (L_outer,        0,        0, 0, 0),
    (L_outer,        W_inner,  0, 0, 0),
    (L_outer - bend, W_inner,  0, 0, 0),
    (L_outer - bend, W_outer,  0, 0, 0),
    (bend,           W_outer,  0, 0, 0),
    (bend,           W_inner,  0, 0, 0),
    (0,              W_inner,  0, 0, 0),
]
    msp.add_lwpolyline(
        points,
        format="xyseb",
        dxfattribs={"layer": "OUTLINE", "closed": True}
    )

# =========================================================
# BEND Layer Lines — Variant W
# Two vertical dashed lines at x=bend and x=L_outer-bend
# running full height of sheet (W_outer), on BEND layer
# =========================================================


# =========================================================
# Pattern Draw (shared by Variant A and Variant W)
# For Variant W: pattern is drawn within the inner zone only.
# The inner zone starts at x=bend (left flange offset) and
# spans L_inner = L_outer - 2*bend horizontally,
# and from y=0 to y=W_inner vertically.
# =========================================================
def draw_pattern(msp, layout, cfg, pattern, L, W, x_offset=0.0):
    """
    x_offset: for Variant W, pass actual_bend so pattern starts
              after the left flange. For Variant A, pass 0.
    L:        inner zone width  (1292.8 for the example)
    W:        inner zone height (415.4 for the example)
    """
    draw_hole_w = cfg["slot_length"] if pattern == "slot" else cfg.get("hole_size", 10)
    draw_hole_h = cfg["slot_width"]  if pattern == "slot" else cfg.get("hole_size", 10)

    # Bounding size used for boundary checks
    if pattern == "diamond":
        bounding_w = draw_hole_w * math.sqrt(2)
        bounding_h = draw_hole_h * math.sqrt(2)
    else:
        bounding_w = draw_hole_w
        bounding_h = draw_hole_h

    y = layout["margin_y"]

    for row in range(layout["count_y"]):

        if pattern == "slot":
            is_offset_row = (row % 2 != 0)
        else:
            is_offset_row = (cfg["offset"] == "half" and row % 2 != 0)

        row_off = (layout["pitch_x"] / 2) if is_offset_row else 0

        if layout.get("is_grouped", False):
            for g in range(layout["num_groups"]):
                g_start = x_offset + layout["margin_x"] + (g * layout["group_stride"])
                for c in range(layout["cols_per_group"]):
                    x = g_start + (c * layout["pitch_x"])
                    # Boundary check against inner zone
                    if x + draw_hole_w > x_offset + L:
                        continue
                    if y + draw_hole_h > W:
                        continue
                    msp.add_lwpolyline(
                        [(x, y), (x+draw_hole_w, y), (x+draw_hole_w, y+draw_hole_h),
                         (x, y+draw_hole_h), (x, y)],
                        dxfattribs={"layer": "PATTERN"}
                    )
        else:
            x_start = x_offset + layout["margin_x"] + row_off
            current_count = layout["count_x"]
            if is_offset_row:
                current_count -= 1

            for c in range(current_count):
                x = x_start + (c * layout["pitch_x"])

                # Boundary check uses bounding_w (correct for diamonds)
                if x + bounding_w > x_offset + L:
                    continue
                if y + bounding_h > W:
                    continue

                if pattern == "square":
                    msp.add_lwpolyline(
                        [(x, y), (x+draw_hole_w, y), (x+draw_hole_w, y+draw_hole_h),
                         (x, y+draw_hole_h), (x, y)],
                        dxfattribs={"layer": "PATTERN"}
                    )
                elif pattern == "slot":
                    r = draw_hole_h / 2
                    msp.add_line((x+r, y), (x+draw_hole_w-r, y),
                                 dxfattribs={"layer": "PATTERN"})
                    msp.add_line((x+r, y+draw_hole_h), (x+draw_hole_w-r, y+draw_hole_h),
                                 dxfattribs={"layer": "PATTERN"})
                    msp.add_arc((x+r, y+r), r, 90, 270,
                                dxfattribs={"layer": "PATTERN"})
                    msp.add_arc((x+draw_hole_w-r, y+r), r, 270, 90,
                                dxfattribs={"layer": "PATTERN"})
                elif pattern == "diamond":
                    diag_w = draw_hole_w * math.sqrt(2)
                    diag_h = draw_hole_h * math.sqrt(2)
                    cx_pt  = x + diag_w / 2
                    cy_pt  = y + diag_h / 2
                    msp.add_lwpolyline(
                        [(cx_pt, y), (x+diag_w, cy_pt), (cx_pt, y+diag_h),
                         (x, cy_pt), (cx_pt, y)],
                        dxfattribs={"layer": "PATTERN"}
                    )
                elif pattern == "circle":
                    r = draw_hole_w / 2
                    msp.add_circle((x+r, y+r), r, dxfattribs={"layer": "PATTERN"})

        y += layout["pitch_y"]

# =========================================================
# Single Endpoint — routes to Variant A or Variant W
# =========================================================
@app.post("/generate_dxf")
async def generate_dxf(payload: dict = Body(...)):
    if isinstance(payload, list):
        payload = payload[0]

    customer    = str(payload.get("customer", "Standard")).replace(" ", "_")
    raw_pattern = payload.get("pattern", "Squares 10x10mm")
    variant     = str(payload.get("variant", "A")).upper()

    # --- Dimension resolution by variant ---
    if variant == "W":
        # Variant W inputs:
        #   length    = stated horizontal finished size (e.g. 1294mm)
        #   width     = stated vertical finished size   (e.g. 416mm)
        #   thickness = bend flange size                (e.g. 9mm)
        #
        # Corrections:
        #   L_inner   = stated_length - 1.2   → perforation zone width
        #   W_inner   = stated_width  - 0.6   → perforation zone height
        #   actual_bend = stated_bend - 1.2   → flange size after correction
        #
        # Outer sheet (what gets drawn as outline):
        #   L_outer = L_inner + 2 * actual_bend  (flanges on left AND right)
        #   W_outer = W_inner + actual_bend       (flange only on top)

        stated_length = float(payload.get("length",    1294))
        stated_width  = float(payload.get("width",      416))
        stated_bend   = float(payload.get("thickness",    9))

        L_inner     = stated_length - 1.2        # e.g. 1294 → 1292.8 mm
        W_inner     = stated_width  - 0.6        # e.g. 416  → 415.4  mm
        actual_bend = stated_bend   - 1.2        # e.g. 9    → 7.8    mm

        L_outer     = L_inner + 2 * actual_bend  # e.g. 1292.8 + 15.6 = 1308.4 mm
        W_outer     = W_inner + actual_bend      # e.g. 415.4  + 7.8  = 423.2  mm

        # Variant W
        output_dir  = "output_dxf_w"
        filename_id = f"{customer}_W_{pattern_code}_{int(stated_length)}x{int(stated_width)}x{int(stated_bend)}"

    else:
        # Variant A: no corrections
        length   = float(payload.get("length", 500))
        width    = float(payload.get("width",  300))
        bent_top = payload.get("bent_top", False)

        L = length
        W = width + 5.1 if bent_top else width

       # Variant A
        output_dir  = "output_dxf"
        filename_id = f"{customer}_A_{pattern_code}_{int(length)}x{int(width)}x1"

    # --- Get pattern config ---
    print(f"[DEBUG] raw_pattern received: '{raw_pattern}'")
    print(f"[DEBUG] available keys: {list(PATTERN_MAP.keys())}")

    cfg = PATTERN_MAP.get(raw_pattern)
    if cfg is None:
        return {
            "status": "error",
            "message": f"Pattern '{raw_pattern}' not found. Available: {list(PATTERN_MAP.keys())}"
        }

    pattern = cfg["pattern"]
    print(f"[DEBUG] resolved pattern type: '{pattern}', cfg: {cfg}")

    hole_w = cfg["slot_length"] if pattern == "slot" else cfg.get("hole_size", 10)

    # --- Calculate layout against inner zone dimensions ---
    if variant == "W":
        layout = calculate_layout_params(
            L_inner, W_inner, hole_w, cfg["spacing"], pattern, cfg
        )
    else:
        layout_width = float(payload.get("width", 300)) if variant == "A" else W
        layout = calculate_layout_params(L, layout_width, hole_w, cfg["spacing"], pattern, cfg)

    if variant == "W":
        print(f"[DEBUG] variant=W, L_inner={L_inner}, W_inner={W_inner}, "
              f"L_outer={L_outer}, W_outer={W_outer}, actual_bend={actual_bend}")
    else:
        print(f"[DEBUG] variant=A, L={L}, W={W}")
    print(f"[DEBUG] layout: {layout}")

    # --- Build DXF ---
    os.makedirs(output_dir, exist_ok=True)
    filename = f"{output_dir}/{customer}_{filename_id}.dxf"

    doc = ezdxf.new("R2010")
    msp = doc.modelspace()

    for layer_name in ["OUTLINE", "PATTERN", "BEND"]:
        if layer_name not in doc.layers:
            doc.layers.new(name=layer_name)

    # --- Draw outline and pattern based on variant ---
    if variant == "W":
        # Outline uses full outer dimensions
        draw_outline_w(msp, L_outer, W_outer, actual_bend)

        # Pattern drawn within inner zone, offset by actual_bend on X axis
        draw_pattern(msp, layout, cfg, pattern, L_inner, W_inner, x_offset=actual_bend)

    else:
        draw_outline_a(msp, L, W)
        draw_pattern(msp, layout, cfg, pattern, L, W, x_offset=0.0)

    # --- Save and return ---
    doc.saveas(filename)
    with open(filename, "rb") as f:
        response = {
            "status":      "ok",
            "variant":     variant,
            "file_name":   os.path.basename(filename),
            "file_base64": base64.b64encode(f.read()).decode()
        }

    if variant == "W":
        response["L_inner"]     = L_inner
        response["W_inner"]     = W_inner
        response["L_outer"]     = L_outer
        response["W_outer"]     = W_outer
        response["actual_bend"] = actual_bend

    return response

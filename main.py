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
        "slot_length": 29.9, # Hardcoded in math, listed here for reference
        "slot_width": 8.5, 
        "spacing": 8.5, 
        "offset": "half"
    },
}

# =========================================================
# Helper: Natural Layout Finder 
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
        dist = abs(margin - target_mid)
        if dist < best_dist:
            best_dist = dist
            best_c = c
            best_margin = margin
            
    return best_c, best_margin

# =========================================================
# Layout Logic
# =========================================================
def calculate_layout_params(sheet_length, sheet_width, item_size, spacing, pattern_type, cfg):
    grouping = cfg.get("grouping")

    # ---------------------------------------------------------
    # 1. LONG SLOTHOLE (Muster L) - BULLETPROOF BOUNDARIES
    # ---------------------------------------------------------
    if pattern_type == "slot":
        # 1. FIXED MACHINE DIMENSIONS
        SLOT_L = 29.9 
        SLOT_H = cfg.get("slot_width", 8.5)
        
        # --- X-AXIS CALCULATION ---
        # Find maximum odd slots that guarantee a >= 16.0mm margin
        min_pitch_x = SLOT_L + 7.0
        max_cx = math.floor((sheet_length - 2 * 16.0 - SLOT_L) / min_pitch_x) + 1
        if max_cx % 2 == 0: max_cx -= 1
        best_cx = max(1, max_cx)
        
        # Scan 7.0 to 8.0 gap to get margin as close to 21.0 as possible
        best_gap_x = 7.5
        best_mx = (sheet_length - (SLOT_L + (best_cx - 1) * (SLOT_L + best_gap_x))) / 2
        
        for test_gap in [x * 0.1 for x in range(70, 81)]: 
            test_pitch = SLOT_L + test_gap
            mx = (sheet_length - (SLOT_L + (best_cx - 1) * test_pitch)) / 2
            if abs(mx - 21.0) < abs(best_mx - 21.0):
                best_mx = mx
                best_gap_x = test_gap
                
        PITCH_X = SLOT_L + best_gap_x
        
        # --- Y-AXIS CALCULATION ---
        # Find max odd rows that guarantee >= 16.0mm margin (vert gap = 24.0-25.0)
        min_gap_y = 24.0
        min_pitch_y = (SLOT_H + min_gap_y) / 2.0
        
        max_cy = math.floor((sheet_width - 2 * 16.0 - SLOT_H) / min_pitch_y) + 1
        if max_cy % 2 == 0: max_cy -= 1
        best_cy = max(1, max_cy)
        
        best_gap_y = 24.5
        best_my = (sheet_width - (SLOT_H + (best_cy - 1) * ((SLOT_H + best_gap_y) / 2.0))) / 2
        
        for test_gap in [x * 0.1 for x in range(240, 251)]: 
            test_pitch_y = (SLOT_H + test_gap) / 2.0
            my = (sheet_width - (SLOT_H + (best_cy - 1) * test_pitch_y)) / 2
            if abs(my - 21.0) < abs(best_my - 21.0):
                best_my = my
                best_gap_y = test_gap
                
        PITCH_Y = (SLOT_H + best_gap_y) / 2.0
        
        # --- EMERGENCY OVERRIDE (RUBBER BAND) ---
        # Trigger if margins are out of bounds (>26.0) or differ by >10mm
        # Only override if best_c > 1 (we cannot stretch a single slot)
        if abs(best_mx - best_my) > 10.0 or best_mx > 26.0 or best_my > 26.0:
            
            # Force X to 21.0mm if safe
            if best_cx > 1:
                test_pitch_x = (sheet_length - 2 * 21.0 - SLOT_L) / (best_cx - 1)
                if test_pitch_x >= SLOT_L + 2.0: # Absolute protection against overlap
                    PITCH_X = test_pitch_x
                    best_mx = 21.0
                    
            # Force Y to 21.0mm if safe
            if best_cy > 1:
                test_pitch_y = (sheet_width - 2 * 21.0 - SLOT_H) / (best_cy - 1)
                if test_pitch_y >= SLOT_H + 2.0: # Absolute protection against overlap
                    PITCH_Y = test_pitch_y
                    best_my = 21.0

        return {
            "pattern": "slot", "is_grouped": False, "count_x": best_cx, "count_y": best_cy,
            "pitch_x": PITCH_X, "pitch_y": PITCH_Y,
            "margin_x": best_mx, "margin_y": best_my
        }

    # ---------------------------------------------------------
    # 2. GROUPED SQUARES (Q+) - UNTOUCHED
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
                
                dist = abs(mx - 21.0)
                if dist < best_dist:
                    best_dist = dist
                    best_c = c
                    best_gap = test_gap
                    best_ng = ng
                    best_mx = mx
                    
        g_w = (best_c * item_size) + ((best_c - 1) * spacing)
        
        if abs(best_mx - m_y) > 10.0:
            m_y = best_mx
            if c_y > 1: pitch_y = (sheet_width - 2*m_y - item_size) / (c_y - 1)

        return {
            "is_grouped": True, "num_groups": best_ng, "cols_per_group": best_c,
            "group_stride": g_w + best_gap, "pitch_x": item_size + spacing, "pitch_y": pitch_y,
            "margin_x": best_mx, "margin_y": m_y, "count_y": c_y
        }

    # ---------------------------------------------------------
    # 3. STANDARD LOGIC (Diamond, Square, Circle) - UNTOUCHED
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
        if c_x > 1: pitch_x = (sheet_length - 2*m_x - bounding_size) / (c_x - 1)
        if c_y > 1: pitch_y = (sheet_width - 2*m_y - bounding_size) / (c_y - 1)

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
    if isinstance(payload, list): payload = payload[0]

    raw_pattern = payload.get("pattern", "Squares 10x10mm")
    
    cfg = PATTERN_MAP.get(raw_pattern, PATTERN_MAP["Squares 10x10mm"])
    pattern = cfg["pattern"]

    customer = str(payload.get("customer", "Standard")).replace(" ", "_")
    length, width = float(payload.get("length", 500)), float(payload.get("width", 300))
    bent_top = payload.get("bent_top", False)

    hole_w = cfg.get("slot_length", 35) if pattern == "slot" else cfg.get("hole_size", 10)
    hole_h = cfg.get("slot_width", 10) if pattern == "slot" else hole_w

    # Passed config properly to avoid global state drift
    layout = calculate_layout_params(length, width, hole_w, cfg["spacing"], pattern, cfg)

    final_width = width + 5.1 if bent_top else width

    os.makedirs("output_dxf", exist_ok=True)
    filename = f"output_dxf/{customer}_{int(length)}x{final_width}.dxf"
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
    
    if "PATTERN" not in doc.layers: doc.layers.new(name="PATTERN")

    # Hardcoded render to guarantee no resizing for Slot 
    draw_hole_w = 29.9 if pattern == "slot" else hole_w
    draw_hole_h = 8.5 if pattern == "slot" else hole_h
    
    y = layout["margin_y"]
    for row in range(layout["count_y"]):
        if pattern == "slot":
            row_off = (layout["pitch_x"] / 2) if row % 2 != 0 else 0
        else:
            row_off = (layout["pitch_x"] / 2) if cfg["offset"] == "half" and row % 2 != 0 else 0
        
        if layout.get("is_grouped", False):
            for g in range(layout["num_groups"]):
                g_start = layout["margin_x"] + (g * layout["group_stride"])
                for c in range(layout["cols_per_group"]):
                    x = g_start + (c * layout["pitch_x"])
                    msp.add_lwpolyline([(x,y),(x+draw_hole_w,y),(x+draw_hole_w,y+draw_hole_h),(x,y+draw_hole_h),(x,y)], dxfattribs={"layer":"PATTERN"})
        else:
            x_start = layout["margin_x"] + row_off
            
            current_count = layout["count_x"]
            if row_off > 0:
                current_count -= 1
                
            for c in range(current_count):
                x = x_start + (c * layout["pitch_x"])
                if x + draw_hole_w > length: continue

                if pattern == "square":
                    msp.add_lwpolyline([(x,y),(x+draw_hole_w,y),(x+draw_hole_w,y+draw_hole_h),(x,y+draw_hole_h),(x,y)], dxfattribs={"layer":"PATTERN"})
                elif pattern == "slot":
                    r = draw_hole_h / 2
                    msp.add_line((x+r, y), (x+draw_hole_w-r, y), dxfattribs={"layer":"PATTERN"})
                    msp.add_line((x+r, y+draw_hole_h), (x+draw_hole_w-r, y+draw_hole_h), dxfattribs={"layer":"PATTERN"})
                    msp.add_arc((x+r, y+r), r, 90, 270, dxfattribs={"layer":"PATTERN"})
                    msp.add_arc((x+draw_hole_w-r, y+r), r, 270, 90, dxfattribs={"layer":"PATTERN"})
                elif pattern == "diamond":
                    diag_w = draw_hole_w * math.sqrt(2) 
                    diag_h = draw_hole_h * math.sqrt(2)
                    cx, cy = x + diag_w/2, y + diag_h/2
                    msp.add_lwpolyline([(cx, y), (x+diag_w, cy), (cx, y+diag_h), (x, cy), (cx, y)], dxfattribs={"layer":"PATTERN"})
                elif pattern == "circle":
                    r = draw_hole_w / 2
                    msp.add_circle((x+r, y+r), r, dxfattribs={"layer":"PATTERN"})

        y += layout["pitch_y"]

    doc.saveas(filename)
    with open(filename, "rb") as f:
        return {"status": "ok", "file_name": os.path.basename(filename), "file_base64": base64.b64encode(f.read()).decode()}

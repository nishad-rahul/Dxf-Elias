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
    # ⬜ SQUARES (Staggered)
    "Squares 10x10mm": {"pattern": "square", "hole_size": 10, "spacing": 10, "offset": "half"},
    
    # ▦ SQUARES (Grouped): Dynamic Option B
    "Squares Grouped": {
        "pattern": "square", "hole_size": 10, "spacing": 10, "offset": "none",
        "grouping": {
            "base_col_count": 8, 
            "gap_range": [60.0, 75.0], 
            "max_margin": 35.0
        }
    },
    
    # 💎 DIAMOND: Fixed 5.1mm spacing
    "Check 10x10mm": {"pattern": "diamond", "hole_size": 10, "spacing": 5.1, "offset": "half"},
    
    # ⚪ ROUND: Circles
    "Round hole 10mm": {"pattern": "circle", "hole_diameter": 10, "spacing": 10, "offset": "half"},
    
    # ▬ SLOTS: Herx Dimensions
    "Slotted hole 35x10mm": {
        "pattern": "slot", 
        "slot_length": 45.0, 
        "slot_width": 8.5, 
        "spacing": 8.5, 
        "offset": "half"
    },
}

# =========================================================
# Helper: Optimized Odd Count (Universal)
# =========================================================
def optimize_odd_count(available_length, item_size, pitch, stagger_offset=0):
    max_c = math.floor((available_length - item_size - stagger_offset - 34) / pitch) + 1
    # FORCE ODD NUMBER for Center-Out Symmetry
    if max_c % 2 == 0:
        max_c -= 1
    return max(1, max_c)

# =========================================================
# Layout Logic
# =========================================================
def calculate_layout_params(sheet_length, sheet_width, item_size, spacing, pattern_type, grouping=None):

    # ---------------------------------------------------------
    # 1. LONG SLOTHOLE (Muster L)
    # ---------------------------------------------------------
    if pattern_type == "slot":
        SLOT_L = 45.0
        SLOT_H = 8.5
        PITCH_Y = 17.0
        
        best_gap = 8.5
        for test_gap in [x * 0.1 for x in range(85, 121)]:
            test_pitch = SLOT_L + test_gap
            
            raw_count = math.floor((sheet_length - 36 - SLOT_L) / test_pitch) + 1
            odd_count = raw_count if raw_count % 2 != 0 else raw_count - 1
            
            total_w = SLOT_L + (odd_count - 1) * test_pitch
            margin = (sheet_length - total_w) / 2
            
            if 18.0 <= margin <= 27.0:
                best_gap = test_gap
                break 

        PITCH_X = SLOT_L + best_gap
        
        raw_count_x = math.floor((sheet_length - 36 - SLOT_L) / PITCH_X) + 1
        count_x = raw_count_x if raw_count_x % 2 != 0 else raw_count_x - 1
        
        raw_count_y = math.floor((sheet_width - 36 - SLOT_H) / PITCH_Y) + 1
        count_y = raw_count_y if raw_count_y % 2 != 0 else raw_count_y - 1
        
        total_w = SLOT_L + (count_x - 1) * PITCH_X
        total_h = SLOT_H + (count_y - 1) * PITCH_Y
        
        return {
            "pattern": "slot",
            "is_grouped": False, "count_x": count_x, "count_y": count_y,
            "pitch_x": PITCH_X, "pitch_y": PITCH_Y,
            "margin_x": (sheet_length - total_w) / 2,
            "margin_y": (sheet_width - total_h) / 2
        }

    # ---------------------------------------------------------
    # 2. GROUPED SQUARES (Q+) - Dynamic Range
    # ---------------------------------------------------------
    if grouping:
        base_col = grouping.get("base_col_count", 8)
        min_gap, max_gap = grouping.get("gap_range", [60.0, 75.0])
        max_margin = grouping.get("max_margin", 35.0)
        
        best_c = base_col
        best_gap = min_gap
        best_ng = 1
        best_margin_val = 9999
        found_perfect = False
        
        for c in range(base_col, 100): 
            gw = (c * item_size) + ((c - 1) * spacing)
            for gap_int in range(int(min_gap * 10), int(max_gap * 10) + 1):
                test_gap = gap_int / 10.0
                stride = gw + test_gap
                
                ng = max(1, math.floor((sheet_length + test_gap) / stride))
                total_w = (ng * gw) + ((ng - 1) * test_gap)
                margin = (sheet_length - total_w) / 2
                
                if 0 <= margin < best_margin_val:
                    best_c = c
                    best_gap = test_gap
                    best_ng = ng
                    best_margin_val = margin
                
                if 0 <= margin <= max_margin:
                    found_perfect = True
                    break 
            if found_perfect: break 
                
        g_w = (best_c * item_size) + ((best_c - 1) * spacing)
        pitch_y = item_size + spacing
        total_w = (best_ng * g_w) + ((best_ng - 1) * best_gap)
        
        # Syncing Q+ Y-axis
        count_y = optimize_odd_count(sheet_width, item_size, pitch_y)
        total_h = item_size + ((count_y - 1) * pitch_y)
        
        return {
            "is_grouped": True, "num_groups": best_ng, "cols_per_group": best_c,
            "group_stride": g_w + best_gap, "pitch_x": pitch_x, "pitch_y": pitch_y,
            "margin_x": (sheet_length - total_w) / 2, "margin_y": (sheet_width - total_h) / 2, "count_y": count_y
        }

    # ---------------------------------------------------------
    # 3. STANDARD LOGIC (Diamond, Square, Circle)
    # ---------------------------------------------------------
    if pattern_type == "diamond":
        pitch_x = (item_size + spacing) * math.sqrt(2)
        pitch_y = pitch_x / 2
        stagger_x = pitch_x / 2
        bounding_size = item_size * math.sqrt(2)
    else:
        pitch_x = item_size + spacing
        pitch_y = item_size + spacing
        stagger_x = (pitch_x / 2)
        bounding_size = item_size

    # 1. Get the X Margin first
    count_x = optimize_odd_count(sheet_length, bounding_size, pitch_x, 0)
    total_w = bounding_size + ((count_x - 1) * pitch_x)
    margin_x = (sheet_length - total_w) / 2

    # 2. OPTION 2 LOGIC: Sync Top/Bottom to Left/Right
    item_h = bounding_size
    max_count_y = optimize_odd_count(sheet_width, item_h, pitch_y)
    
    best_count_y = max_count_y
    best_margin_diff = float('inf')

    # Drop exactly 2 rows at a time to keep symmetry ODD
    for test_y in range(max_count_y, 0, -2):
        test_h = item_h + ((test_y - 1) * pitch_y)
        test_margin_y = (sheet_width - test_h) / 2
        
        # How close is the Y margin to the X margin?
        diff = abs(test_margin_y - margin_x)
        
        if diff < best_margin_diff:
            best_margin_diff = diff
            best_count_y = test_y
        else:
            # The gap is getting wider, stop here!
            break

    count_y = best_count_y
    total_h = item_h + ((count_y - 1) * pitch_y)

    return {
        "is_grouped": False, "count_x": count_x, "count_y": count_y,
        "pitch_x": pitch_x, "pitch_y": pitch_y,
        "margin_x": margin_x,
        "margin_y": (sheet_width - total_h) / 2
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

    layout = calculate_layout_params(length, width, hole_w, cfg["spacing"], pattern, cfg.get("grouping"))

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
                    msp.add_lwpolyline([(x,y),(x+hole_w,y),(x+hole_w,y+hole_h),(x,y+hole_h),(x,y)], dxfattribs={"layer":"PATTERN"})
        else:
            x_start = layout["margin_x"] + row_off
            
            # Universal Symmetry - Unchanged!
            current_count = layout["count_x"]
            if row_off > 0:
                current_count -= 1
                
            for c in range(current_count):
                x = x_start + (c * layout["pitch_x"])
                if x + hole_w > length: continue

                if pattern == "square":
                    msp.add_lwpolyline([(x,y),(x+hole_w,y),(x+hole_w,y+hole_h),(x,y+hole_h),(x,y)], dxfattribs={"layer":"PATTERN"})
                elif pattern == "slot":
                    r = hole_h / 2
                    msp.add_line((x+r, y), (x+hole_w-r, y), dxfattribs={"layer":"PATTERN"})
                    msp.add_line((x+r, y+hole_h), (x+hole_w-r, y+hole_h), dxfattribs={"layer":"PATTERN"})
                    msp.add_arc((x+r, y+r), r, 90, 270, dxfattribs={"layer":"PATTERN"})
                    msp.add_arc((x+hole_w-r, y+r), r, 270, 90, dxfattribs={"layer":"PATTERN"})
                elif pattern == "diamond":
                    diag_w = hole_w * math.sqrt(2) 
                    diag_h = hole_h * math.sqrt(2)
                    cx, cy = x + diag_w/2, y + diag_h/2
                    msp.add_lwpolyline([(cx, y), (x+diag_w, cy), (cx, y+diag_h), (x, cy), (cx, y)], dxfattribs={"layer":"PATTERN"})
                elif pattern == "circle":
                    r = hole_w / 2
                    msp.add_circle((x+r, y+r), r, dxfattribs={"layer":"PATTERN"})

        y += layout["pitch_y"]

    doc.saveas(filename)
    with open(filename, "rb") as f:
        return {"status": "ok", "file_name": os.path.basename(filename), "file_base64": base64.b64encode(f.read()).decode()}

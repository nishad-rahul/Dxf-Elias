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
        "grouping": {"col_count": 8, "gap_size": 70.0}
    },
    # DIAMOND: Fixed 5.1mm spacing
    "Check 10x10mm": {"pattern": "diamond", "hole_size": 10, "spacing": 5.1, "offset": "half"},
    "Round hole 10mm": {"pattern": "circle", "hole_diameter": 10, "spacing": 10, "offset": "half"},
    
    # SLOTS: Herx Dimensions
    "Slotted hole 35x10mm": {
        "pattern": "slot", 
        "slot_length": 45.0, 
        "slot_width": 8.5, 
        "spacing": 8.5, 
        "offset": "half"
    },
}

# =========================================================
# Helper: Optimized Count
# =========================================================
def optimize_tight_count(available_length, item_size, pitch, stagger_offset=0):
    # Calculate Max Count based on the WIDEST row (Offset = 0)
    # We remove stagger_offset here because we handle the "Minus 1" logic 
    # explicitly in the drawing loop.
    max_c = math.floor((available_length - item_size - stagger_offset - 34) / pitch) + 1
    return max(1, max_c)

# =========================================================
# Layout Logic
# =========================================================
def calculate_layout_params(sheet_length, sheet_width, item_size, spacing, pattern_type, grouping=None):

    # ---------------------------------------------------------
    # 1. LONG SLOTHOLE (Muster L) - Symmetry Fix
    # ---------------------------------------------------------
    if pattern_type == "slot":
        SLOT_L = 45.0
        SLOT_H = 8.5
        PITCH_Y = 17.0
        
        # Rubber band logic (8.5mm to 12.0mm gap)
        best_gap = 8.5
        for test_gap in [x * 0.1 for x in range(85, 121)]:
            test_pitch = SLOT_L + test_gap
            
            # Count based on MAIN ROW (Widest)
            count = math.floor((sheet_length - 36 - SLOT_L) / test_pitch) + 1
            total_w = SLOT_L + (count - 1) * test_pitch
            margin = (sheet_length - total_w) / 2
            
            if 18.0 <= margin <= 27.0:
                best_gap = test_gap
                break 

        PITCH_X = SLOT_L + best_gap
        
        # Final Calculations
        count_x = math.floor((sheet_length - 36 - SLOT_L) / PITCH_X) + 1
        count_y = math.floor((sheet_width - 36 - SLOT_H) / PITCH_Y) + 1
        
        # Center grid based on MAIN ROW
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
    # 2. STANDARD LOGIC (Diamond, Square, Circle)
    # ---------------------------------------------------------
    if pattern_type == "diamond":
        # Pitch calculated on Diagonal
        pitch_x = (item_size + spacing) * math.sqrt(2)
        pitch_y = pitch_x / 2
        stagger_x = pitch_x / 2
        bounding_size = item_size * math.sqrt(2)
    else:
        pitch_x = item_size + spacing
        pitch_y = item_size + spacing
        stagger_x = (pitch_x / 2)
        bounding_size = item_size

    if grouping:
        base_gap = grouping["gap_size"]
        best_col_count, best_margin = 8, 999
        for c in range(8, 100):
            g_w = (c * item_size) + ((c - 1) * spacing)
            g_stride = g_w + base_gap
            n_g = max(1, math.floor((sheet_length + base_gap) / g_stride))
            pat_w = (n_g * g_w) + ((n_g - 1) * base_gap)
            margin = (sheet_length - pat_w) / 2
            if 20 <= margin <= 50:
                best_col_count, best_margin = c, margin
                break
        
        g_w = (best_col_count * item_size) + ((best_col_count - 1) * spacing)
        n_g = max(1, math.floor((sheet_length + base_gap) / (g_w + base_gap)))
        total_w = (n_g * g_w) + ((n_g - 1) * base_gap)
        count_y = optimize_tight_count(sheet_width, item_size, pitch_y)
        total_h = item_size + ((count_y - 1) * pitch_y)
        
        return {
            "is_grouped": True, "num_groups": n_g, "cols_per_group": best_col_count,
            "group_stride": g_w + base_gap, "pitch_x": pitch_x, "pitch_y": pitch_y,
            "margin_x": (sheet_length - total_w) / 2, "margin_y": (sheet_width - total_h) / 2, "count_y": count_y
        }

    # Standard Count based on MAIN ROW (Offset 0)
    count_x = optimize_tight_count(sheet_length, bounding_size, pitch_x, 0)
    item_h = bounding_size
    count_y = optimize_tight_count(sheet_width, item_h, pitch_y)

    total_w = bounding_size + ((count_x - 1) * pitch_x)
    total_h = item_h + ((count_y - 1) * pitch_y)

    return {
        "is_grouped": False, "count_x": count_x, "count_y": count_y,
        "pitch_x": pitch_x, "pitch_y": pitch_y,
        "margin_x": (sheet_length - total_w) / 2,
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
    
    # 🆕 CORRECTED OUTLINE: 3mm Radius with Perfect 0.4142 Bulge
    R = 3.0
    L, W = length, final_width
    BULGE = 0.41421356 # tan(22.5) for 90 degree arc
    points = [
        (L-R, 0, 0, 0, BULGE), (L, R, 0, 0, 0), (L, W-R, 0, 0, BULGE), (L-R, W, 0, 0, 0),
        (R, W, 0, 0, BULGE), (0, W-R, 0, 0, 0), (0, R, 0, 0, BULGE), (R, 0, 0, 0, 0)
    ]
    msp.add_lwpolyline(points, format="xyseb", dxfattribs={"layer": "OUTLINE", "closed": True})
    
    if "PATTERN" not in doc.layers: doc.layers.new(name="PATTERN")

    y = layout["margin_y"]
    for row in range(layout["count_y"]):
        # Offset Logic
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
            
            # 🆕 SYMMETRY FIX: Reduce count by 1 for Odd (Staggered) rows in Slots AND Diamonds
            # "Last second column" logic: Stop loop at N-1
            current_count = layout["count_x"]
            if (pattern == "slot" or pattern == "diamond") and row_off > 0:
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
                    # CORRECT DIAMOND SIZING
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

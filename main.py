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
    "Check 10x10mm": {"pattern": "diamond", "hole_size": 10, "spacing": 5.1, "offset": "half"},
    "Round hole 10mm": {"pattern": "circle", "hole_diameter": 10, "spacing": 10, "offset": "half"},
    # 🆕 UPDATED: Precise 40x8.5mm Slot Configuration
    "Slotted hole 35x10mm": {
        "pattern": "slot", 
        "slot_length": 40.0, 
        "slot_width": 8.5, 
        "spacing": 8.5,    
        "offset": "half"
    },
}

# =========================================================
# Helper: Optimized Tight Packing (Target 18-27mm)
# =========================================================
def get_optimized_count(available, item, pitch, stagger=0):
    """Finds the count that forces the margin into the 18-27mm range."""
    best_count = 1
    # Test counts from 1 up to a reasonable limit
    for c in range(1, 500):
        visual_w = item + ((c - 1) * pitch) + stagger
        margin = (available - visual_w) / 2
        if margin < 18.0:
            break  # Too tight, stop at previous count
        best_count = c
    return best_count

# =========================================================
# Layout Logic (Strictly Isolated)
# =========================================================
def calculate_layout_params(sheet_length, sheet_width, item_size, spacing, pattern_type, grouping=None):
    # 1. Standard Pitch Calculations
    if pattern_type == "diamond":
        pitch_x = (item_size + spacing) * math.sqrt(2)
        pitch_y = pitch_x / 2
        stagger_x = pitch_x / 2
        bounding_size = item_size * math.sqrt(2)
        item_h = bounding_size
    elif pattern_type == "slot":
        pitch_x = 40.0 + 8.5  # Fixed Horizontal Pitch for Slots
        pitch_y = 25.0        # 🆕 Fixed Vertical Pitch for Slots
        stagger_x = pitch_x / 2
        bounding_size = 40.0
        item_h = 8.5
    else:
        # Squares / Circles
        pitch_x = item_size + spacing
        pitch_y = item_size + spacing
        stagger_x = (pitch_x / 2)
        bounding_size = item_size
        item_h = item_size

    # 2. Q+ Specific Optimization (Flexible 65-70mm Gap)
    if grouping:
        best_col_count = 8
        # Aggressive search for Q+ to hit the 18-27mm margin
        for c in range(8, 150):
            for gap in [x * 0.5 for x in range(130, 141)]: # 65.0 - 70.0
                g_w = (c * item_size) + ((c - 1) * spacing)
                g_stride = g_w + gap
                n_g = max(1, math.floor((sheet_length + gap - 36) / g_stride))
                pat_w = (n_g * g_w) + ((n_g - 1) * gap)
                margin = (sheet_length - pat_w) / 2
                if 18 <= margin <= 27:
                    return {
                        "is_grouped": True, "num_groups": n_g, "cols_per_group": c,
                        "group_stride": g_stride, "pitch_x": pitch_x, "pitch_y": pitch_y,
                        "margin_x": margin, 
                        "margin_y": (sheet_width - ((get_optimized_count(sheet_width, item_h, pitch_y) - 1) * pitch_y + item_h)) / 2, 
                        "count_y": get_optimized_count(sheet_width, item_h, pitch_y)
                    }
        # Fallback if no perfect fit
        grouping_layout = {"is_grouped": True, "num_groups": 1, "cols_per_group": 8, "group_stride": 80.0} # etc

    # 3. Standard Variants (Slot, Diamond, Circle, Square)
    count_x = get_optimized_count(sheet_length, bounding_size, pitch_x, stagger_x)
    count_y = get_optimized_count(sheet_width, item_h, pitch_y)

    total_w = bounding_size + ((count_x - 1) * pitch_x) + stagger_x
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
    length, width = float(payload.get("length", 1000)), float(payload.get("width", 500))
    bent_top = payload.get("bent_top", False)
    
    # Precise Size handling
    hole_w = 40.0 if pattern == "slot" else cfg.get("hole_size", 10)
    hole_h = 8.5 if pattern == "slot" else hole_w

    layout = calculate_layout_params(length, width, hole_w, cfg["spacing"], pattern, cfg.get("grouping"))
    final_width = width + 5.1 if bent_top else width

    os.makedirs("output_dxf", exist_ok=True)
    filename = f"output_dxf/{customer}_{int(length)}x{final_width}.dxf"
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    doc.layers.new(name="OUTLINE")
    doc.layers.new(name="PATTERN")

    # Draw Outline
    msp.add_lwpolyline([(0,0), (length,0), (length, final_width), (0, final_width), (0,0)], dxfattribs={"layer": "OUTLINE"})

    # Draw Pattern
    y = layout["margin_y"]
    for row in range(layout["count_y"]):
        if layout["is_grouped"]:
            for g in range(layout["num_groups"]):
                g_start = layout["margin_x"] + (g * layout["group_stride"])
                for c in range(layout["cols_per_group"]):
                    x = g_start + (c * layout["pitch_x"])
                    msp.add_lwpolyline([(x,y),(x+hole_w,y),(x+hole_w,y+hole_h),(x,y+hole_h),(x,y)], dxfattribs={"layer":"PATTERN"})
        else:
            row_off = (layout["pitch_x"] / 2) if cfg["offset"] == "half" and row % 2 != 0 else 0
            x_start = layout["margin_x"] + row_off
            for c in range(layout["count_x"]):
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
                    cx, cy = x + hole_w/2, y + hole_h/2
                    msp.add_lwpolyline([(cx, y), (x+hole_w, cy), (cx, y+hole_h), (x, cy), (cx, y)], dxfattribs={"layer":"PATTERN"})
                elif pattern == "circle":
                    r = hole_w / 2
                    msp.add_circle((x+r, y+r), r, dxfattribs={"layer":"PATTERN"})

        y += layout["pitch_y"]

    doc.saveas(filename)
    with open(filename, "rb") as f:
        return {"status": "ok", "file_name": os.path.basename(filename), "file_base64": base64.b64encode(f.read()).decode()}

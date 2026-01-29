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
    "Slotted hole 35x10mm": {
        "pattern": "slot", 
        "slot_length": 45.0, # Updated to match Herx files (was 40.0)
        "slot_width": 8.5, 
        "spacing": 8.5, 
        "offset": "half"
    },
}

# =========================================================
# Layout Logic (Herx Replication)
# =========================================================
def calculate_layout_params(sheet_length, sheet_width, item_size, spacing, pattern_type):
    
    # ---------------------------------------------------------
    # 1. HERX LOGIC FOR SLOTS
    # ---------------------------------------------------------
    if pattern_type == "slot":
        # Dimensions from Herx Analysis
        SLOT_L = 45.0      # Straight 36.5 + 2*r (4.25) = 45.0
        SLOT_H = 8.5
        PITCH_Y = 17.0     # Fixed Vertical Pitch from Herx_2
        
        # Horizontal Logic: "Rubber Band" Gap
        # Target gap is 8.5, but we search 7.0mm to 10.0mm to find equal margins
        best_gap = 8.5
        best_margin_diff = 999.0
        
        # Iterate to find the gap that centers the pattern perfectly
        # We check gaps in 0.1mm increments
        for test_gap in [x * 0.1 for x in range(70, 101)]: # 7.0mm to 10.0mm
            test_pitch = SLOT_L + test_gap
            count = math.floor((sheet_length - 36 - SLOT_L) / test_pitch) + 1
            
            # Check staggering margin
            # Even row width: SLOT_L + (count-1)*pitch
            # Odd row width (staggered): SLOT_L + (count-1)*pitch + (pitch/2)
            # We need the block to fit centered
            
            total_w = SLOT_L + (count - 1) * test_pitch
            margin = (sheet_length - total_w) / 2
            
            # We prefer a gap that lands us closest to the 22-25mm margin sweet spot
            if 18.0 <= margin <= 27.0:
                best_gap = test_gap
                break # Found a valid gap
        
        GAP_X = best_gap
        PITCH_X = SLOT_L + GAP_X
        
        # Recalculate with best gap
        count_x = math.floor((sheet_length - 36 - SLOT_L) / PITCH_X) + 1
        count_y = math.floor((sheet_width - 36 - SLOT_H) / PITCH_Y) + 1
        
        total_w = SLOT_L + (count_x - 1) * PITCH_X
        total_h = SLOT_H + (count_y - 1) * PITCH_Y
        
        margin_x = (sheet_length - total_w) / 2
        margin_y = (sheet_width - total_h) / 2
        
        return {
            "pattern": "slot",
            "count_x": count_x,
            "count_y": count_y,
            "pitch_x": PITCH_X,
            "pitch_y": PITCH_Y,
            "margin_x": margin_x,
            "margin_y": margin_y,
            "hole_w": SLOT_L,
            "hole_h": SLOT_H
        }

    # ---------------------------------------------------------
    # 2. STANDARD LOGIC FOR OTHERS
    # ---------------------------------------------------------
    pitch_x = item_size + spacing
    pitch_y = item_size + spacing
    if pattern_type == "diamond":
        pitch_x = (item_size + spacing) * math.sqrt(2)
        pitch_y = pitch_x / 2

    count_x = math.floor((sheet_length - 34 - item_size) / pitch_x) + 1
    count_y = math.floor((sheet_width - 34 - item_size) / pitch_y) + 1
    
    total_w = item_size + (count_x - 1) * pitch_x
    total_h = item_size + (count_y - 1) * pitch_y

    return {
        "pattern": "other",
        "count_x": count_x,
        "count_y": count_y,
        "pitch_x": pitch_x,
        "pitch_y": pitch_y,
        "margin_x": (sheet_length - total_w) / 2,
        "margin_y": (sheet_width - total_h) / 2,
        "hole_w": item_size,
        "hole_h": item_size
    }

# =========================================================
# DXF Generator Endpoint
# =========================================================
@app.post("/generate_dxf")
async def generate_dxf(payload: dict = Body(...)):
    if isinstance(payload, list): payload = payload[0]
    raw_pattern = payload.get("pattern", "Squares 10x10mm")
    cfg = PATTERN_MAP.get(raw_pattern, PATTERN_MAP["Squares 10x10mm"])
    pattern_type = cfg["pattern"]

    length = float(payload.get("length", 1400))
    width = float(payload.get("width", 500))
    customer = str(payload.get("customer", "Standard")).replace(" ", "_")
    bent_top = payload.get("bent_top", False)

    layout = calculate_layout_params(length, width, cfg.get("hole_size", 10), cfg.get("spacing", 10), pattern_type)
    final_width = width + 5.1 if bent_top else width

    os.makedirs("output_dxf", exist_ok=True)
    filename = f"output_dxf/{customer}_{int(length)}x{final_width}.dxf"
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    doc.layers.new(name="OUTLINE")
    doc.layers.new(name="PATTERN")

    msp.add_lwpolyline([(0,0), (length,0), (length, final_width), (0, final_width), (0,0)], dxfattribs={"layer": "OUTLINE"})

    hole_w, hole_h = layout["hole_w"], layout["hole_h"]
    r = hole_h / 2
    
    for row in range(layout["count_y"]):
        y = layout["margin_y"] + (row * layout["pitch_y"])
        
        # Stagger Logic
        is_odd = (row % 2 != 0)
        
        if pattern_type == "slot":
            row_offset = (layout["pitch_x"] / 2) if is_odd else 0
        else:
            row_offset = (layout["pitch_x"] / 2) if cfg.get("offset") == "half" and is_odd else 0
        
        # Herx Safety: Staggered rows have one less slot to maintain symmetry
        current_count = layout["count_x"]
        if is_odd and pattern_type == "slot":
             current_count -= 1
        
        for c in range(current_count):
            x = layout["margin_x"] + row_offset + (c * layout["pitch_x"])
            
            # Boundary Check
            if x + hole_w > length: continue

            if pattern_type == "slot":
                msp.add_line((x+r, y), (x+hole_w-r, y), dxfattribs={"layer":"PATTERN"})
                msp.add_line((x+r, y+hole_h), (x+hole_w-r, y+hole_h), dxfattribs={"layer":"PATTERN"})
                msp.add_arc((x+r, y+r), r, 90, 270, dxfattribs={"layer":"PATTERN"})
                msp.add_arc((x+hole_w-r, y+r), r, 270, 90, dxfattribs={"layer":"PATTERN"})
            elif pattern_type == "square":
                msp.add_lwpolyline([(x,y),(x+hole_w,y),(x+hole_w,y+hole_h),(x,y+hole_h),(x,y)], dxfattribs={"layer":"PATTERN"})
            elif pattern_type == "diamond":
                cx, cy = x + hole_w/2, y + hole_h/2
                msp.add_lwpolyline([(cx, y), (x+hole_w, cy), (cx, y+hole_h), (x, cy), (cx, y)], dxfattribs={"layer":"PATTERN"})
            elif pattern_type == "circle":
                msp.add_circle((x+r, y+r), r, dxfattribs={"layer":"PATTERN"})

    doc.saveas(filename)
    with open(filename, "rb") as f:
        return {"status": "ok", "file_name": os.path.basename(filename), "file_base64": base64.b64encode(f.read()).decode()}

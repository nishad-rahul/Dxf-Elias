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
        "slot_length": 40.0, 
        "slot_width": 8.5, 
        "spacing": 8.5,    
        "offset": "half"
    },
}

def solve_best_fit(available, item_w, min_gap, max_gap):
    """Finds perfect gap to hit 18-27mm margins."""
    for gap in [x * 0.1 for x in range(int(min_gap*10), int(max_gap*10) + 1)]:
        pitch = item_w + gap
        count = math.floor((available - 36 - item_w) / pitch) + 1
        margin = (available - (item_w + (count - 1) * pitch)) / 2
        if 18.0 <= margin <= 27.0:
            return count, margin, gap
    p = item_w + min_gap
    c = math.floor((available - 36 - item_w) / p) + 1
    return c, (available - (item_w + (c-1)*p))/2, min_gap

@app.post("/generate_dxf")
async def generate_dxf(payload: dict = Body(...)):
    if isinstance(payload, list): payload = payload[0]
    raw_pattern = payload.get("pattern", "Squares 10x10mm")
    cfg = PATTERN_MAP.get(raw_pattern, PATTERN_MAP["Squares 10x10mm"])
    pattern = cfg["pattern"]

    length = float(payload.get("length", 1400))
    width = float(payload.get("width", 500))
    customer = str(payload.get("customer", "Standard")).replace(" ", "_")
    bent_top = payload.get("bent_top", False)
    
    # 🆕 EXACT HERX STANDARDS
    hole_w = 40.0 if pattern == "slot" else 10.0
    hole_h = 8.5 if pattern == "slot" else 10.0
    # 17mm pitch creates the 25.5mm vertical 'clearance' you requested
    pitch_y = 17.0 if pattern == "slot" else 20.0 

    # 1. HORIZONTAL SOLVING
    count_even, margin_even, gap_x = solve_best_fit(length, hole_w, 8.5, 14.0)
    pitch_x = hole_w + gap_x
    
    # Independent Centering for Odd Rows (Prevents Right Margin Crash)
    count_odd = count_even - 1
    margin_odd = (length - (hole_w + (count_odd - 1) * pitch_x)) / 2

    # 2. VERTICAL SOLVING
    count_y = math.floor((width - 36 - hole_h) / pitch_y) + 1
    margin_y = (width - (hole_h + (count_y - 1) * pitch_y)) / 2

    final_width = width + 5.1 if bent_top else width

    os.makedirs("output_dxf", exist_ok=True)
    filename = f"output_dxf/{customer}_{int(length)}x{final_width}.dxf"
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    doc.layers.new(name="OUTLINE")
    doc.layers.new(name="PATTERN")

    # Draw Outline
    msp.add_lwpolyline([(0,0), (length,0), (length, final_width), (0, final_width), (0,0)], dxfattribs={"layer": "OUTLINE"})

    # 3. DRAWING LOOP
    r = hole_h / 2
    for row in range(count_y):
        y_pos = margin_y + (row * pitch_y)
        
        is_odd = (row % 2 != 0)
        current_x = margin_odd if is_odd else margin_even
        current_count = count_odd if is_odd else count_even

        for c in range(current_count):
            x = current_x + (c * pitch_x)
            
            # Precise Slot Geometry
            msp.add_line((x+r, y_pos), (x+hole_w-r, y_pos), dxfattribs={"layer":"PATTERN"})
            msp.add_line((x+r, y_pos+hole_h), (x+hole_w-r, y_pos+hole_h), dxfattribs={"layer":"PATTERN"})
            msp.add_arc((x+r, y_pos+r), r, 90, 270, dxfattribs={"layer":"PATTERN"})
            msp.add_arc((x+hole_w-r, y_pos+r), r, 270, 90, dxfattribs={"layer":"PATTERN"})

    doc.saveas(filename)
    with open(filename, "rb") as f:
        return {"status": "ok", "file_name": os.path.basename(filename), "file_base64": base64.b64encode(f.read()).decode()}

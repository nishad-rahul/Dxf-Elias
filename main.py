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
    # Precise 40x8.5mm Slot Configuration
    "Slotted hole 35x10mm": {
        "pattern": "slot", 
        "slot_length": 40.0, 
        "slot_width": 8.5, 
        "spacing": 8.5,    
        "offset": "half"
    },
}

# =========================================================
# Helper: Optimized Solver (Target 18-27mm)
# =========================================================
def solve_layout(available, item, min_gap, max_gap, stagger=0.0):
    """
    Finds the best count and gap to hit the 18-27mm margin standard.
    """
    for gap in [x * 0.1 for x in range(int(min_gap*10), int(max_gap*10) + 1)]:
        pitch = item + gap
        for count in range(1, 1000):
            used_width = item + (count - 1) * pitch + stagger
            margin = (available - used_width) / 2
            if margin < 18.0:
                break
            if 18.0 <= margin <= 27.0:
                return count, margin, gap
    return None

# =========================================================
# Layout Logic
# =========================================================
def calculate_layout_params(sheet_length, sheet_width, item_size, spacing, pattern_type, grouping=None):
    # 1. Specialized Logic for Slotted Holes (Longholes)
    if pattern_type == "slot":
        # Flex gap from 8.5mm to 13.0mm to fix the 41mm margin error
        x_sol = solve_layout(sheet_length, 40.0, 8.5, 13.0, (40.0+8.5)/2)
        # Vertical pitch is fixed at 25mm
        y_sol = solve_layout(sheet_width, 8.5, 16.5, 16.5) # 16.5 gap + 8.5 item = 25 pitch
        
        if x_sol and y_sol:
            return {
                "is_grouped": False, "count_x": x_sol[0], "count_y": y_sol[0],
                "pitch_x": 40.0 + x_sol[2], "pitch_y": 25.0,
                "margin_x": x_sol[1], "margin_y": y_sol[1]
            }

    # 2. Logic for Other Standard Patterns (Diamonds, Circles, Squares)
    if pattern_type == "diamond":
        pitch_x = (item_size + spacing) * math.sqrt(2)
        pitch_y = pitch_x / 2
        stagger_x = pitch_x / 2
        bounding_size = item_size * math.sqrt(2)
        item_h = bounding_size
    else:
        pitch_x = item_size + spacing
        pitch_y = item_size + spacing
        stagger_x = pitch_x / 2
        bounding_size = item_size
        item_h = item_size

    # Standard packing optimization for non-slot variants
    # Note: Q+ grouping logic is omitted here as requested to focus on Longhole
    count_x = max(1, math.floor((sheet_length - bounding_size - stagger_x - 36) / pitch_x) + 1)
    count_y = max(1, math.floor((sheet_width - item_h - 36) / pitch_y) + 1)
    
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
    length = float(payload.get("length", 1000))
    width = float(payload.get("width", 500))
    bent_top = payload.get("bent_top", False)
    
    # Use exact dimensions for Longholes
    hole_w = 40.0 if pattern == "slot" else cfg.get("hole_size", 10)
    hole_h = 8.5 if pattern == "slot" else hole_w

    layout = calculate_layout_params(length, width, hole_w, cfg["spacing"], pattern)
    
    # Bending extension logic remains unchanged
    final_width = width + 5.1 if bent_top else width

    os.makedirs("output_dxf", exist_ok=True)
    filename = f"output_dxf/{customer}_{int(length)}x{final_width}.dxf"
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    doc.layers.new(name="OUTLINE")
    doc.layers.new(name="PATTERN")

    # Draw Outline
    msp.add_lwpolyline([(0,0), (length,0), (length, final_width), (0, final_width), (0,0)], dxfattribs={"layer": "OUTLINE"})

    # Draw Pattern Loop
    y = layout["margin_y"]
    for row in range(layout["count_y"]):
        # Centered Row Offset logic
        row_off = (layout["pitch_x"] / 2) if cfg.get("offset") == "half" and row % 2 != 0 else 0
        x_start = layout["margin_x"] + row_off
        
        for c in range(layout["count_x"]):
            x = x_start + (c * layout["pitch_x"])
            
            # Boundary safety check
            if x + hole_w > length - 15.0: continue
            
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

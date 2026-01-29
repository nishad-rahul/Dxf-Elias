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
        "spacing": 8.5,     # Hardcoded horizontal gap
        "offset": "half"
    },
}

# =========================================================
# Layout Logic (Hardcoded Spacing)
# =========================================================
def calculate_layout_params(sheet_length, sheet_width, item_size, spacing, pattern_type, grouping=None):
    
    # 1. HARDCODED LOGIC FOR SLOTS
    if pattern_type == "slot":
        # Fixed Dimensions
        SLOT_L = 40.0
        SLOT_H = 8.5
        GAP_X = 8.5        # Hardcoded: Distance between slots
        PITCH_Y = 25.0     # Hardcoded: Vertical distance center-to-center
        
        PITCH_X = SLOT_L + GAP_X
        
        # Calculate Counts (Safe Fit)
        # We subtract 36mm (18mm per side) to ensure we don't go below min border
        count_x = math.floor((sheet_length - 36 - SLOT_L) / PITCH_X) + 1
        count_y = math.floor((sheet_width - 36 - SLOT_H) / PITCH_Y) + 1
        
        # Calculate Total Pattern Size
        total_w = SLOT_L + (count_x - 1) * PITCH_X
        total_h = SLOT_H + (count_y - 1) * PITCH_Y
        
        # Center the Pattern (Margins will be whatever is left over, e.g. 50-70mm)
        margin_x = (sheet_length - total_w) / 2
        margin_y = (sheet_width - total_h) / 2
        
        return {
            "is_grouped": False,
            "count_x": count_x,
            "count_y": count_y,
            "pitch_x": PITCH_X,
            "pitch_y": PITCH_Y,
            "margin_x": margin_x,
            "margin_y": margin_y
        }

    # 2. STANDARD LOGIC FOR OTHERS (Diamond, Square, Circle)
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

    # Simple centering for others
    count_x = max(1, math.floor((sheet_length - bounding_size - stagger_x - 34) / pitch_x) + 1)
    count_y = max(1, math.floor((sheet_width - item_h - 34) / pitch_y) + 1)
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

    length = float(payload.get("length", 1400))
    width = float(payload.get("width", 500))
    customer = str(payload.get("customer", "Standard")).replace(" ", "_")
    bent_top = payload.get("bent_top", False)
    
    # Hardcoded Slot Sizes
    hole_w = 40.0 if pattern == "slot" else cfg.get("hole_size", 10)
    hole_h = 8.5 if pattern == "slot" else hole_w

    layout = calculate_layout_params(length, width, hole_w, cfg["spacing"], pattern)
    final_width = width + 5.1 if bent_top else width

    os.makedirs("output_dxf", exist_ok=True)
    filename = f"output_dxf/{customer}_{int(length)}x{final_width}.dxf"
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    doc.layers.new(name="OUTLINE")
    doc.layers.new(name="PATTERN")

    msp.add_lwpolyline([(0,0), (length,0), (length, final_width), (0, final_width), (0,0)], dxfattribs={"layer": "OUTLINE"})

    # DRAWING LOOP
    y = layout["margin_y"]
    r = hole_h / 2
    
    for row in range(layout["count_y"]):
        # Offset logic: 
        # For slots, offset is exactly half the pitch (24.25mm)
        # For others, it's calculated dynamically
        if pattern == "slot":
            row_off = (layout["pitch_x"] / 2) if row % 2 != 0 else 0
        else:
            row_off = (layout["pitch_x"] / 2) if cfg.get("offset") == "half" and row % 2 != 0 else 0
            
        x_start = layout["margin_x"] + row_off
        
        # Determine number of items in this row
        # If staggered row pushes last item out of bounds, reduce count by 1
        current_count = layout["count_x"]
        if row_off > 0 and (x_start + (current_count-1)*layout["pitch_x"] + hole_w) > length:
            current_count -= 1
            
        for c in range(current_count):
            x = x_start + (c * layout["pitch_x"])
            
            # Draw
            if pattern == "square":
                msp.add_lwpolyline([(x,y),(x+hole_w,y),(x+hole_w,y+hole_h),(x,y+hole_h),(x,y)], dxfattribs={"layer":"PATTERN"})
            elif pattern == "slot":
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

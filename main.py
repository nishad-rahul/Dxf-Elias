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
    "Squares 10x10mm": {
        "pattern": "square",
        "hole_size": 10,
        "spacing": 10, 
        "offset": "half",
    },
    # 🆕 NEW Q+ PATTERN LOGIC
    "Squares Grouped": {
        "pattern": "square",
        "hole_size": 10,
        "spacing": 10,
        "offset": "half",
        # Grouping Logic: Draw for 110mm (approx 6 cols), then skip 70mm
        "grouping": {
            "fill_width": 110.0, 
            "gap_width": 70.0
        }
    },
    "Check 10x10mm": {
        "pattern": "diamond",
        "hole_size": 10, 
        "spacing": 5.1,    # Bridge gap 5.1mm
        "offset": "half",  # Staggered
    },
    "Round hole 10mm": {
        "pattern": "circle",
        "hole_diameter": 10,
        "spacing": 10,
        "offset": "half",
    },
    "Slotted hole 35x10mm": {
        "pattern": "slot",
        "slot_length": 35,
        "slot_width": 10,
        "spacing": 10,
        "offset": "half", 
    },
}

# =========================================================
# Helper: Rounded rectangle
# =========================================================
def draw_rounded_rectangle(msp, x, y, w, h, r, layer):
    if r <= 0:
        msp.add_lwpolyline(
            [(x,y),(x+w,y),(x+w,y+h),(x,y+h),(x,y)],
            dxfattribs={"layer": layer}
        )
        return
    
    msp.add_line((x+r, y), (x+w-r, y), dxfattribs={"layer": layer})
    msp.add_line((x+w, y+r), (x+w, y+h-r), dxfattribs={"layer": layer})
    msp.add_line((x+w-r, y+h), (x+r, y+h), dxfattribs={"layer": layer})
    msp.add_line((x, y+h-r), (x, y+r), dxfattribs={"layer": layer})
    
    msp.add_arc((x+w-r, y+r), r, 270, 360, dxfattribs={"layer": layer})
    msp.add_arc((x+w-r, y+h-r), r, 0, 90, dxfattribs={"layer": layer})
    msp.add_arc((x+r, y+h-r), r, 90, 180, dxfattribs={"layer": layer})
    msp.add_arc((x+r, y+r), r, 180, 270, dxfattribs={"layer": layer})

# =========================================================
# Layout Logic
# =========================================================
def calculate_layout_params(sheet_length, sheet_width, item_size, target_gap, pattern_type):
    TARGET_MIN_MARGIN = 17.0 
    
    # 1. Calculate Pitch
    if pattern_type == "diamond":
        pitch_x = (item_size + target_gap) * math.sqrt(2)
        pitch_y = pitch_x / 2
        stagger_x = pitch_x / 2
        bounding_size = item_size * math.sqrt(2)
    else:
        pitch_x = item_size + target_gap
        pitch_y = item_size + target_gap 
        stagger_x = (pitch_x / 2)
        bounding_size = item_size

    # 2. Calculate Counts
    usable_x = sheet_length - (2 * TARGET_MIN_MARGIN)
    usable_y = sheet_width - (2 * TARGET_MIN_MARGIN)
    
    safe_width_allowance = usable_x - bounding_size - stagger_x
    if safe_width_allowance < 0: count_x = 0
    else: count_x = math.floor(safe_width_allowance / pitch_x) + 1
    
    safe_height_allowance = usable_y - bounding_size
    if safe_height_allowance < 0: count_y = 0
    else: count_y = math.floor(safe_height_allowance / pitch_y) + 1

    if count_x <= 0 or count_y <= 0:
        return 0, 0, 0, 0, sheet_length/2, sheet_width/2

    # 3. Calculate Margins
    total_pattern_w = bounding_size + ((count_x - 1) * pitch_x) + stagger_x
    total_pattern_h = bounding_size + ((count_y - 1) * pitch_y)

    margin_x = (sheet_length - total_pattern_w) / 2
    margin_y = (sheet_width - total_pattern_h) / 2
    
    return count_x, count_y, pitch_x, pitch_y, margin_x, margin_y

# =========================================================
# DXF Generator Endpoint
# =========================================================
@app.post("/generate_dxf")
async def generate_dxf(payload: dict = Body(...)):
    if isinstance(payload, list):
        payload = payload[0]

    raw_pattern = payload.get("pattern", "Squares 10x10mm")
    # Fallback to standard squares if not found
    cfg = PATTERN_MAP.get(raw_pattern, PATTERN_MAP["Squares 10x10mm"])
    pattern = cfg["pattern"]

    customer = str(payload.get("customer", "Variant_A")).replace(" ", "_")
    length = float(payload.get("length", 500))
    width = float(payload.get("width", 300))
    corner_radius = float(payload.get("corner_radius", 5))

    spacing = cfg["spacing"]
    offset_mode = cfg["offset"]
    
    # 🆕 Extract grouping config if it exists (For Q+)
    grouping = cfg.get("grouping", None)

    # ============================
    # 1. Determine Base Hole Size
    # ============================
    hole_base_size = 10
    hole_w, hole_h = 10, 10 

    if pattern == "square" or pattern == "diamond":
        hole_base_size = cfg.get("hole_size", 10)
    elif pattern == "circle":
        hole_base_size = cfg.get("hole_diameter", 10)
    elif pattern == "slot":
        hole_base_size = cfg.get("slot_length", 35)
        hole_w = cfg.get("slot_length", 35)
        hole_h = cfg.get("slot_width", 10)

    # ============================
    # 2. Calculate Layout
    # ============================
    cols, rows, pitch_x, pitch_y, margin_x, margin_y = calculate_layout_params(
        length, width, hole_base_size, spacing, pattern
    )
    
    if pattern == "diamond":
        bbox_size = hole_base_size * math.sqrt(2)
        hole_w, hole_h = bbox_size, bbox_size

    # ============================
    # 3. Generate DXF
    # ============================
    os.makedirs("output_dxf", exist_ok=True)
    filename = f"output_dxf/{customer}_{pattern}.dxf"
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    doc.layers.new(name="OUTLINE")
    doc.layers.new(name="PATTERN")

    draw_rounded_rectangle(msp, 0, 0, length, width, corner_radius, "OUTLINE")

    y = margin_y
    row = 0
    
    while row < rows:
        current_offset = 0
        if offset_mode == "half" and row % 2 != 0:
            current_offset = pitch_x / 2
        
        # Determine X start
        x = margin_x + current_offset
        col = 0

        while col < cols:
            
            # =====================================================
            # 🆕 LOGIC: SKIP ZONE (For Q+ Pattern)
            # =====================================================
            should_draw = True
            
            if grouping:
                # Calculate relative position from the START of the pattern
                rel_x = x - margin_x
                
                # Full cycle = Filled Width + Gap Width
                cycle = grouping["fill_width"] + grouping["gap_width"]
                
                # Where are we in the current cycle?
                pos_in_cycle = rel_x % cycle
                
                # If we are past the fill width, we are in the gap. SKIP.
                # (We add a tiny buffer to avoid floating point edge cases)
                if pos_in_cycle > (grouping["fill_width"] + 1): 
                    should_draw = False

            if should_draw:
                if pattern == "square":
                    msp.add_lwpolyline(
                        [(x,y), (x+hole_w,y), (x+hole_w,y+hole_h), (x,y+hole_h), (x,y)],
                        dxfattribs={"layer":"PATTERN"}
                    )
                elif pattern == "diamond":
                    cx, cy = x + hole_w/2, y + hole_h/2
                    msp.add_lwpolyline(
                        [(cx, y), (x+hole_w, cy), (cx, y+hole_h), (x, cy), (cx, y)],
                        dxfattribs={"layer":"PATTERN"}
                    )
                elif pattern == "circle":
                    r = hole_w / 2
                    msp.add_circle((x+r, y+r), r, dxfattribs={"layer":"PATTERN"})
                elif pattern == "slot":
                    r = hole_h / 2
                    msp.add_line((x+r, y+hole_h), (x+hole_w-r, y+hole_h), dxfattribs={"layer": "PATTERN"})
                    msp.add_line((x+r, y), (x+hole_w-r, y), dxfattribs={"layer": "PATTERN"})
                    msp.add_arc((x+r, y+r), r, 90, 270, dxfattribs={"layer": "PATTERN"})
                    msp.add_arc((x+hole_w-r, y+r), r, -90, 90, dxfattribs={"layer": "PATTERN"})

            x += pitch_x
            col += 1

        y += pitch_y
        row += 1

    doc.saveas(filename)
    with open(filename, "rb") as f:
        encoded = base64.b64encode(f.read()).decode()

    return {
        "status": "ok",
        "file_name": os.path.basename(filename),
        "file_base64": encoded,
        "debug": {
             "type": pattern,
             "is_grouped": grouping is not None,
             "margin_x": round(margin_x, 2),
             "margin_y": round(margin_y, 2)
        }
    }

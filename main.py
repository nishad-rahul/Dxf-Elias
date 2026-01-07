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
    "Check 10x10mm": {
        "pattern": "diamond",
        "hole_size": 10, 
        "spacing": 5.1,    # 🆕 UPDATED: Exact 5.1mm bridge gap
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
# Layout Logic: Uniform Margins + Dense Diamond Packing
# =========================================================
def calculate_layout_params(sheet_length, sheet_width, item_size, target_gap, pattern_type):
    """
    Calculates unified layout parameters for both axes to ensure symmetry.
    Special logic for 'diamond' to ensure dense packing and correct bridge width.
    """
    TARGET_MIN_MARGIN = 17.0 
    
    # ---------------------------------------------------------
    # 1. Calculate PITCH (Center-to-Center Distance)
    # ---------------------------------------------------------
    if pattern_type == "diamond":
        # GEOMETRY FIX: For a diamond mesh with a specific "Bridge Width" (gap),
        # the Pitch is the diagonal of the (Size + Gap) square.
        # Pitch = (Side + Gap) * sqrt(2)
        pitch_x = (item_size + target_gap) * math.sqrt(2)
        
        # PACKING FIX: To make it "impact packed", rows must nest.
        # Vertical pitch should be exactly half of horizontal pitch in a standard diamond mesh.
        pitch_y = pitch_x / 2
        
        # Stagger X offset is half the pitch
        stagger_x = pitch_x / 2
        
        # Bounding Box for calculation (Tip-to-Tip size)
        bounding_size = item_size * math.sqrt(2)
        
    else:
        # Standard logic for Square/Circle/Slot
        pitch_x = item_size + target_gap
        pitch_y = item_size + target_gap # Usually square grid base
        
        stagger_x = (pitch_x / 2) # Standard stagger
        bounding_size = item_size # Simple bounding box

    # ---------------------------------------------------------
    # 2. Calculate Counts based on Usable Space
    # ---------------------------------------------------------
    # We strip the safety margin from the sheet
    usable_x = sheet_length - (2 * TARGET_MIN_MARGIN)
    usable_y = sheet_width - (2 * TARGET_MIN_MARGIN)
    
    # X-Axis Count (Visual Width)
    # Formula: (Count-1)*Pitch + BoundingSize + (Stagger if applicable) <= Usable
    # Note: Stagger adds width to the total block only if rows are offset.
    # For Diamond/Half-offset, the visual block is wider by exactly 'stagger_x'.
    
    safe_width_allowance = usable_x - bounding_size - stagger_x
    if safe_width_allowance < 0: count_x = 0
    else: count_x = math.floor(safe_width_allowance / pitch_x) + 1
    
    # Y-Axis Count
    safe_height_allowance = usable_y - bounding_size
    if safe_height_allowance < 0: count_y = 0
    else: count_y = math.floor(safe_height_allowance / pitch_y) + 1

    if count_x <= 0 or count_y <= 0:
        return 0, 0, 0, 0, sheet_length/2, sheet_width/2

    # ---------------------------------------------------------
    # 3. Calculate Exact Margins (Centering)
    # ---------------------------------------------------------
    # Actual total visual width of the pattern block
    total_pattern_w = bounding_size + ((count_x - 1) * pitch_x) + stagger_x
    total_pattern_h = bounding_size + ((count_y - 1) * pitch_y)

    margin_x = (sheet_length - total_pattern_w) / 2
    margin_y = (sheet_width - total_pattern_h) / 2
    
    # ---------------------------------------------------------
    # 4. Enforce "Equal Margins" (Square Frame)
    # ---------------------------------------------------------
    # If you want Top/Bottom to equal Left/Right, we pick the larger margin.
    # However, forcing this might reduce the count in one direction.
    # To be safe and simple: We accept the calculated symmetrical centers.
    # If strictly "Equal All Around" is needed, we'd use max(margin_x, margin_y) 
    # but that might cut off rows. Usually "Centered" is what users mean by "Equal".
    # I will stick to Perfect Centering which guarantees Left=Right and Top=Bottom.
    
    return count_x, count_y, pitch_x, pitch_y, margin_x, margin_y

# =========================================================
# DXF Generator Endpoint
# =========================================================
@app.post("/generate_dxf")
async def generate_dxf(payload: dict = Body(...)):
    if isinstance(payload, list):
        payload = payload[0]

    raw_pattern = payload.get("pattern", "Squares 10x10mm")
    cfg = PATTERN_MAP.get(raw_pattern, PATTERN_MAP["Squares 10x10mm"])
    pattern = cfg["pattern"]

    customer = str(payload.get("customer", "Variant_A")).replace(" ", "_")
    length = float(payload.get("length", 500))
    width = float(payload.get("width", 300))
    corner_radius = float(payload.get("corner_radius", 5))

    spacing = cfg["spacing"]
    offset_mode = cfg["offset"]

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
        # Slot logic uses length for spacing calculations? 
        # Actually slot logic is complex, sticking to simple "spacing" adder for now
        # unless it's diamond.
        hole_base_size = cfg.get("slot_length", 35)
        hole_w = cfg.get("slot_length", 35)
        hole_h = cfg.get("slot_width", 10)

    # ============================
    # 2. Calculate Layout
    # ============================
    cols, rows, pitch_x, pitch_y, margin_x, margin_y = calculate_layout_params(
        length, width, hole_base_size, spacing, pattern
    )
    
    # Recalculate hole bounding box for drawing loop
    if pattern == "diamond":
        # 10mm side -> 14.14mm diagonal width
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
        
        # Stagger logic
        if offset_mode == "half" and row % 2 != 0:
            current_offset = pitch_x / 2
        
        x = margin_x + current_offset
        col = 0

        while col < cols:
            # Draw shapes
            if pattern == "square":
                msp.add_lwpolyline(
                    [(x,y), (x+hole_w,y), (x+hole_w,y+hole_h), (x,y+hole_h), (x,y)],
                    dxfattribs={"layer":"PATTERN"}
                )
            elif pattern == "diamond":
                # Diamond inscribed in bounding box
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
            "pitch_x": round(pitch_x, 2),
            "pitch_y": round(pitch_y, 2),
            "gap_setting": spacing,
            "margin_x": round(margin_x, 2),
            "margin_y": round(margin_y, 2)
        }
    }

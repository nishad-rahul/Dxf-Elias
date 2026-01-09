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
    # 🆕 Q+ PATTERN (Squares Grouped)
    "Squares Grouped": {
        "pattern": "square",
        "hole_size": 10,
        "spacing": 10,
        "offset": "none",   # ⚠️ GRID ALIGNMENT (Single straight line)
        "grouping": {
            "col_count": 8,  # ⚠️ 8 Columns wide
            "gap_size": 70.0 # ⚠️ 70mm Gap between groups
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
        msp.add_lwpolyline([(x,y),(x+w,y),(x+w,y+h),(x,y+h),(x,y)], dxfattribs={"layer": layer})
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
def calculate_layout_params(sheet_length, sheet_width, item_size, spacing, pattern_type, grouping=None):
    TARGET_MIN_MARGIN = 17.0 
    
    # ---------------------------------------
    # 1. Define Standard Pitch
    # ---------------------------------------
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

    # ---------------------------------------
    # 2. Special Logic for GROUPED Patterns (Q+)
    # ---------------------------------------
    if grouping:
        cols_per_group = grouping["col_count"]
        gap_size = grouping["gap_size"]
        
        # Visual Width of ONE group (8 columns + 7 internal gaps)
        group_visual_width = (cols_per_group * item_size) + ((cols_per_group - 1) * spacing)
        
        # Stride = Distance from Start of Group 1 to Start of Group 2
        group_stride = group_visual_width + gap_size
        
        usable_x = sheet_length - (2 * TARGET_MIN_MARGIN)
        
        # How many full groups fit?
        num_groups = math.floor((usable_x + gap_size) / group_stride)
        if num_groups < 1: num_groups = 1 
        
        # Calculate Total Width of the Pattern Block
        total_pattern_w = (num_groups * group_visual_width) + ((num_groups - 1) * gap_size)
        
        # Determine X Margin (Centering)
        margin_x = (sheet_length - total_pattern_w) / 2
        
        # Y-axis behaves like standard square grid
        usable_y = sheet_width - (2 * TARGET_MIN_MARGIN)
        safe_h = usable_y - bounding_size
        count_y = math.floor(safe_h / pitch_y) + 1
        total_pattern_h = bounding_size + ((count_y - 1) * pitch_y)
        margin_y = (sheet_width - total_pattern_h) / 2
        
        return {
            "is_grouped": True,
            "num_groups": num_groups,
            "cols_per_group": cols_per_group,
            "group_stride": group_stride,
            "pitch_x": pitch_x,
            "pitch_y": pitch_y,
            "margin_x": margin_x,
            "margin_y": margin_y,
            "count_y": count_y
        }

    # ---------------------------------------
    # 3. Standard Logic (Non-Grouped)
    # ---------------------------------------
    usable_x = sheet_length - (2 * TARGET_MIN_MARGIN)
    usable_y = sheet_width - (2 * TARGET_MIN_MARGIN)
    
    safe_w = usable_x - bounding_size - stagger_x
    if safe_w < 0: count_x = 0
    else: count_x = math.floor(safe_w / pitch_x) + 1
    
    safe_h = usable_y - bounding_size
    if safe_h < 0: count_y = 0
    else: count_y = math.floor(safe_h / pitch_y) + 1

    total_pattern_w = bounding_size + ((count_x - 1) * pitch_x) + stagger_x
    total_pattern_h = bounding_size + ((count_y - 1) * pitch_y)

    margin_x = (sheet_length - total_pattern_w) / 2
    margin_y = (sheet_width - total_pattern_h) / 2
    
    return {
        "is_grouped": False,
        "count_x": count_x,
        "count_y": count_y,
        "pitch_x": pitch_x,
        "pitch_y": pitch_y,
        "margin_x": margin_x,
        "margin_y": margin_y
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

    customer = str(payload.get("customer", "Variant_A")).replace(" ", "_")
    length = float(payload.get("length", 500))
    width = float(payload.get("width", 300))
    corner_radius = float(payload.get("corner_radius", 5))

    spacing = cfg["spacing"]
    offset_mode = cfg["offset"]
    grouping = cfg.get("grouping", None)

    # 1. Base Hole Size
    hole_w, hole_h = 10, 10 
    hole_base = 10
    if pattern == "square" or pattern == "diamond":
        hole_base = cfg.get("hole_size", 10)
        hole_w, hole_h = hole_base, hole_base
    elif pattern == "circle":
        hole_base = cfg.get("hole_diameter", 10)
        hole_w, hole_h = hole_base, hole_base
    elif pattern == "slot":
        hole_w = cfg.get("slot_length", 35)
        hole_h = cfg.get("slot_width", 10)

    # 2. Calculate Layout
    layout = calculate_layout_params(length, width, hole_base, spacing, pattern, grouping)
    
    if pattern == "diamond":
        bbox = hole_base * math.sqrt(2)
        hole_w, hole_h = bbox, bbox

    # 3. DXF Setup
    os.makedirs("output_dxf", exist_ok=True)
    filename = f"output_dxf/{customer}_{pattern}.dxf"
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    doc.layers.new(name="OUTLINE")
    doc.layers.new(name="PATTERN")

    draw_rounded_rectangle(msp, 0, 0, length, width, corner_radius, "OUTLINE")

    # 4. Drawing Loop
    margin_y = layout["margin_y"]
    pitch_y = layout["pitch_y"]
    pitch_x = layout["pitch_x"]
    count_y = layout["count_y"]
    
    y = margin_y
    row = 0

    while row < count_y:
        row_offset = 0
        if offset_mode == "half" and row % 2 != 0:
            row_offset = pitch_x / 2
        
        # -------------------------------------------------
        # DRAWING STRATEGY
        # -------------------------------------------------
        if layout["is_grouped"]:
            # Q+ Logic: Draw specific columns per group
            num_groups = layout["num_groups"]
            cols_per_group = layout["cols_per_group"]
            group_stride = layout["group_stride"]
            start_x = layout["margin_x"]
            
            for g in range(num_groups):
                group_start_x = start_x + (g * group_stride)
                for c in range(cols_per_group):
                    # No row_offset here because Q+ offset is "none"
                    x = group_start_x + (c * pitch_x)
                    
                    if pattern == "square":
                         msp.add_lwpolyline([(x,y),(x+hole_w,y),(x+hole_w,y+hole_h),(x,y+hole_h),(x,y)], dxfattribs={"layer":"PATTERN"})
        
        else:
            # Standard Logic
            count_x = layout["count_x"]
            x_start = layout["margin_x"] + row_offset
            
            for c in range(count_x):
                x = x_start + (c * pitch_x)
                if x + hole_w > length: continue

                if pattern == "square":
                    msp.add_lwpolyline([(x,y),(x+hole_w,y),(x+hole_w,y+hole_h),(x,y+hole_h),(x,y)], dxfattribs={"layer":"PATTERN"})
                elif pattern == "diamond":
                    cx, cy = x + hole_w/2, y + hole_h/2
                    msp.add_lwpolyline([(cx, y), (x+hole_w, cy), (cx, y+hole_h), (x, cy), (cx, y)], dxfattribs={"layer":"PATTERN"})
                elif pattern == "circle":
                    r = hole_w / 2
                    msp.add_circle((x+r, y+r), r, dxfattribs={"layer":"PATTERN"})
                elif pattern == "slot":
                    r = hole_h / 2
                    msp.add_line((x+r, y+hole_h), (x+hole_w-r, y+hole_h), dxfattribs={"layer": "PATTERN"})
                    msp.add_line((x+r, y), (x+hole_w-r, y), dxfattribs={"layer": "PATTERN"})
                    msp.add_arc((x+r, y+r), r, 90, 270, dxfattribs={"layer": "PATTERN"})
                    msp.add_arc((x+hole_w-r, y+r), r, -90, 90, dxfattribs={"layer": "PATTERN"})

        y += pitch_y
        row += 1

    doc.saveas(filename)
    with open(filename, "rb") as f:
        encoded = base64.b64encode(f.read()).decode()

    return {
        "status": "ok",
        "file_name": os.path.basename(filename),
        "file_base64": encoded
    }

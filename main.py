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
    # Q+ Pattern: 'col_count' is now a starting point/fallback
    "Squares Grouped": {
        "pattern": "square",
        "hole_size": 10,
        "spacing": 10,
        "offset": "none",   
        "grouping": {
            "col_count": 8,   # Default start
            "gap_size": 70.0  # Fixed gap
        }
    },
    "Check 10x10mm": {
        "pattern": "diamond",
        "hole_size": 10, 
        "spacing": 5.1,    
        "offset": "half",  
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
    
    # 1. Define Standard Pitch
    if pattern_type == "diamond":
        pitch_x = (item_size + spacing) * math.sqrt(2)
        pitch_y = pitch_x / 2
        stagger_x = pitch_x / 2
        bounding_size = item_size * math.sqrt(2)
    else:
        # Standard logic
        pitch_x = item_size + spacing
        
        if pattern_type == "slot":
             pitch_y = 10.0 + spacing
        else:
             pitch_y = item_size + spacing

        stagger_x = (pitch_x / 2)
        bounding_size = item_size

    # 2. Q+ Grouped Logic (DYNAMIC OPTIMIZATION)
    if grouping:
        base_gap = grouping["gap_size"]
        
        # --- DYNAMIC COLUMN CALCULATION ---
        # We simulate adding columns (starting from 8) until the margin is ideal (20-50mm)
        best_col_count = 8
        best_margin = 9999
        found_valid = False
        
        # Try a range of column counts (e.g., 8 to 50)
        for c in range(8, 100):
            # Calculate metrics for 'c' columns
            # Group Width = (c * size) + ((c-1) * spacing)
            g_width = (c * item_size) + ((c - 1) * spacing)
            g_stride = g_width + base_gap
            
            # How many groups fit?
            # Available space = Length - SafetyMargin
            # But calculating Margin is easier directly:
            # (N * Width) + ((N-1) * Gap) <= Length
            
            # Calc N groups
            n_groups = math.floor((sheet_length + base_gap) / g_stride)
            if n_groups < 1: n_groups = 1
            
            # Calc Resulting Margin
            pat_width = (n_groups * g_width) + ((n_groups - 1) * base_gap)
            margin = (sheet_length - pat_width) / 2
            
            # Optimization Criteria:
            # 1. Margin MUST be >= 20mm (Hard Limit)
            # 2. Prefer Margin <= 50mm (Soft Limit)
            # 3. If multiple fit, pick closest to 35mm (Sweet Spot)
            
            if margin < 20.0:
                # If margin gets too small, we've added too many columns or groups. 
                # Stop searching if we already found a valid one.
                if found_valid: 
                    break 
                # If we haven't found valid yet, keep going (though increasing col count usually reduces margin, 
                # unless N drops, which spikes margin. So we check all).
            else:
                # Margin is safe (>= 20)
                found_valid = True
                
                # Calculate how close to sweet spot (35mm)
                diff = abs(margin - 35.0)
                
                # If this is better than what we found before, keep it
                # Logic: We start from c=8. If c=8 gives 90mm margin, diff is 55.
                # c=9 gives 60mm margin, diff is 25. Update best.
                # c=10 gives 30mm margin, diff is 5. Update best.
                if diff < abs(best_margin - 35.0):
                    best_margin = margin
                    best_col_count = c
                
                # If we hit a margin that is "good enough" (e.g. 20-50), we could stop early,
                # but checking a few more is safer.
        
        # --- END OPTIMIZATION ---
        
        # Apply the Best Found Configuration
        cols_per_group = best_col_count
        gap_size = base_gap
        
        group_visual_width = (cols_per_group * item_size) + ((cols_per_group - 1) * spacing)
        group_stride = group_visual_width + gap_size
        
        num_groups = math.floor((sheet_length + gap_size) / group_stride)
        if num_groups < 1: num_groups = 1 
        
        total_pattern_w = (num_groups * group_visual_width) + ((num_groups - 1) * gap_size)
        margin_x = (sheet_length - total_pattern_w) / 2
        
        # Y-Axis Logic (Standard)
        usable_y = sheet_width - (2 * TARGET_MIN_MARGIN)
        safe_h = usable_y - bounding_size 
        
        count_y = math.floor((usable_y - 10) / pitch_y) + 1 
        if count_y < 0: count_y = 0

        total_pattern_h = 10 + ((count_y - 1) * pitch_y)
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
            "count_y": count_y,
            "debug_col_count": cols_per_group, # Info for response
            "debug_margin": margin_x
        }

    # 3. Standard Logic (unchanged)
    usable_x = sheet_length - (2 * TARGET_MIN_MARGIN)
    usable_y = sheet_width - (2 * TARGET_MIN_MARGIN)
    
    safe_w = usable_x - bounding_size - stagger_x
    if safe_w < 0: count_x = 0
    else: count_x = math.floor(safe_w / pitch_x) + 1
    
    item_h = 10 if pattern_type == "slot" else bounding_size
    
    safe_h = usable_y - item_h
    if safe_h < 0: count_y = 0
    else: count_y = math.floor(safe_h / pitch_y) + 1

    total_pattern_w = bounding_size + ((count_x - 1) * pitch_x) + stagger_x
    total_pattern_h = item_h + ((count_y - 1) * pitch_y)

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
    
    bent_top = payload.get("bent_top", False)
    
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
        hole_base = cfg.get("slot_length", 35) 
        hole_w = cfg.get("slot_length", 35)
        hole_h = cfg.get("slot_width", 10)

    # ============================================================
    # 2. CALCULATE LAYOUT
    # ============================================================
    layout = calculate_layout_params(length, width, hole_base, spacing, pattern, grouping)
    
    # Bending Logic Adjustment
    final_dxf_width = width
    if bent_top:
        final_dxf_width = width + 5.1

    if pattern == "diamond":
        bbox = hole_base * math.sqrt(2)
        hole_w, hole_h = bbox, bbox

    # 3. DXF Setup
    os.makedirs("output_dxf", exist_ok=True)
    
    # Filename Logic: Name_LengthxWidth.dxf
    l_str = int(length) if length.is_integer() else length
    w_str = int(final_dxf_width) if final_dxf_width.is_integer() else final_dxf_width
    
    filename = f"output_dxf/{customer}_{l_str}x{w_str}.dxf"
    
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    doc.layers.new(name="OUTLINE")
    doc.layers.new(name="PATTERN")

    draw_rounded_rectangle(msp, 0, 0, length, final_dxf_width, corner_radius, "OUTLINE")

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
        
        if layout["is_grouped"]:
            num_groups = layout["num_groups"]
            cols_per_group = layout["cols_per_group"]
            group_stride = layout["group_stride"]
            start_x = layout["margin_x"]
            
            for g in range(num_groups):
                group_start_x = start_x + (g * group_stride)
                for c in range(cols_per_group):
                    x = group_start_x + (c * pitch_x)
                    if pattern == "square":
                         msp.add_lwpolyline([(x,y),(x+hole_w,y),(x+hole_w,y+hole_h),(x,y+hole_h),(x,y)], dxfattribs={"layer":"PATTERN"})
        else:
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
        "file_base64": encoded,
        "debug": {
            "chosen_columns": layout.get("debug_col_count"),
            "final_margin": layout.get("debug_margin")
        }
    }

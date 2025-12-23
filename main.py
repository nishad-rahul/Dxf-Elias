from fastapi import FastAPI, Body
import ezdxf
import os
import base64
from ezdxf import path
from ezdxf.render import forms

app = FastAPI()

# =========================================================
# Pattern normalization (matches n8n input)
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
        "spacing": 10,
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
# DXF Generator Endpoint
# =========================================================
@app.post("/generate_dxf")
async def generate_dxf(payload: dict = Body(...)):
    try:
        # -------------------------------------------------
        # Handle n8n array input
        # -------------------------------------------------
        if isinstance(payload, list):
            payload = payload[0]

        # -------------------------------------------------
        # Normalize pattern
        # -------------------------------------------------
        raw_pattern = payload.get("pattern", "Squares 10x10mm")
        if raw_pattern not in PATTERN_MAP:
            return {"error": f"Unsupported pattern: {raw_pattern}"}

        cfg = PATTERN_MAP[raw_pattern]
        pattern = cfg["pattern"]

        # -------------------------------------------------
        # Dynamic inputs
        # -------------------------------------------------
        customer = str(payload.get("customer", "unknown")).replace(" ", "_")
        length = float(payload.get("length", 500))
        width = float(payload.get("width", 300))
        border = float(payload.get("border", 17))
        corner_radius = float(payload.get("corner_radius", 0))

        spacing = cfg.get("spacing", 10)
        offset_mode = cfg.get("offset", "none")

        hole_size = cfg.get("hole_size", 10)
        hole_diameter = cfg.get("hole_diameter", 10)
        slot_length = cfg.get("slot_length", 35)
        slot_width = cfg.get("slot_width", 10)

        # -------------------------------------------------
        # File setup
        # -------------------------------------------------
        os.makedirs("output_dxf", exist_ok=True)
        filename = f"output_dxf/{customer}_{pattern}.dxf"

        doc = ezdxf.new("R2010")
        doc.units = ezdxf.units.MM
        msp = doc.modelspace()

        doc.layers.new(name="OUTLINE")
        doc.layers.new(name="PATTERN")

        # -------------------------------------------------
        # Outline (rounded rectangle)
        # -------------------------------------------------
        outline_path = forms.rect(length, width, radius=corner_radius)
        outline = path.to_lwpolyline(outline_path, close=True)
        outline.dxf.layer = "OUTLINE"
        msp.add_entity(outline)

        # -------------------------------------------------
        # Pattern bounds
        # -------------------------------------------------
        px1, py1 = border, border
        px2, py2 = length - border, width - border

        y = py1
        row = 0

        # -------------------------------------------------
        # Pattern generation (CRASH-SAFE)
        # -------------------------------------------------
        while y < py2:
            offset_x = hole_size / 2 if offset_mode == "half" and row % 2 else 0
            x = px1 + offset_x

            while x < px2:

                # ---------- SQUARE ----------
                if pattern == "square":
                    s = hole_size
                    if x + s <= px2 and y + s <= py2:
                        msp.add_lwpolyline(
                            [(x,y),(x+s,y),(x+s,y+s),(x,y+s),(x,y)],
                            dxfattribs={"layer":"PATTERN"}
                        )
                    step_x = s
                    step_y = s

                # ---------- DIAMOND ----------
                elif pattern == "diamond":
                    s = hole_size
                    cx, cy = x + s/2, y + s/2
                    if x + s <= px2 and y + s <= py2:
                        msp.add_lwpolyline(
                            [(cx,y),(x+s,cy),(cx,y+s),(x,cy),(cx,y)],
                            dxfattribs={"layer":"PATTERN"}
                        )
                    step_x = s
                    step_y = s

                # ---------- CIRCLE ----------
                elif pattern == "circle":
                    d = hole_diameter
                    r = d / 2
                    if x + d <= px2 and y + d <= py2:
                        msp.add_circle((x+r,y+r), r, dxfattribs={"layer":"PATTERN"})
                    step_x = d
                    step_y = d

                # ---------- SLOT ----------
                elif pattern == "slot":
                    hl, hw = slot_length, slot_width
                    r = hw / 2
                    if x + hl <= px2 and y + hw <= py2:
                        msp.add_line((x+r,y+r),(x+hl-r,y+r), dxfattribs={"layer":"PATTERN"})
                        msp.add_arc((x+r,y+r), r, 90, 270, dxfattribs={"layer":"PATTERN"})
                        msp.add_arc((x+hl-r,y+r), r, -90, 90, dxfattribs={"layer":"PATTERN"})
                    step_x = hl
                    step_y = hw

                else:
                    break

                x += step_x + spacing

            y += step_y + spacing
            row += 1

        # -------------------------------------------------
        # AutoCAD viewport
        # -------------------------------------------------
        doc.set_modelspace_vport(
            center=(length/2, width/2),
            height=width * 1.1
        )

        # -------------------------------------------------
        # Save & return
        # -------------------------------------------------
        doc.saveas(filename)
        with open(filename, "rb") as f:
            encoded = base64.b64encode(f.read()).decode()

        return {
            "status": "ok",
            "file_name": os.path.basename(filename),
            "file_base64": encoded,
            "length_mm": length,
            "width_mm": width,
            "pattern": raw_pattern
        }

    except Exception as e:
        return {
            "error": "DXF generation failed",
            "details": str(e)
        }

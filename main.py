from fastapi import FastAPI, Body
import ezdxf
import os
import base64

app = FastAPI()

# -----------------------------
# Pattern rules (locked format)
# -----------------------------
RULES = {
    "Squares 10x10mm": {
        "type": "square",
        "size": 10,
        "spacing": 10,
        "offset": "half",
    },
    "Check 10x10mm": {
        "type": "diamond",
        "size": 10,
        "spacing": 10,
        "offset": "half",
    },
    "Slotted hole 35x10mm": {
        "type": "slot",
        "length": 35,
        "width": 10,
        "spacing": 10,
        "offset": "half",
    },
    "Round hole 10mm": {
        "type": "circle",
        "diameter": 10,
        "spacing": 10,
        "offset": "half",
    },
}

MARGIN = 17  # matches your examples

# -----------------------------
# DXF Generator
# -----------------------------
@app.post("/generate-dxf")
async def generate_dxf(payload: dict = Body(...)):
    customer = payload.get("customer", "unknown")
    pattern_name = payload.get("pattern", "Squares 10x10mm")
    length = float(payload.get("length", 500))
    width = float(payload.get("width", 300))

    rule = RULES.get(pattern_name, RULES["Squares 10x10mm"])

    os.makedirs("output_dxf", exist_ok=True)
    filename = f"output_dxf/{customer}.dxf"

    # -----------------------------
    # DXF setup (IMPORTANT)
    # -----------------------------
    doc = ezdxf.new("R2010")
    doc.units = ezdxf.units.MM  # critical
    msp = doc.modelspace()

    # Layers (same idea as example DXFs)
    doc.layers.new(name="OUTLINE")
    doc.layers.new(name="PATTERN")

    # -----------------------------
    # Outer frame (exact size)
    # -----------------------------
    msp.add_lwpolyline(
        [
            (0, 0),
            (length, 0),
            (length, width),
            (0, width),
            (0, 0),
        ],
        dxfattribs={"layer": "OUTLINE"},
    )

    # -----------------------------
    # Pattern bounds
    # -----------------------------
    px1 = MARGIN
    py1 = MARGIN
    px2 = length - MARGIN
    py2 = width - MARGIN

    # -----------------------------
    # Pattern generator
    # -----------------------------
    y = py1
    row = 0

    while y < py2:
        offset_x = 0
        if rule.get("offset") == "half" and row % 2 == 1:
            offset_x = rule.get("size", rule.get("diameter", 10)) / 2

        x = px1 + offset_x

        while x < px2:
            t = rule["type"]

            if t == "square":
                s = rule["size"]
                if x + s <= px2 and y + s <= py2:
                    msp.add_lwpolyline(
                        [
                            (x, y),
                            (x + s, y),
                            (x + s, y + s),
                            (x, y + s),
                            (x, y),
                        ],
                        dxfattribs={"layer": "PATTERN"},
                    )

            elif t == "diamond":
                s = rule["size"]
                if x + s <= px2 and y + s <= py2:
                    msp.add_lwpolyline(
                        [
                            (x + s / 2, y),
                            (x + s, y + s / 2),
                            (x + s / 2, y + s),
                            (x, y + s / 2),
                            (x + s / 2, y),
                        ],
                        dxfattribs={"layer": "PATTERN"},
                    )

            elif t == "circle":
                d = rule["diameter"]
                r = d / 2
                if x + d <= px2 and y + d <= py2:
                    msp.add_circle(
                        (x + r, y + r),
                        r,
                        dxfattribs={"layer": "PATTERN"},
                    )

            elif t == "slot":
                hl = rule["length"]
                hw = rule["width"]
                if x + hl <= px2 and y + hw <= py2:
                    msp.add_lwpolyline(
                        [
                            (x, y),
                            (x + hl, y),
                            (x + hl, y + hw),
                            (x, y + hw),
                            (x, y),
                        ],
                        dxfattribs={"layer": "PATTERN"},
                    )

            step = rule.get("size", rule.get("diameter", rule.get("length", 10)))
            x += step + rule["spacing"]

        y += rule.get("size", rule.get("diameter", rule.get("width", 10))) + rule["spacing"]
        row += 1

    # -----------------------------
    # Force correct AutoCAD view
    # -----------------------------
    doc.set_modelspace_vport(
        center=(length / 2, width / 2),
        height=width * 1.1,
    )

    # -----------------------------
    # Save & return
    # -----------------------------
    doc.saveas(filename)

    with open(filename, "rb") as f:
        encoded = base64.b64encode(f.read()).decode()

    return {
        "status": "ok",
        "filename": filename,
        "file_base64": encoded,
        "length_mm": length,
        "width_mm": width,
        "pattern": pattern_name,
    }

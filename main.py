from fastapi import FastAPI, Body
import ezdxf, os, base64

app = FastAPI()

@app.post("/generate-dxf")
async def generate_dxf(payload: dict = Body(...)):
    ai_json = payload
    os.makedirs("output_dxf", exist_ok=True)
    filename = f"output_dxf/{ai_json.get('customer','unknown')}_variantA.dxf"

    doc = ezdxf.new('R2010')
    msp = doc.modelspace()

    for act in ai_json.get("actions", []):
        t = act["type"]

        # Outer boundary rectangle
        if t == "add_rectangle":
            x1, y1, x2, y2 = act["x1"], act["y1"], act["x2"], act["y2"]
            msp.add_lwpolyline([(x1, y1), (x2, y1), (x2, y2), (x1, y2), (x1, y1)])

        # Simple circle
        elif t == "add_circle":
            msp.add_circle((act["x"], act["y"]), act["r"])

        # Text annotation
        elif t == "add_text":
            msp.add_text(
                act["text"],
                dxfattribs={'height': act.get('height', 10)}
            ).set_pos((act["x"], act["y"]))

        # Pattern fill inside rectangle
        elif t == "add_pattern":
            pattern = act.get("pattern", "square").lower()
            spacing = float(act.get("spacing", 10))
            hole_size = float(act.get("hole_size", 5))
            margin = float(act.get("margin", 10))  # unperforated edge margin
            x1, y1, x2, y2 = act["x1"], act["y1"], act["x2"], act["y2"]

            # Define pattern area inside the outer boundary
            start_x = x1 + margin
            start_y = y1 + margin
            end_x = x2 - margin
            end_y = y2 - margin

            y = start_y
            row = 0
            while y + hole_size <= end_y:
                # Offset alternate rows for diagonal/diamond effect
                offset_x = (hole_size / 2) if (pattern in ["diamond", "check"]) and (row % 2 == 1) else 0
                x = start_x + offset_x
                while x + hole_size <= end_x:
                    if pattern == "square":
                        msp.add_lwpolyline([
                            (x, y),
                            (x + hole_size, y),
                            (x + hole_size, y + hole_size),
                            (x, y + hole_size),
                            (x, y)
                        ])
                    elif pattern == "diamond" or pattern == "check":
                        msp.add_lwpolyline([
                            (x + hole_size / 2, y),
                            (x + hole_size, y + hole_size / 2),
                            (x + hole_size / 2, y + hole_size),
                            (x, y + hole_size / 2),
                            (x + hole_size / 2, y)
                        ])
                    elif pattern == "circle" or pattern == "round":
                        msp.add_circle(
                            (x + hole_size / 2, y + hole_size / 2),
                            hole_size / 2
                        )
                    x += hole_size + spacing
                y += hole_size + spacing
                row += 1

    # Save DXF
    doc.saveas(filename)

    # Encode the DXF to Base64 for n8n
    with open(filename, "rb") as f:
        encoded = base64.b64encode(f.read()).decode()

    return {"status": "ok", "filename": filename, "file_base64": encoded}

return items.map(item => {
  const rawMuster = (item.json["Muster"] || "").toString().trim().toLowerCase();
  const rawName = (item.json["Name"] || "").toString().trim().toLowerCase();
  const rawMaterial = (item.json["Material"] || "").toString().trim().toLowerCase();
  const rawVariant = (item.json["Ausführung"] || "").toString().trim().toLowerCase();
  const rawSize = (item.json["Maße in mm"] || "").toString().trim();

  // Handle Size
  const sizeMatch = rawSize.match(/(\d+)\s*[xX*]\s*(\d+)(?:\s*[xX*]\s*(\d+))?/);
  const length = sizeMatch ? parseInt(sizeMatch[1]) : null;
  const width = sizeMatch ? parseInt(sizeMatch[2]) : null;
  const thickness = sizeMatch && sizeMatch[3] ? parseFloat(sizeMatch[3]) : 1;

  let pattern = "Squares 10x10mm"; // Default

  switch (true) {
    // 🆕 Q+ → Squares Grouped (8 cols + 70mm gap)
    case /^q\+$/.test(rawMuster):
    case /q\s*\+/.test(rawMuster):
    case /grouped/.test(rawMuster):
      pattern = "Squares Grouped";
      break;

    // 🔹 Q → Standard Squares
    case /^q$/.test(rawMuster):
    case /quadrat|square|check/.test(rawMuster):
    case /_a_q/.test(rawName):
      pattern = "Squares 10x10mm";
      break;

    // 🔹 K → Diamond (Check)
    case /^k$/.test(rawMuster):
    case /karos|karo|diamond/.test(rawMuster):
    case /_a_k/.test(rawName):
      pattern = "Check 10x10mm";
      break;

    // 🔹 L → Slot
    case /^l$/.test(rawMuster):
    case /langloch|slot/.test(rawMuster):
    case /_a_l/.test(rawName):
      pattern = "Slotted hole 35x10mm";
      break;

    // 🔹 O → Circle
    case /^o$/.test(rawMuster):
    case /rundloch|round/.test(rawMuster):
    case /_a_o/.test(rawName):
      pattern = "Round hole 10mm";
      break;
  }

  return {
    json: {
      ...item.json,
      Length: length,
      Width: width,
      Thickness: thickness,
      Pattern: pattern,
      Material: rawMaterial.toUpperCase(),
      Variant: rawVariant.toUpperCase()
    }
  };
});

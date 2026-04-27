# Open-Source Printing Pipeline

This subfolder extends the TAMP workflow to replace Bambu Lab with a fully open-source stack, giving programmatic control over every step from microscopy image to printed lithograph.

```
Microscopy Image → Height Map → STL → G-code (PrusaSlicer) → Printer (Klipper/Prusa)
```

### Why open-source?

The Bambu Lab ecosystem has three limitations for research use:
- **Proprietary slicer** — no scripting or automation support
- **No API control** — cannot integrate into larger pipelines
- **Hardware lock-in** — costly and not community-repairable

This pipeline uses only open-source tools and works with any FDM printer.

---

## Workflow Steps

### 1. Prepare your image in ImageJ/Fiji

- Convert to grayscale
- For images with very fine detail (1–2 pixel precision), apply a Gaussian blur (radius = 1.0 pixel) — or use `--blur 1.0` in the script instead
- **Crop out any scale bars, metadata bars, or annotations** at the bottom of the image — these will appear as raised features in the lithograph
- Export as `.PNG` or `.JPG`

> 💡 The script handles grayscale conversion and blur internally, so you can also feed in a raw export directly and tune `--blur` from the command line.

---

### 2. Check your image dimensions and set print size

- Note your image's pixel dimensions (e.g. 1024×768)
- Your physical print size must match this aspect ratio — **the print does NOT have to be square**
- If the ratio is wrong, the script will warn you automatically and suggest the correct `--size-y`

| Image pixels | Print flags |
|---|---|
| 1024 × 1024 (square) | `--size-x 100 --size-y 100` |
| 1024 × 768 (4:3) | `--size-x 100 --size-y 75` |
| 1920 × 1080 (16:9) | `--size-x 100 --size-y 56.3` |

> ⚠️ If `--size-x` and `--size-y` don't match your image's aspect ratio, the script will warn you:
> ```
> [WARNING] Aspect ratio mismatch!
>     Height map is 512×384 (ratio 1.333)
>     Print size is 100×100 mm (ratio 1.000)
>     The lithograph will appear stretched. Consider --size-y 75.0
> ```

---

### 3. Generate the STL file

Install dependencies once:
```bash
pip install -r requirements.txt
```

Then run:
```bash
python tamp_litho.py your_image.png \
  --size-x 100 --size-y 75 \
  --base-thickness 1.0 \
  --relief-height 3.0 \
  --blur 1.2 \
  --skip-slice
```

This produces a `.stl` file in `./output/`. Open it in [MeshLab](https://www.meshlab.net/) or PrusaSlicer to inspect the relief before printing.

> 💡 Use `--invert` if your image has bright backgrounds and dark features (e.g. some TEM images) — this flips which areas become raised.

---

### 4. Slice and print

**Option A — Manual (any slicer):**
- Load the `.stl` into PrusaSlicer, OrcaSlicer, or Cura
- Recommended FDM settings:
  - Layer height: **0.12 mm**
  - Nozzle: **0.4 mm**
  - Infill: **15%** (gyroid)
  - Supports: **none needed** (flat base)

**Option B — Automated via script:**
```bash
python tamp_litho.py your_image.png \
  --size-x 100 --size-y 75 \
  --prusaslicer /path/to/prusa-slicer \
  --layer-height 0.12
```

> 💡 Finding PrusaSlicer on your system:
> - **Linux:** `which prusa-slicer`
> - **macOS:** `/Applications/PrusaSlicer.app/Contents/MacOS/PrusaSlicer`
> - **Windows:** `C:\Program Files\Prusa3D\PrusaSlicer\prusa-slicer-console.exe`

**Option C — Send directly to printer (Klipper only):**
```bash
python tamp_litho.py your_image.png \
  --size-x 100 --size-y 75 \
  --moonraker-host http://192.168.1.42:7125 \
  --start-print
```

---

## All Options

| Flag | Default | Description |
|------|---------|-------------|
| `--size-x` | 100 mm | Print width |
| `--size-y` | 100 mm | Print height — **set to match image aspect ratio** |
| `--resolution` | 512 | Height map resolution (px, longest side) |
| `--invert` | off | Invert relief: dark areas become raised |
| `--blur` | 1.0 | Gaussian smoothing — increase for noisy images |
| `--base-thickness` | 1 mm | Solid base below relief |
| `--relief-height` | 3 mm | Maximum tactile height difference |
| `--layer-height` | 0.12 mm | FDM layer height |
| `--skip-slice` | off | Stop after STL, skip slicing |
| `--printer-profile` | — | PrusaSlicer `.ini` config for your machine |
| `--moonraker-host` | — | Klipper printer URL for direct upload |
| `--start-print` | off | Auto-start print after upload |

---

## Recommended Printers

| Printer | Firmware | Notes |
|---------|----------|-------|
| **Prusa MK4 / XL** | Marlin | Most plug-and-play, good for labs |
| **Voron 2.4** | Klipper | Best for full automation via Moonraker API |
| Any Marlin/Klipper printer | — | Works with PrusaSlicer profiles |

---

## Example Output

Input: `SEM_5um_raw.png` — FePt spherical particles, 5 μm scale

![Height map preview](examples/fept_spheres/sem5um_preview.png)

Generated with:
```bash
python tamp_litho.py examples/SEM_5um_raw.png \
  --size-x 100 --size-y 75 \
  --relief-height 3.0 --blur 1.2
```

---

## Pipeline Details

| Step | Function | Description |
|------|----------|-------------|
| 1 | `image_to_heightmap` | Grayscale → contrast stretch → Gaussian blur → [0,1] float array |
| 2 | `heightmap_to_stl` | Builds watertight solid mesh: top relief + flat base + 4 side walls |
| 3 | `slice_stl` | Calls PrusaSlicer CLI; pass a `.ini` profile for your printer |
| 4 | `send_to_klipper` | Moonraker REST API upload + optional print start |

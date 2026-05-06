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

## Tools

### Main tool

| File | Format | Description |
|--------|--------|-------------|
| `tamp_batch_gui_v2.ipynb` | Jupyter notebook | **Start here.** Batch GUI with Low/Medium/High quality presets calculated from your printer's nozzle and layer height. Supports .STL, .3MF, .GLB output. |

> ⚠️ Requires **Jupyter Lab or Jupyter Notebook** — not VS Code notebook viewer.

### Supporting tools

| File | Format | Description |
|--------|--------|-------------|
| `tamp_batch_gui.ipynb` | Jupyter notebook | Previous version of the batch GUI — manual resolution and blur settings, useful if you want full control from the start |
| `tamp_litho.py` | Python script | Command-line pipeline for single images — useful for automation and scripting |
| `tamp_resolution_compare.ipynb` | Jupyter notebook | **Quality checking tool.** Run one image at multiple resolution, relief height, or blur values to find the best settings before a full batch run |
| `tamp_resolution_compare.py` | Python script | GUI version of the comparison tool |

---

## Getting Started from Zero

Follow these steps if you have never used Python before.

### 1. Install Python

Download Python 3.10 or newer from:
→ **https://www.python.org/downloads/**

> ⚠️ On Windows, check **"Add Python to PATH"** during installation.

Verify it worked — open a terminal and type:
```
python --version
```
You should see something like `Python 3.11.2`.

### 2. Install dependencies

Open a terminal, go into this folder, and run:
```bash
pip install -r requirements.txt
```
You only need to do this once.

### 3. Open the main tool

Open `tamp_batch_gui_v2.ipynb` in Jupyter Lab and run all cells. The GUI window will appear.

---

## The Main Batch GUI (v2)

The v2 GUI calculates resolution and blur automatically from your printer's physical specs — no need to guess numbers.

**How to use it:**

1. Click **+ Add Images** to select one or more microscopy images
2. Click **Browse** to choose where files will be saved
3. Choose your **output format**: `.STL`, `.3MF`, or `.GLB` — tick as many as you need
4. Enter your **printer specs** (print width, nozzle diameter, layer height)
5. Select a **quality preset**:

| Preset | What it means |
|--------|--------------|
| **Low** | 1 pixel = 2× nozzle width. Smooth, small file. Good for quick checks. |
| **Medium** | 1 pixel = 1 nozzle width. Matches what your printer can actually reproduce. **Recommended starting point.** |
| **High** | 1 pixel = 0.5× nozzle width. Finer than the nozzle — captures more texture, larger file. |

6. Set **print height** — leave as `auto` and it is calculated from your image's aspect ratio
7. Set **relief height** — the mm difference between lowest and highest point. The GUI shows how many distinct height levels your printer can produce at your layer height
8. Click **Generate STLs**

> 💡 Check **Full customization** to override resolution, blur, and base thickness manually if needed.

---

## Quality Checking Before a Full Batch Run

Before processing many images, use `tamp_resolution_compare.ipynb` to find the best settings for your specific image and printer.

It runs **one image** at multiple values of one parameter (resolution, relief height, or blur) and saves clearly named files — e.g. `elephant_resolution_128.stl`, `elephant_resolution_256.stl` — so you can compare them side by side in MeshLab or PrusaSlicer.

**Recommended workflow:**
1. Run `tamp_resolution_compare.ipynb` on one representative image
2. Open the output files in MeshLab to compare
3. Pick the settings that look best
4. Use those settings in `tamp_batch_gui_v2.ipynb` for the full batch

---

## Workflow Steps

### 1. Prepare your image in ImageJ/Fiji

- Convert to grayscale
- For images with very fine detail (1–2 pixel precision), apply a Gaussian blur (radius = 1.0 pixel) — or use the blur setting in the GUI
- **Crop out any scale bars, metadata bars, or annotations** at the bottom of the image — these will appear as raised features in the lithograph
- Export as `.PNG` or `.JPG`

---

### 2. Check your image dimensions and set print size

- Your physical print size must match the image aspect ratio — **the print does NOT have to be square**
- Leave print height as `auto` and the tool calculates it for you
- If you set it manually and it doesn't match, the script will warn you:

```
[WARNING] Aspect ratio mismatch!
    Height map is 512×384 (ratio 1.333)
    Print size is 100×100 mm (ratio 1.000)
    The lithograph will appear stretched. Consider size_y=75.0
```

| Image pixels | Correct print size |
|---|---|
| 1024 × 1024 (square) | size_x=100, size_y=100 |
| 1024 × 768 (4:3) | size_x=100, size_y=75 |
| 1920 × 1080 (16:9) | size_x=100, size_y=56.3 |

---

### 3. Generate the STL

Use `tamp_batch_gui_v2.ipynb` for most cases. For single images via command line:

```bash
python tamp_litho.py your_image.png \
  --size-x 100 --size-y 75 \
  --relief-height 3.0 \
  --skip-slice
```

---

### 4. Slice and print

**Manual (any slicer):**
- Load the `.stl` into PrusaSlicer, OrcaSlicer, or Cura
- Recommended FDM settings:
  - Layer height: **0.12 mm**
  - Nozzle: **0.4 mm**
  - Infill: **15%** (gyroid)
  - Supports: **none needed** (flat base)

**Automated via command line:**
```bash
python tamp_litho.py your_image.png \
  --size-x 100 --size-y 75 \
  --prusaslicer /path/to/prusa-slicer \
  --layer-height 0.12
```

> 💡 Finding PrusaSlicer:
> - **Linux:** `which prusa-slicer`
> - **macOS:** `/Applications/PrusaSlicer.app/Contents/MacOS/PrusaSlicer`
> - **Windows:** `C:\Program Files\Prusa3D\PrusaSlicer\prusa-slicer-console.exe`

**Direct to Klipper printer:**
```bash
python tamp_litho.py your_image.png \
  --size-x 100 --size-y 75 \
  --moonraker-host http://192.168.1.42:7125 \
  --start-print
```

---

## All Options (command-line)

| CLI flag | Default | What it does |
|----------|---------|--------------|
| `--size-x` | 100 mm | Print width |
| `--size-y` | 100 mm | Print height — match image aspect ratio |
| `--relief-height` | 3 mm | Max tactile height difference |
| `--base-thickness` | 1 mm | Solid base below relief |
| `--blur` | 1.0 | Gaussian smoothing — increase for noisy images |
| `--resolution` | 512 | Height map resolution in px |
| `--invert` | off | Flips which areas become raised |
| `--no-flip` | off | Disable vertical flip correction |
| `--layer-height` | 0.12 mm | FDM layer height for slicing |
| `--skip-slice` | off | Stop after STL, skip slicing |
| `--printer-profile` | — | PrusaSlicer `.ini` config |
| `--moonraker-host` | — | Klipper printer URL |
| `--start-print` | off | Auto-start print after upload |

---

## Recommended Printers

| Printer | Firmware | Notes |
|---------|----------|-------|
| **Prusa MK4 / XL** | Marlin | Most plug-and-play, good for labs |
| **Voron 2.4** | Klipper | Best for full automation via Moonraker API |
| Any Marlin/Klipper printer | — | Works with PrusaSlicer profiles |

---

## Troubleshooting

**`python: command not found` / `pip: command not found`**
→ Python is not installed or not in PATH. Re-install from https://www.python.org/downloads/ and check "Add Python to PATH" on Windows.

**`ModuleNotFoundError: No module named 'numpy'` (or pillow, scipy, stl)**
→ Run `pip install -r requirements.txt` from inside the `open_source_printing/` folder.

**`ModuleNotFoundError: No module named 'tamp_litho'` (when running the GUI)**
→ Make sure `tamp_batch_gui.py` and `tamp_litho.py` are in the same folder.

**The STL looks stretched or squished**
→ Print height doesn't match the image aspect ratio. Leave size_y as `auto` or check the warning message for the suggested value.

**The STL is mirrored**
→ Make sure "Flip vertically" is checked in the GUI, or that `--no-flip` is not set in the CLI.

**The relief is too subtle or too extreme**
→ Adjust relief height. Start with 3.0 mm. Use `tamp_resolution_compare.ipynb` to test values before a full batch run.

**The GUI window doesn't appear (Jupyter)**
→ Use Jupyter Lab or Jupyter Notebook. Does not work in VS Code's notebook viewer.

**PrusaSlicer not found**
→ Pass the full path with `--prusaslicer`. See examples in Step 4 above.

**STL file is too large for GitHub (>25 MB)**
→ Use the Low preset, or reduce `--resolution` to 256 in the CLI.

---

## Example Output

Input: `SEM_5um_raw.png` — FePt spherical particles, 5 μm scale

![Height map preview](examples/fept_spheres/sem5um_preview.png)

---

## Files

| File | Description |
|------|-------------|
| `tamp_batch_gui_v2.ipynb` | **Main tool** — batch GUI with quality presets |
| `tamp_batch_gui.ipynb` | Supporting — previous GUI version, manual settings |
| `tamp_litho.py` | Supporting — command-line single image pipeline |
| `tamp_resolution_compare.ipynb` | Supporting — quality checking before batch runs |
| `tamp_resolution_compare.py` | Supporting — GUI version of the comparison tool |
| `requirements.txt` | Python dependencies |

## Pipeline Details

| Step | Function | Description |
|------|----------|-------------|
| 1 | `image_to_heightmap` | Grayscale → contrast stretch → Gaussian blur → flip → [0,1] float array |
| 2 | `heightmap_to_stl` | Builds watertight solid mesh: top relief + flat base + 4 side walls |
| 3 | `slice_stl` | Calls PrusaSlicer CLI; pass a `.ini` profile for your printer |
| 4 | `send_to_klipper` | Moonraker REST API upload + optional print start |

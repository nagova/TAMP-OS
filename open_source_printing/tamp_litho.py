#!/usr/bin/env python3
"""
TAMP Open-Source Lithograph Maker
==================================
Extends the TAMP (Tactile Accessible Microscopy Printing) workflow
to replace Bambu Lab with a fully open-source pipeline:

  Microscopy Image → Height Map → STL → G-code (PrusaSlicer CLI) → Printer

Dependencies:
    pip install numpy pillow scipy numpy-stl

Optional (for direct print sending):
    pip install requests  # for Klipper/Moonraker printers
"""

import argparse
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter
from stl import mesh


# ─────────────────────────────────────────────
#  STEP 1 — Image → Height Map
# ─────────────────────────────────────────────

def image_to_heightmap(
    image_path: Path,
    output_size: tuple = (512, 512),
    invert: bool = False,
    blur_sigma: float = 1.0,
    contrast_percentile: tuple = (2.0, 98.0),
    preserve_aspect: bool = True,
) -> np.ndarray:
    """
    Convert a microscopy image to a normalised [0, 1] height map.

    Args:
        image_path:          Path to input image (any format PIL supports).
        output_size:         (width, height) in pixels for the height map.
                             If preserve_aspect=True, height is derived from
                             the image's aspect ratio and output_size[0] is
                             used as the reference width.
        invert:              Flip dark/light mapping (useful for SEM images
                             where bright = high structure).
        blur_sigma:          Gaussian blur sigma to smooth noise before
                             height mapping.
        contrast_percentile: Low/high percentile clipping for contrast
                             stretching.
        preserve_aspect:     If True (default), keeps the original image
                             aspect ratio. The physical print dimensions
                             (--size-x / --size-y) should match this ratio
                             or the lithograph will appear stretched.

    Returns:
        2-D float32 numpy array with values in [0, 1].

    Notes:
        The print does NOT have to be square. Pass matching --size-x and
        --size-y values to heightmap_to_stl() to reproduce the correct
        physical proportions. If you force a square print from a rectangular
        image the relief will be stretched.
    """
    img = Image.open(image_path).convert("L")
    orig_w, orig_h = img.size

    if preserve_aspect and (orig_w != orig_h):
        target_w = output_size[0]
        target_h = round(target_w * orig_h / orig_w)
        actual_size = (target_w, target_h)
        print(
            f"[i] Image is {orig_w}x{orig_h} (non-square, ratio "
            f"{orig_w/orig_h:.3f}). Height map will be {target_w}x{target_h}.\n"
            f"    Make sure --size-x and --size-y preserve this ratio,\n"
            f"    e.g. --size-x 100 --size-y {round(100*orig_h/orig_w, 1)}\n"
            f"    otherwise the lithograph will appear stretched."
        )
    else:
        actual_size = output_size

    img = img.resize(actual_size, Image.LANCZOS)
    arr = np.array(img, dtype=np.float32)

    lo = np.percentile(arr, contrast_percentile[0])
    hi = np.percentile(arr, contrast_percentile[1])
    arr = np.clip((arr - lo) / (hi - lo + 1e-8), 0.0, 1.0)

    if blur_sigma > 0:
        arr = gaussian_filter(arr, sigma=blur_sigma)

    if invert:
        arr = 1.0 - arr

    return arr


# ─────────────────────────────────────────────
#  STEP 2 — Height Map → STL
# ─────────────────────────────────────────────

def heightmap_to_stl(
    heightmap: np.ndarray,
    output_path: Path,
    base_thickness_mm: float = 1.0,
    max_relief_mm: float = 3.0,
    physical_size_mm: tuple = (100.0, 100.0),
) -> Path:
    """
    Convert a [0,1] height map to a solid STL mesh suitable for FDM printing.

    The mesh has:
      - A top surface shaped by the height map.
      - A flat bottom at z = 0.
      - Four side walls.

    Args:
        heightmap:           2-D float32 array, values in [0, 1].
        output_path:         Where to save the .stl file.
        base_thickness_mm:   Minimum solid base below the relief.
        max_relief_mm:       Height difference between lowest and highest point.
        physical_size_mm:    (x_mm, y_mm) real-world footprint of the print.

    Returns:
        Path to the written STL file.
    """
    rows, cols = heightmap.shape
    dx = physical_size_mm[0] / (cols - 1)
    dy = physical_size_mm[1] / (rows - 1)

    # Aspect ratio check
    hm_ratio = cols / rows
    print_ratio = physical_size_mm[0] / physical_size_mm[1]
    if abs(hm_ratio - print_ratio) > 0.05:
        print(
            f"[WARNING] Aspect ratio mismatch!\n"
            f"    Height map is {cols}x{rows} (ratio {hm_ratio:.3f})\n"
            f"    Print size is {physical_size_mm[0]}x{physical_size_mm[1]} mm "
            f"(ratio {print_ratio:.3f})\n"
            f"    The lithograph will appear stretched. "
            f"Consider --size-y {round(physical_size_mm[0] / hm_ratio, 1)}"
        )

    z_top = base_thickness_mm + heightmap * max_relief_mm

    num_top_tris = (rows - 1) * (cols - 1) * 2
    num_bottom_tris = (rows - 1) * (cols - 1) * 2
    num_side_tris = 2 * ((rows - 1) + (cols - 1)) * 2

    total_tris = num_top_tris + num_bottom_tris + num_side_tris
    litho_mesh = mesh.Mesh(np.zeros(total_tris, dtype=mesh.Mesh.dtype))

    tri_idx = 0

    def add_tri(v0, v1, v2):
        nonlocal tri_idx
        litho_mesh.vectors[tri_idx] = [v0, v1, v2]
        tri_idx += 1

    # Top surface
    for r in range(rows - 1):
        for c in range(cols - 1):
            x0, y0 = c * dx, r * dy
            x1 = (c + 1) * dx
            x2, y2 = c * dx, (r + 1) * dy
            x3, y3 = (c + 1) * dx, (r + 1) * dy
            z00 = z_top[r, c]
            z10 = z_top[r, c + 1]
            z01 = z_top[r + 1, c]
            z11 = z_top[r + 1, c + 1]
            add_tri([x0, y0, z00], [x1, y0, z10], [x2, y2, z01])
            add_tri([x1, y0, z10], [x3, y3, z11], [x2, y2, z01])

    # Bottom surface
    for r in range(rows - 1):
        for c in range(cols - 1):
            x0, y0 = c * dx, r * dy
            x1 = (c + 1) * dx
            x2, y2 = c * dx, (r + 1) * dy
            x3, y3 = (c + 1) * dx, (r + 1) * dy
            add_tri([x0, y0, 0], [x2, y2, 0], [x1, y0, 0])
            add_tri([x1, y0, 0], [x2, y2, 0], [x3, y3, 0])

    xmax = (cols - 1) * dx
    ymax = (rows - 1) * dy

    # Front wall (y=0)
    for c in range(cols - 1):
        x0, x1 = c * dx, (c + 1) * dx
        z0, z1 = z_top[0, c], z_top[0, c + 1]
        add_tri([x0, 0, 0], [x1, 0, 0], [x0, 0, z0])
        add_tri([x1, 0, 0], [x1, 0, z1], [x0, 0, z0])

    # Back wall (y=ymax)
    for c in range(cols - 1):
        x0, x1 = c * dx, (c + 1) * dx
        z0, z1 = z_top[-1, c], z_top[-1, c + 1]
        add_tri([x0, ymax, 0], [x0, ymax, z0], [x1, ymax, 0])
        add_tri([x1, ymax, 0], [x0, ymax, z0], [x1, ymax, z1])

    # Left wall (x=0)
    for r in range(rows - 1):
        y0, y1 = r * dy, (r + 1) * dy
        z0, z1 = z_top[r, 0], z_top[r + 1, 0]
        add_tri([0, y0, 0], [0, y0, z0], [0, y1, 0])
        add_tri([0, y1, 0], [0, y0, z0], [0, y1, z1])

    # Right wall (x=xmax)
    for r in range(rows - 1):
        y0, y1 = r * dy, (r + 1) * dy
        z0, z1 = z_top[r, -1], z_top[r + 1, -1]
        add_tri([xmax, y0, 0], [xmax, y1, 0], [xmax, y0, z0])
        add_tri([xmax, y1, 0], [xmax, y1, z1], [xmax, y0, z0])

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    litho_mesh.save(str(output_path))
    print(f"[OK] STL saved -> {output_path}")
    return output_path


# ─────────────────────────────────────────────
#  STEP 3 — STL → G-code via PrusaSlicer CLI
# ─────────────────────────────────────────────

PRUSASLICER_DEFAULTS = {
    "layer_height": "0.12",
    "first_layer_height": "0.2",
    "fill_density": "15%",
    "fill_pattern": "gyroid",
    "perimeters": "3",
    "support_material": "0",
    "nozzle_diameter": "0.4",
    "filament_type": "PLA",
}


def slice_stl(
    stl_path: Path,
    output_dir: Path,
    prusaslicer_bin: str = "prusa-slicer",
    printer_profile: str = None,
    extra_args: dict = None,
) -> Path:
    """
    Slice an STL with PrusaSlicer CLI and return the path to the G-code file.

    Args:
        stl_path:         Path to the .stl file.
        output_dir:       Directory where the .gcode file will be written.
        prusaslicer_bin:  Name or full path of the PrusaSlicer executable.
                          Linux:   'prusa-slicer'
                          macOS:   '/Applications/PrusaSlicer.app/Contents/MacOS/PrusaSlicer'
                          Windows: 'C:/Program Files/Prusa3D/PrusaSlicer/prusa-slicer-console.exe'
        printer_profile:  Optional path to a PrusaSlicer .ini printer config.
        extra_args:       Dict of additional --key value pairs passed to CLI.

    Returns:
        Path to the generated .gcode file.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    gcode_path = output_dir / (Path(stl_path).stem + ".gcode")
    params = {**PRUSASLICER_DEFAULTS, **(extra_args or {})}

    cmd = [prusaslicer_bin, "--export-gcode", str(stl_path), "--output", str(gcode_path)]
    if printer_profile:
        cmd += ["--load", printer_profile]
    for k, v in params.items():
        cmd += [f"--{k}", str(v)]

    print(f"[->] Slicing: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"[ERROR] PrusaSlicer:\n{result.stderr}", file=sys.stderr)
        raise RuntimeError("Slicing failed — check PrusaSlicer is installed and in PATH.")

    print(f"[OK] G-code saved -> {gcode_path}")
    return gcode_path


# ─────────────────────────────────────────────
#  STEP 4 — Send G-code to printer (Klipper/Moonraker)
# ─────────────────────────────────────────────

def send_to_klipper(
    gcode_path: Path,
    moonraker_host: str = "http://localhost:7125",
    start_print: bool = False,
) -> None:
    """
    Upload a G-code file to a Klipper printer via Moonraker HTTP API
    and optionally start the print.

    Args:
        gcode_path:      Local path to the .gcode file.
        moonraker_host:  Base URL of the Moonraker instance
                         (e.g. 'http://192.168.1.42:7125').
        start_print:     If True, immediately starts printing after upload.
    """
    try:
        import requests
    except ImportError:
        print("[ERROR] 'requests' not installed. Run: pip install requests")
        return

    filename = Path(gcode_path).name
    upload_url = f"{moonraker_host}/server/files/upload"

    with open(gcode_path, "rb") as f:
        response = requests.post(upload_url, files={"file": (filename, f)})

    if response.status_code != 201:
        raise RuntimeError(f"Upload failed: {response.text}")
    print(f"[OK] Uploaded {filename} to Moonraker at {moonraker_host}")

    if start_print:
        r = requests.post(f"{moonraker_host}/printer/print/start", json={"filename": filename})
        if r.status_code == 200:
            print(f"[OK] Print started: {filename}")
        else:
            print(f"[ERROR] Failed to start print: {r.text}")


# ─────────────────────────────────────────────
#  Full pipeline
# ─────────────────────────────────────────────

def run_pipeline(args: argparse.Namespace) -> None:
    image_path = Path(args.image)
    out_dir = Path(args.output_dir)

    print(f"\n{'='*50}")
    print(f"  TAMP-OS Lithograph Pipeline")
    print(f"{'='*50}\n")

    print("[1/4] Converting image to height map...")
    heightmap = image_to_heightmap(
        image_path,
        output_size=(args.resolution, args.resolution),
        invert=args.invert,
        blur_sigma=args.blur,
        contrast_percentile=(args.contrast_lo, args.contrast_hi),
    )
    print(f"      Shape: {heightmap.shape}, range [{heightmap.min():.3f}, {heightmap.max():.3f}]")

    print("\n[2/4] Generating STL mesh...")
    stl_path = out_dir / f"{image_path.stem}_lithograph.stl"
    heightmap_to_stl(
        heightmap, stl_path,
        base_thickness_mm=args.base_thickness,
        max_relief_mm=args.relief_height,
        physical_size_mm=(args.size_x, args.size_y),
    )

    if not args.skip_slice:
        print("\n[3/4] Slicing STL to G-code...")
        gcode_path = slice_stl(
            stl_path, out_dir,
            prusaslicer_bin=args.prusaslicer,
            printer_profile=args.printer_profile,
            extra_args={"layer_height": str(args.layer_height)},
        )
    else:
        print("\n[3/4] Skipping slicing (--skip-slice).")
        gcode_path = None

    if gcode_path and args.moonraker_host:
        print(f"\n[4/4] Uploading to Klipper at {args.moonraker_host}...")
        send_to_klipper(gcode_path, args.moonraker_host, start_print=args.start_print)
    else:
        print("\n[4/4] Skipping upload (no --moonraker-host provided).")

    print(f"\n{'='*50}")
    print(f"  Done! Files written to: {out_dir}")
    print(f"{'='*50}\n")


# ─────────────────────────────────────────────
#  CLI
# ─────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="TAMP-OS: Open-Source Lithograph Maker",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("image", help="Path to microscopy image (PNG, TIFF, JPG, ...)")
    p.add_argument("-o", "--output-dir", default="./output", help="Output directory")

    p.add_argument("--resolution", type=int, default=512, help="Height map resolution (px, longest side)")
    p.add_argument("--invert", action="store_true", help="Invert grayscale -> height mapping")
    p.add_argument("--blur", type=float, default=1.0, help="Gaussian blur sigma")
    p.add_argument("--contrast-lo", type=float, default=2.0, help="Low percentile for contrast stretch")
    p.add_argument("--contrast-hi", type=float, default=98.0, help="High percentile for contrast stretch")

    p.add_argument("--size-x", type=float, default=100.0, help="Print width in mm")
    p.add_argument("--size-y", type=float, default=100.0, help="Print height in mm (match image aspect ratio!)")
    p.add_argument("--base-thickness", type=float, default=1.0, help="Base thickness below relief (mm)")
    p.add_argument("--relief-height", type=float, default=3.0, help="Maximum relief height (mm)")

    p.add_argument("--skip-slice", action="store_true", help="Stop after STL, skip slicing")
    p.add_argument("--prusaslicer", default="prusa-slicer", help="Path to PrusaSlicer executable")
    p.add_argument("--printer-profile", help="Path to PrusaSlicer .ini printer config")
    p.add_argument("--layer-height", type=float, default=0.12, help="Layer height for slicing (mm)")

    p.add_argument("--moonraker-host", help="Moonraker base URL (e.g. http://192.168.1.42:7125)")
    p.add_argument("--start-print", action="store_true", help="Auto-start print after upload")
    return p


if __name__ == "__main__":
    parser = build_parser()
    args = parser.parse_args()
    run_pipeline(args)

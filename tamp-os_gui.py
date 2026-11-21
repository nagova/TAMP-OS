#!/usr/bin/env python3
"""
TAMP-OS v2: Tactile Microscopy & Scientific Image Printing
Standalone Desktop Application

Unified interface supporting both:
  1. TAMP-OS Mode: Grayscale heightmap lithographs from microscopy images.
  2. TAMP-OS Chroma Mode: Multi-color gradient and colormap tactile encoding
     with macroscopic ramp + micro-texture modulation.

Run:
  python tamp_gui.py
"""

import os
import sys
import json
import math
import time
import struct
import zipfile
import threading
from pathlib import Path

import numpy as np
from PIL import Image, ImageTk
from scipy.ndimage import gaussian_filter
from scipy.spatial import cKDTree
from stl import mesh as stl_mesh

import matplotlib
matplotlib.use("Agg")
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.colors import LightSource
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Optional 3D viewer
try:
    import pyvista as pv
    PYVISTA_AVAILABLE = True
except ImportError:
    PYVISTA_AVAILABLE = False


# ==============================================================================
# SECTION 1: SETTINGS & PERSISTENCE
# ==============================================================================

SETTINGS_FILE = Path.home() / ".tamp_settings.json"

DEFAULT_SETTINGS = {
    "mode": "os",  # "os" or "chroma"
    "printer_profile": "Standard FDM / 0.4 mm nozzle",
    "selected_preset": "Medium",
    "output_dir": str(Path.home() / "TAMP_output"),
    "fmt_stl": True,
    "fmt_3mf": False,
    "fmt_glb": False,
    "size_x": "100",
    "size_y": "auto",
    "nozzle": "0.4",
    "layer": "0.12",
    "relief": "3.0",
    "blur": "1.2",
    "base_thickness": "1.2",
    "flip": True,
    # Chroma specific
    "chroma_colormap": "Inferno",
    "chroma_ramp_elevation": 1.8,
    "chroma_texture": "Honeycomb",
    "chroma_texture_relief": 0.6,
    "chroma_polarity_inverted": False
}


def load_settings():
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                cfg = dict(DEFAULT_SETTINGS)
                cfg.update(saved)
                return cfg
        except Exception:
            pass
    return dict(DEFAULT_SETTINGS)


def save_settings(cfg):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass


# ==============================================================================
# SECTION 2: PRESET CALCULATOR & IMAGE ANALYZER
# ==============================================================================

def estimate_stl_file_size(resolution, aspect_ratio=1.0):
    """Return an approximate binary STL size in MB for a height-map mesh."""
    cols = max(2, int(resolution))
    rows = max(2, int(round(cols * aspect_ratio)))
    num_tris = (rows - 1) * (cols - 1) * 4 + 2 * ((rows - 1) + (cols - 1)) * 2
    return (84 + 50 * num_tris) / (1024 * 1024)


def format_file_size(size_mb):
    if size_mb < 1:
        return f"{size_mb * 1024:.0f} KB"
    if size_mb < 100:
        return f"{size_mb:.1f} MB"
    return f"{size_mb:.0f} MB"


def calculate_presets(print_size_x, nozzle_mm=0.4, layer_mm=0.12, aspect_ratio=1.0):
    """
    Calculate Low / Medium / High presets from printer physical specs.
    Medium = nozzle-matched (1 px per nozzle width), Low is coarser,
    High oversamples the nozzle to preserve finer features.
    """
    medium_res = round(print_size_x / nozzle_mm)
    low_res = round(print_size_x / (nozzle_mm * 2))
    high_res = round(print_size_x / (nozzle_mm * 0.5))

    def snap(v):
        return max(64, min(512, int(2 ** round(math.log2(v)))))

    low_res = snap(low_res)
    medium_res = snap(medium_res)
    high_res = min(512, snap(high_res))

    def preset(resolution, blur, px_size, feature_text, note):
        size_mb = estimate_stl_file_size(resolution, aspect_ratio)
        return {
            "resolution": resolution,
            "blur": blur,
            "px_size": px_size,
            "file_size_mb": size_mb,
            "file_size": format_file_size(size_mb),
            "description": f"{note}\n~{format_file_size(size_mb)} STL · {resolution} px",
        }

    return {
        "Low": preset(low_res, 2.0, print_size_x / low_res, f"~{nozzle_mm*2:.1f} mm features", "Quick draft"),
        "Medium": preset(medium_res, 1.2, print_size_x / medium_res, f"~{nozzle_mm:.1f} mm features", "Balanced detail"),
        "High": preset(high_res, 0.8, print_size_x / high_res, f"~{nozzle_mm*0.5:.2f} mm features", "Maximum detail"),
    }


def analyze_image_quality(img_path):
    """Measure source image size, exposure spread, and edge detail for preset guidance."""
    img = Image.open(img_path).convert("L")
    w, h = img.size
    analysis_img = img.copy()
    analysis_img.thumbnail((1024, 1024), Image.LANCZOS)
    arr = np.array(analysis_img, dtype=np.float32)
    p1, p5, p95, p99 = np.percentile(arr, [1, 5, 95, 99])
    dynamic_range = float(p95 - p5)
    clipped_dark = float(np.mean(arr <= 3) * 100)
    clipped_light = float(np.mean(arr >= 252) * 100)
    gy, gx = np.gradient(arr / 255.0)
    edge_detail = float(np.percentile(np.hypot(gx, gy), 90))

    if dynamic_range < 45:
        exposure = "low contrast"
    elif clipped_dark + clipped_light > 8:
        exposure = "clipped highlights/shadows"
    elif dynamic_range > 170:
        exposure = "high dynamic range"
    else:
        exposure = "balanced contrast"

    if edge_detail > 0.075:
        detail = "fine edge detail/noise"
    elif edge_detail < 0.025:
        detail = "smooth gradients"
    else:
        detail = "moderate detail"

    if min(w, h) < 512:
        pixel_note = "small source image"
    elif min(w, h) > 1800:
        pixel_note = "large source image"
    else:
        pixel_note = "moderate source image"

    return {
        "width": w, "height": h, "megapixels": (w * h) / 1_000_000,
        "dynamic_range": dynamic_range, "exposure": exposure,
        "edge_detail": edge_detail, "detail": detail,
        "clipped_total": clipped_dark + clipped_light, "pixel_note": pixel_note,
    }


def recommend_preset_from_analysis(analysis):
    if analysis["pixel_note"] == "small source image" or analysis["detail"] == "smooth gradients":
        preset = "Low"
    elif analysis["detail"] == "fine edge detail/noise" or analysis["pixel_note"] == "large source image":
        preset = "High"
    else:
        preset = "Medium"
    return preset


# ==============================================================================
# SECTION 3: MESH BUILDER & 3D FORMAT CONVERTERS
# ==============================================================================

def heightmap_to_stl(heightmap, output_path, base_thickness_mm=1.2,
                     max_relief_mm=3.0, physical_size_mm=(100.0, 75.0)):
    """Generate a watertight binary STL from a 2D heightmap."""
    rows, cols = heightmap.shape
    dx = physical_size_mm[0] / (cols - 1)
    dy = physical_size_mm[1] / (rows - 1)
    z_top = base_thickness_mm + heightmap * max_relief_mm

    num_tris = (rows - 1) * (cols - 1) * 4 + 2 * ((rows - 1) + (cols - 1)) * 2
    litho_mesh = stl_mesh.Mesh(np.zeros(num_tris, dtype=stl_mesh.Mesh.dtype))
    tri_idx = 0

    def add_tri(v0, v1, v2):
        nonlocal tri_idx
        litho_mesh.vectors[tri_idx] = [v0, v1, v2]
        tri_idx += 1

    # Top & bottom surfaces
    for r in range(rows - 1):
        for c in range(cols - 1):
            x0, y0 = c * dx, r * dy
            x1 = (c + 1) * dx
            x2, y2 = c * dx, (r + 1) * dy
            x3, y3 = (c + 1) * dx, (r + 1) * dy
            z00, z10, z01, z11 = z_top[r, c], z_top[r, c + 1], z_top[r + 1, c], z_top[r + 1, c + 1]

            # Top surface
            add_tri([x0, y0, z00], [x1, y0, z10], [x2, y2, z01])
            add_tri([x1, y0, z10], [x3, y3, z11], [x2, y2, z01])
            # Bottom plane
            add_tri([x0, y0, 0], [x2, y2, 0], [x1, y0, 0])
            add_tri([x1, y0, 0], [x2, y2, 0], [x3, y3, 0])

    xmax, ymax = (cols - 1) * dx, (rows - 1) * dy

    # Side walls
    for c in range(cols - 1):
        x0, x1 = c * dx, (c + 1) * dx
        z0, z1 = z_top[0, c], z_top[0, c + 1]
        add_tri([x0, 0, 0], [x1, 0, 0], [x0, 0, z0])
        add_tri([x1, 0, 0], [x1, 0, z1], [x0, 0, z0])

    for c in range(cols - 1):
        x0, x1 = c * dx, (c + 1) * dx
        z0, z1 = z_top[-1, c], z_top[-1, c + 1]
        add_tri([x0, ymax, 0], [x0, ymax, z0], [x1, ymax, 0])
        add_tri([x1, ymax, 0], [x0, ymax, z0], [x1, ymax, z1])

    for r in range(rows - 1):
        y0, y1 = r * dy, (r + 1) * dy
        z0, z1 = z_top[r, 0], z_top[r + 1, 0]
        add_tri([0, y0, 0], [0, y0, z0], [0, y1, 0])
        add_tri([0, y1, 0], [0, y0, z0], [0, y1, z1])

    for r in range(rows - 1):
        y0, y1 = r * dy, (r + 1) * dy
        z0, z1 = z_top[r, -1], z_top[r + 1, -1]
        add_tri([xmax, y0, 0], [xmax, y1, 0], [xmax, y0, z0])
        add_tri([xmax, y1, 0], [xmax, y1, z1], [xmax, y0, z0])

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    litho_mesh.save(str(output_path))
    return output_path


def surface_z_to_stl(Z, output_path, physical_size_mm=(100.0, 75.0)):
    """Generate binary STL directly from absolute Z coordinate surface (mm)."""
    rows, cols = Z.shape
    dx = physical_size_mm[0] / (cols - 1)
    dy = physical_size_mm[1] / (rows - 1)
    z_top = Z

    num_tris = (rows - 1) * (cols - 1) * 4 + 2 * ((rows - 1) + (cols - 1)) * 2
    litho_mesh = stl_mesh.Mesh(np.zeros(num_tris, dtype=stl_mesh.Mesh.dtype))
    tri_idx = 0

    def add_tri(v0, v1, v2):
        nonlocal tri_idx
        litho_mesh.vectors[tri_idx] = [v0, v1, v2]
        tri_idx += 1

    for r in range(rows - 1):
        for c in range(cols - 1):
            x0, y0 = c * dx, r * dy
            x1 = (c + 1) * dx
            x2, y2 = c * dx, (r + 1) * dy
            x3, y3 = (c + 1) * dx, (r + 1) * dy
            z00, z10, z01, z11 = z_top[r, c], z_top[r, c + 1], z_top[r + 1, c], z_top[r + 1, c + 1]

            add_tri([x0, y0, z00], [x1, y0, z10], [x2, y2, z01])
            add_tri([x1, y0, z10], [x3, y3, z11], [x2, y2, z01])
            add_tri([x0, y0, 0], [x2, y2, 0], [x1, y0, 0])
            add_tri([x1, y0, 0], [x2, y2, 0], [x3, y3, 0])

    xmax, ymax = (cols - 1) * dx, (rows - 1) * dy

    for c in range(cols - 1):
        x0, x1 = c * dx, (c + 1) * dx
        z0, z1 = z_top[0, c], z_top[0, c + 1]
        add_tri([x0, 0, 0], [x1, 0, 0], [x0, 0, z0])
        add_tri([x1, 0, 0], [x1, 0, z1], [x0, 0, z0])

    for c in range(cols - 1):
        x0, x1 = c * dx, (c + 1) * dx
        z0, z1 = z_top[-1, c], z_top[-1, c + 1]
        add_tri([x0, ymax, 0], [x0, ymax, z0], [x1, ymax, 0])
        add_tri([x1, ymax, 0], [x0, ymax, z0], [x1, ymax, z1])

    for r in range(rows - 1):
        y0, y1 = r * dy, (r + 1) * dy
        z0, z1 = z_top[r, 0], z_top[r + 1, 0]
        add_tri([0, y0, 0], [0, y0, z0], [0, y1, 0])
        add_tri([0, y1, 0], [0, y0, z0], [0, y1, z1])

    for r in range(rows - 1):
        y0, y1 = r * dy, (r + 1) * dy
        z0, z1 = z_top[r, -1], z_top[r + 1, -1]
        add_tri([xmax, y0, 0], [xmax, y1, 0], [xmax, y0, z0])
        add_tri([xmax, y1, 0], [xmax, y1, z1], [xmax, y0, z0])

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    litho_mesh.save(str(output_path))
    return output_path


def stl_to_3mf(stl_path):
    m = stl_mesh.Mesh.from_file(str(stl_path))
    vertices = []
    vert_map = {}
    indices = []
    for tri in m.vectors:
        face = []
        for v in tri:
            key = tuple(round(float(x), 4) for x in v)
            if key not in vert_map:
                vert_map[key] = len(vertices)
                vertices.append(key)
            face.append(vert_map[key])
        indices.append(face)
    vx = " ".join(f'<vertex x="{v[0]:.4f}" y="{v[1]:.4f}" z="{v[2]:.4f}"/>' for v in vertices)
    tx = " ".join(f'<triangle v1="{t[0]}" v2="{t[1]}" v3="{t[2]}"/>' for t in indices)
    ns = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
    xml = (f'<?xml version="1.0" encoding="UTF-8"?>'
           f'<model unit="millimeter" xmlns="{ns}">'
           f'<resources><object id="1" type="model"><mesh>'
           f'<vertices>{vx}</vertices><triangles>{tx}</triangles>'
           f'</mesh></object></resources><build><item objectid="1"/></build></model>')
    out = Path(str(stl_path).replace(".stl", ".3mf"))
    ct_ns = "http://schemas.openxmlformats.org/package/2006/content-types"
    rel_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    rel_type = "http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"
    with zipfile.ZipFile(str(out), "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("3D/3dmodel.model", xml)
        zf.writestr("[Content_Types].xml",
            f'<?xml version="1.0"?><Types xmlns="{ct_ns}">'
            f'<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            f'<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
            f'</Types>')
        zf.writestr("_rels/.rels",
            f'<?xml version="1.0"?><Relationships xmlns="{rel_ns}">'
            f'<Relationship Type="{rel_type}" Target="/3D/3dmodel.model" Id="r1"/>'
            f'</Relationships>')
    return out


def stl_to_glb(stl_path):
    m = stl_mesh.Mesh.from_file(str(stl_path))
    verts = m.vectors.reshape(-1, 3).astype(np.float32)
    indices = np.arange(len(verts), dtype=np.uint32)
    def pad4(b): return b + b'\x00' * ((4 - len(b) % 4) % 4)
    ib = pad4(indices.tobytes())
    vb = pad4(verts.tobytes())
    bd = ib + vb
    gltf = {
        "asset": {"version": "2.0", "generator": "TAMP-OS v2"}, "scene": 0,
        "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 1}, "indices": 0}]}],
        "accessors": [
            {"bufferView": 0, "componentType": 5125, "count": len(indices), "type": "SCALAR"},
            {"bufferView": 1, "componentType": 5126, "count": len(verts), "type": "VEC3",
             "min": verts.min(0).tolist(), "max": verts.max(0).tolist()}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(ib), "target": 34963},
            {"buffer": 0, "byteOffset": len(ib), "byteLength": len(vb), "target": 34962}],
        "buffers": [{"byteLength": len(bd)}]
    }
    jb = pad4(json.dumps(gltf, separators=(",", ":")).encode())
    def chunk(d, t): return struct.pack("<II", len(d), t) + d
    out = Path(str(stl_path).replace(".stl", ".glb"))
    with open(str(out), "wb") as f:
        f.write(struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(jb) + 8 + len(bd))
                + chunk(jb, 0x4E4F534A) + chunk(bd, 0x004E4942))
    return out


def convert_stl(stl_path, formats):
    if formats.get("3mf"):
        stl_to_3mf(stl_path)
    if formats.get("glb"):
        stl_to_glb(stl_path)
    if not formats.get("stl"):
        stl_path.unlink(missing_ok=True)


# ==============================================================================
# SECTION 4: CHROMA ENGINE (KD-TREE DECODING, RAMP & TEXTURES)
# ==============================================================================

SUPPORTED_COLORMAPS = ["Inferno", "Viridis", "Turbo", "SVD Chromatic", "Luminance"]

_KD_CACHE = {}

def get_colormap_tree(colormap_name):
    """Return (lut_rgb, cKDTree) for the specified colormap."""
    if colormap_name in _KD_CACHE:
        return _KD_CACHE[colormap_name]

    c_lower = colormap_name.lower().replace(" ", "")
    if c_lower in ("inferno", "viridis", "turbo"):
        cmap = mpl.colormaps[c_lower]
        lut = cmap(np.linspace(0, 1, 256))[:, :3]
    elif "svd" in c_lower:
        # Chromatic 1st principal axis (cyan -> yellow -> magenta/red)
        t = np.linspace(0, 1, 256)
        r = np.clip(0.2 + 0.8 * t**1.2, 0, 1)
        g = np.clip(np.sin(t * np.pi)**0.8, 0, 1)
        b = np.clip(1.0 - t**0.8, 0, 1)
        lut = np.stack([r, g, b], axis=-1)
    else:  # Luminance / Grayscale
        t = np.linspace(0, 1, 256)
        lut = np.stack([t, t, t], axis=-1)

    tree = cKDTree(lut)
    _KD_CACHE[colormap_name] = (lut, tree)
    return lut, tree


def decode_colormap(img_pil, colormap_name="Inferno"):
    """
    Fast RGB-to-scalar projection using scipy.spatial.cKDTree.
    Returns normalized scalar array [0, 1] of shape (H, W).
    """
    if colormap_name == "Luminance":
        gray = img_pil.convert("L")
        return np.array(gray, dtype=np.float32) / 255.0

    rgb = img_pil.convert("RGB")
    arr = np.array(rgb, dtype=np.float32) / 255.0
    h, w, _ = arr.shape
    flat_rgb = arr.reshape(-1, 3)

    lut, tree = get_colormap_tree(colormap_name)
    _, indices = tree.query(flat_rgb)
    scalar = (indices / 255.0).reshape(h, w).astype(np.float32)
    return scalar


def build_ramp(rows, cols, physical_size_mm, ramp_elevation_mm, direction="horizontal"):
    """Generate linear elevation ramp in mm."""
    if direction == "horizontal":
        x_coords = np.linspace(0.0, float(ramp_elevation_mm), cols, dtype=np.float32)
        return np.tile(x_coords, (rows, 1))
    else:
        y_coords = np.linspace(0.0, float(ramp_elevation_mm), rows, dtype=np.float32).reshape(-1, 1)
        return np.repeat(y_coords, cols, axis=1)


def apply_texture(scalar_field, texture_type, physical_size_mm, relief_mm, polarity_inverted=False):
    """
    Generate procedural micro-texture height field in mm modulated by scalar_field.
    """
    s = scalar_field.copy()
    if polarity_inverted:
        s = 1.0 - s

    rows, cols = s.shape
    relief = float(relief_mm)
    w_mm, h_mm = physical_size_mm
    xs = np.linspace(0, w_mm, cols, dtype=np.float32)
    ys = np.linspace(0, h_mm, rows, dtype=np.float32)
    X, Y = np.meshgrid(xs, ys)

    p = 2.8  # Fundamental spatial period in mm (tuned for finger pulp perception)

    if texture_type == "Dots":
        # Staggered Gaussian stippling
        row_idx = np.floor(Y / (p * 0.866)).astype(int)
        X_s = X + (row_idx % 2) * (p / 2.0)
        dx = np.mod(X_s, p) - p / 2.0
        dy = np.mod(Y, p * 0.866) - (p * 0.866) / 2.0
        r2 = dx**2 + dy**2
        sigma = 0.55
        t = np.exp(-r2 / (2.0 * sigma**2)) * s * relief

    elif texture_type == "Stripes":
        # Parallel ridges
        t = 0.5 * (1.0 + np.cos(2.0 * np.pi * X / p)) * s * relief

    elif texture_type == "Grid":
        # Orthogonal crosshatch
        gx = 0.5 * (1.0 + np.cos(2.0 * np.pi * X / p))
        gy = 0.5 * (1.0 + np.cos(2.0 * np.pi * Y / p))
        t = np.maximum(gx, gy) * s * relief

    elif texture_type == "Waves":
        # Sinusoidal rippling surface
        phase = np.sin(2.0 * np.pi * Y / (2.5 * p))
        t = 0.5 * (1.0 + np.sin(2.0 * np.pi * X / p + phase)) * s * relief

    elif texture_type == "Scales":
        # Overlapping fish scales / shingles
        row_idx = np.floor(Y / (p * 0.7)).astype(int)
        X_s = X + (row_idx % 2) * (p / 2.0)
        dx = np.mod(X_s, p) - p / 2.0
        dy = np.mod(Y, p * 0.7)
        r = np.sqrt(dx**2 + (dy * 1.3)**2)
        t = np.clip(1.0 - r / (p * 0.65), 0.0, 1.0) * s * relief

    elif texture_type == "Honeycomb":
        # Hexagonal cell network
        hx = p * 1.15
        hy = hx * np.sqrt(3) / 2.0
        mx1 = np.mod(X, hx) - hx / 2.0
        my1 = np.mod(Y, 2.0 * hy) - hy
        d1 = np.sqrt(mx1**2 + my1**2)

        mx2 = np.mod(X + hx / 2.0, hx) - hx / 2.0
        my2 = np.mod(Y + hy, 2.0 * hy) - hy
        d2 = np.sqrt(mx2**2 + my2**2)

        d_hex = np.minimum(d1, d2)
        wall = np.clip(1.0 - np.abs(d_hex - hx * 0.35) / (hx * 0.16), 0.0, 1.0)
        t = wall * s * relief

    else:
        t = np.zeros_like(s)

    return t.astype(np.float32)


# ==============================================================================
# SECTION 5: TKINTER VECTOR TEXTURE ICONS
# ==============================================================================

def draw_texture_icon(canvas, texture_name, is_selected=False):
    """Draw a clean, resolution-independent vector pattern inside a small canvas."""
    canvas.delete("all")
    w = canvas.winfo_width() or 46
    h = canvas.winfo_height() or 34
    fg = "#2563EB" if is_selected else "#64748B"
    bg = "#EFF6FF" if is_selected else "#FFFFFF"
    canvas.configure(bg=bg)

    if texture_name == "Dots":
        # Staggered dots
        for row in range(3):
            y = 7 + row * 10
            x_off = 6 if row % 2 == 1 else 0
            for col in range(4):
                x = 8 + col * 10 + x_off
                if x < w - 6:
                    canvas.create_oval(x - 2.5, y - 2.5, x + 2.5, y + 2.5, fill=fg, outline="")

    elif texture_name == "Stripes":
        for x in [10, 18, 26, 34]:
            canvas.create_line(x, 5, x, h - 5, fill=fg, width=2.5)

    elif texture_name == "Grid":
        for x in [12, 23, 34]:
            canvas.create_line(x, 5, x, h - 5, fill=fg, width=1.8)
        for y in [9, 17, 25]:
            canvas.create_line(6, y, w - 6, y, fill=fg, width=1.8)

    elif texture_name == "Waves":
        pts = []
        for xi in range(6, w - 6, 2):
            yi = 17 + int(6.0 * math.sin(xi * 0.28))
            pts.extend([xi, yi])
        if len(pts) >= 4:
            canvas.create_line(*pts, fill=fg, width=2.2, smooth=True)
            # Second parallel wave
            pts2 = [p if i % 2 == 0 else p + 8 for i, p in enumerate(pts)]
            canvas.create_line(*pts2, fill=fg, width=1.8, smooth=True)

    elif texture_name == "Scales":
        # Scallop arches
        for row in range(2):
            y = 12 + row * 11
            x_off = 7 if row % 2 == 1 else 0
            for col in range(3):
                x = 7 + col * 14 + x_off
                if x + 12 < w:
                    canvas.create_arc(x, y - 6, x + 12, y + 6, start=0, extent=180,
                                      style="arc", outline=fg, width=1.8)

    elif texture_name == "Honeycomb":
        # Hexagonal rings
        def hex_pts(cx, cy, r):
            pts = []
            for i in range(6):
                ang = i * math.pi / 3.0
                pts.extend([cx + r * math.cos(ang), cy + r * math.sin(ang)])
            return pts

        canvas.create_polygon(hex_pts(16, 17, 7.5), outline=fg, fill="", width=1.6)
        canvas.create_polygon(hex_pts(30, 17, 7.5), outline=fg, fill="", width=1.6)


# ==============================================================================
# SECTION 6: USER INTERFACE (TAMP-OS v2 DESKTOP GUI)
# ==============================================================================

class TAMPGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("TAMP-OS Lithograph Maker v2")
        self.root.geometry("1160x860")
        self.root.minsize(980, 720)
        self.root.configure(bg="#F1F5F9")

        self.cfg = load_settings()
        self.mode = self.cfg.get("mode", "os")  # "os" or "chroma"

        self.images_data = []  # list of dicts: {"path", "width", "height", "quality", "invert", "analysis"}
        self.selected_idx = 0
        self.is_generating = False

        self._init_vars()
        self._build_layout()
        self._load_default_examples_if_available()
        self._update_mode_ui()
        self._refresh_image_table()

    def _init_vars(self):
        self.printer_profile_var = tk.StringVar(value=self.cfg.get("printer_profile", "Standard FDM / 0.4 mm nozzle"))
        self.selected_preset_var = tk.StringVar(value=self.cfg.get("selected_preset", "Medium"))
        self.output_dir_var = tk.StringVar(value=self.cfg.get("output_dir", str(Path.home() / "TAMP_output")))

        self.fmt_stl_var = tk.BooleanVar(value=self.cfg.get("fmt_stl", True))
        self.fmt_3mf_var = tk.BooleanVar(value=self.cfg.get("fmt_3mf", False))
        self.fmt_glb_var = tk.BooleanVar(value=self.cfg.get("fmt_glb", False))

        self.size_x_var = tk.StringVar(value=self.cfg.get("size_x", "100"))
        self.size_y_var = tk.StringVar(value=self.cfg.get("size_y", "auto"))
        self.nozzle_var = tk.StringVar(value=self.cfg.get("nozzle", "0.4"))
        self.layer_var = tk.StringVar(value=self.cfg.get("layer", "0.12"))
        self.relief_var = tk.StringVar(value=self.cfg.get("relief", "3.0"))
        self.res_override_var = tk.StringVar(value="")
        self.blur_var = tk.StringVar(value=self.cfg.get("blur", "1.2"))
        self.base_thickness_var = tk.StringVar(value=self.cfg.get("base_thickness", "1.2"))
        self.flip_var = tk.BooleanVar(value=self.cfg.get("flip", True))

        # Chroma vars
        self.chroma_colormap_var = tk.StringVar(value=self.cfg.get("chroma_colormap", "Inferno"))
        self.chroma_ramp_var = tk.DoubleVar(value=self.cfg.get("chroma_ramp_elevation", 1.8))
        self.chroma_texture_var = tk.StringVar(value=self.cfg.get("chroma_texture", "Honeycomb"))
        self.chroma_relief_var = tk.DoubleVar(value=self.cfg.get("chroma_texture_relief", 0.6))
        self.chroma_polarity_var = tk.BooleanVar(value=self.cfg.get("chroma_polarity_inverted", False))

        self.advanced_open = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Ready.")

    def _build_layout(self):
        # 1. Top Header Bar
        header = tk.Frame(self.root, bg="#1E293B", height=64)
        header.pack(side=tk.TOP, fill=tk.X)
        header.pack_propagate(False)

        # Title and subtitle
        title_box = tk.Frame(header, bg="#1E293B")
        title_box.pack(side=tk.LEFT, padx=18, pady=8)
        tk.Label(title_box, text="TAMP-OS Lithograph Maker", font=("Segoe UI", 15, "bold"),
                 fg="#F8FAFC", bg="#1E293B").pack(anchor="w")
        tk.Label(title_box, text="Microscopy images to tactile 3D prints", font=("Segoe UI", 8),
                 fg="#94A3B8", bg="#1E293B").pack(anchor="w")

        # Right Header Items
        header_right = tk.Frame(header, bg="#1E293B")
        header_right.pack(side=tk.RIGHT, padx=18, pady=12)

        tk.Button(header_right, text="Help & guide", font=("Segoe UI", 9),
                  bg="#334155", fg="#F8FAFC", activebackground="#475569",
                  relief="flat", cursor="hand2", padx=10, command=self._show_help).pack(side=tk.RIGHT, padx=6)

        tk.Label(header_right, text="v2.1", font=("Segoe UI", 9, "bold"),
                 fg="#38BDF8", bg="#1E293B").pack(side=tk.RIGHT, padx=8)

        # Segmented Mode Switch [ TAMP-OS | TAMP-OS Chroma ]
        switch_frame = tk.Frame(header, bg="#0F172A", bd=1, relief="solid")
        switch_frame.pack(side=tk.RIGHT, padx=20, pady=12)

        self.btn_mode_os = tk.Button(switch_frame, text="TAMP-OS", font=("Segoe UI", 10, "bold"),
                                     bd=0, padx=14, pady=4, cursor="hand2", command=lambda: self._set_mode("os"))
        self.btn_mode_os.pack(side=tk.LEFT)

        self.btn_mode_chroma = tk.Button(switch_frame, text="TAMP-OS Chroma", font=("Segoe UI", 10, "bold"),
                                         bd=0, padx=14, pady=4, cursor="hand2", command=lambda: self._set_mode("chroma"))
        self.btn_mode_chroma.pack(side=tk.LEFT)

        # 2. Main 2-Column Content Split
        main_content = tk.Frame(self.root, bg="#F1F5F9")
        main_content.pack(fill=tk.BOTH, expand=True, padx=14, pady=10)

        # Left Column (Images & Live Preview)
        self.left_col = tk.Frame(main_content, bg="#FFFFFF", relief="ridge", bd=1, width=540)
        self.left_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 7))

        # Right Column (Settings & Chroma parameters)
        self.right_col = tk.Frame(main_content, bg="#FFFFFF", relief="ridge", bd=1, width=560)
        self.right_col.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(7, 0))

        # 3. Bottom Status Bar
        bottom_bar = tk.Frame(self.root, bg="#FFFFFF", relief="ridge", bd=1, height=60)
        bottom_bar.pack(side=tk.BOTTOM, fill=tk.X, padx=14, pady=(0, 10))
        bottom_bar.pack_propagate(False)

        self.status_label = tk.Label(bottom_bar, textvariable=self.status_var,
                                     font=("Segoe UI", 9), fg="#334155", bg="#FFFFFF")
        self.status_label.pack(side=tk.LEFT, padx=16, pady=14)

        self.progress_bar = ttk.Progressbar(bottom_bar, orient=tk.HORIZONTAL, length=240, mode="determinate")
        self.progress_bar.pack(side=tk.LEFT, padx=10, pady=14)

        self.btn_generate = tk.Button(bottom_bar, text="Generate print files",
                                      font=("Segoe UI", 11, "bold"), bg="#2563EB", fg="#FFFFFF",
                                      activebackground="#1D4ED8", activeforeground="#FFFFFF",
                                      relief="flat", cursor="hand2", padx=20, pady=6, command=self._start_generation)
        self.btn_generate.pack(side=tk.RIGHT, padx=16, pady=10)

        tk.Button(bottom_bar, text="Open output folder", font=("Segoe UI", 9),
                  bg="#F1F5F9", fg="#334155", relief="flat", cursor="hand2",
                  padx=12, pady=6, command=self._open_output_folder).pack(side=tk.RIGHT, padx=6, pady=10)

        # Build column internals
        self._build_left_column()
        self._build_right_column()

    # --------------------------------------------------------------------------
    # LEFT COLUMN: IMAGES & PREVIEW
    # --------------------------------------------------------------------------
    def _build_left_column(self):
        f = self.left_col

        # Section 1: Images Header
        hdr = tk.Frame(f, bg="#FFFFFF")
        hdr.pack(fill=tk.X, padx=14, pady=(12, 6))

        tk.Label(hdr, text="1. Images", font=("Segoe UI", 12, "bold"),
                 fg="#0F172A", bg="#FFFFFF").pack(side=tk.LEFT)
        self.lbl_img_count = tk.Label(hdr, text="0 images", font=("Segoe UI", 9),
                                      fg="#64748B", bg="#FFFFFF")
        self.lbl_img_count.pack(side=tk.LEFT, padx=8)

        tk.Button(hdr, text="+ Add images…", font=("Segoe UI", 9, "bold"),
                  bg="#EFF6FF", fg="#2563EB", activebackground="#DBEAFE",
                  relief="flat", cursor="hand2", padx=10, pady=2,
                  command=self._add_images_dialog).pack(side=tk.RIGHT)
        tk.Button(hdr, text="Clear", font=("Segoe UI", 8),
                  bg="#F8FAFC", fg="#94A3B8", relief="flat", cursor="hand2",
                  command=self._clear_images).pack(side=tk.RIGHT, padx=4)

        # Images Table
        tbl_container = tk.Frame(f, bg="#F8FAFC", relief="solid", bd=1, height=130)
        tbl_container.pack(fill=tk.X, padx=14, pady=4)
        tbl_container.pack_propagate(False)

        # Table header
        th = tk.Frame(tbl_container, bg="#E2E8F0")
        th.pack(fill=tk.X)
        tk.Label(th, text="Image", font=("Segoe UI", 8, "bold"), fg="#475569", bg="#E2E8F0", width=28, anchor="w").pack(side=tk.LEFT, padx=6, pady=3)
        tk.Label(th, text="Quality", font=("Segoe UI", 8, "bold"), fg="#475569", bg="#E2E8F0", width=12, anchor="center").pack(side=tk.LEFT, padx=4, pady=3)
        self.th_invert_lbl = tk.Label(th, text="Invert", font=("Segoe UI", 8, "bold"), fg="#475569", bg="#E2E8F0", width=10, anchor="center")
        self.th_invert_lbl.pack(side=tk.LEFT, padx=4, pady=3)

        # Scrollable image items list
        self.tbl_canvas = tk.Canvas(tbl_container, bg="#FFFFFF", bd=0, highlightthickness=0)
        tbl_scrollbar = ttk.Scrollbar(tbl_container, orient="vertical", command=self.tbl_canvas.yview)
        self.tbl_inner = tk.Frame(self.tbl_canvas, bg="#FFFFFF")
        self.tbl_canvas.configure(yscrollcommand=tbl_scrollbar.set)
        tbl_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tbl_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tbl_win = self.tbl_canvas.create_window((0, 0), window=self.tbl_inner, anchor="nw")
        self.tbl_inner.bind("<Configure>", lambda e: self.tbl_canvas.configure(scrollregion=self.tbl_canvas.bbox("all")))
        self.tbl_canvas.bind("<Configure>", lambda e: self.tbl_canvas.itemconfig(self.tbl_win, width=e.width))

        # Preview Section
        sep = ttk.Separator(f, orient="horizontal")
        sep.pack(fill=tk.X, padx=14, pady=8)

        prev_hdr = tk.Frame(f, bg="#FFFFFF")
        prev_hdr.pack(fill=tk.X, padx=14, pady=(2, 4))
        self.lbl_preview_title = tk.Label(prev_hdr, text="Relief preview", font=("Segoe UI", 11, "bold"),
                                          fg="#0F172A", bg="#FFFFFF")
        self.lbl_preview_title.pack(side=tk.LEFT)

        tk.Button(prev_hdr, text="Open 3D view", font=("Segoe UI", 9, "bold"),
                  bg="#F0FDF4", fg="#16A34A", activebackground="#DCFCE7",
                  relief="flat", cursor="hand2", padx=10, pady=2,
                  command=self._launch_pyvista_3d).pack(side=tk.RIGHT)

        # Meta tags badge row
        self.meta_badge_frame = tk.Frame(f, bg="#FFFFFF")
        self.meta_badge_frame.pack(fill=tk.X, padx=14, pady=2)
        self.lbl_meta_raised = tk.Label(self.meta_badge_frame, text="Raised: Light areas", font=("Segoe UI", 8),
                                        bg="#F1F5F9", fg="#475569", padx=6, pady=2)
        self.lbl_meta_raised.pack(side=tk.LEFT, padx=(0, 4))
        self.lbl_meta_size = tk.Label(self.meta_badge_frame, text="Size: 100 × 75 mm", font=("Segoe UI", 8),
                                      bg="#F1F5F9", fg="#475569", padx=6, pady=2)
        self.lbl_meta_size.pack(side=tk.LEFT, padx=4)
        self.lbl_meta_res = tk.Label(self.meta_badge_frame, text="Res: 256 px", font=("Segoe UI", 8),
                                     bg="#F1F5F9", fg="#475569", padx=6, pady=2)
        self.lbl_meta_res.pack(side=tk.LEFT, padx=4)
        self.lbl_meta_stl = tk.Label(self.meta_badge_frame, text="Est. STL: ~9.4 MB", font=("Segoe UI", 8),
                                     bg="#F1F5F9", fg="#475569", padx=6, pady=2)
        self.lbl_meta_stl.pack(side=tk.LEFT, padx=4)

        # Preview Display Container
        self.prev_container = tk.Frame(f, bg="#0F172A", height=280)
        self.prev_container.pack(fill=tk.BOTH, expand=True, padx=14, pady=6)
        self.lbl_preview_image = tk.Label(self.prev_container, bg="#0F172A")
        self.lbl_preview_image.pack(fill=tk.BOTH, expand=True)

        # Cross section plot container (visible in Chroma mode)
        self.plot_container = tk.Frame(f, bg="#FFFFFF", height=100)
        self.plot_canvas = None

        # Helper hint text at bottom of left column
        self.lbl_preview_hint = tk.Label(f, text="Light = raised, dark = low. Check this before generating: if the feature you want to feel is sunk, tick Invert.",
                                         font=("Segoe UI", 8), fg="#64748B", bg="#FFFFFF", wraplength=480, justify="left")
        self.lbl_preview_hint.pack(fill=tk.X, padx=14, pady=(2, 10))

    # --------------------------------------------------------------------------
    # RIGHT COLUMN: CHROMA CONTROLS + SHARED SETTINGS
    # --------------------------------------------------------------------------
    def _build_right_column(self):
        f = self.right_col

        # Scrollable container for the right column
        r_canvas = tk.Canvas(f, bg="#FFFFFF", bd=0, highlightthickness=0)
        r_scrollbar = ttk.Scrollbar(f, orient="vertical", command=r_canvas.yview)
        self.r_inner = tk.Frame(r_canvas, bg="#FFFFFF")
        r_canvas.configure(yscrollcommand=r_scrollbar.set)
        r_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        r_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        r_win = r_canvas.create_window((0, 0), window=self.r_inner, anchor="nw")
        self.r_inner.bind("<Configure>", lambda e: r_canvas.configure(scrollregion=r_canvas.bbox("all")))
        r_canvas.bind("<Configure>", lambda e: r_canvas.itemconfig(r_win, width=e.width))

        rf = self.r_inner

        # -------------------- CHROMA CONTAINER (TOP OF RIGHT COL) --------------------
        self.chroma_container = tk.Frame(rf, bg="#FFFFFF")
        self.chroma_container.pack(fill=tk.X, padx=0, pady=0)
        self.chroma_frame = tk.Frame(self.chroma_container, bg="#F8FAFC", bd=1, relief="solid")
        self.chroma_frame.pack(fill=tk.X, padx=14, pady=(12, 6))

        ch_hdr = tk.Frame(self.chroma_frame, bg="#F8FAFC")
        ch_hdr.pack(fill=tk.X, padx=12, pady=(10, 4))
        tk.Label(ch_hdr, text="Chroma · colormap & texture", font=("Segoe UI", 11, "bold"),
                 fg="#0F172A", bg="#F8FAFC").pack(anchor="w")
        tk.Label(ch_hdr, text="Color value → ramp height + texture", font=("Segoe UI", 8),
                 fg="#64748B", bg="#F8FAFC").pack(anchor="w")

        # Colormap row
        cm_row = tk.Frame(self.chroma_frame, bg="#F8FAFC")
        cm_row.pack(fill=tk.X, padx=12, pady=4)
        tk.Label(cm_row, text="Colormap:", font=("Segoe UI", 9, "bold"),
                 fg="#334155", bg="#F8FAFC").pack(side=tk.LEFT)

        self.cm_combo = ttk.Combobox(cm_row, textvariable=self.chroma_colormap_var,
                                     values=SUPPORTED_COLORMAPS, state="readonly", width=14)
        self.cm_combo.pack(side=tk.LEFT, padx=8)
        self.cm_combo.bind("<<ComboboxSelected>>", self._on_colormap_changed)

        # Gradient Canvas preview bar
        self.cmap_canvas = tk.Canvas(cm_row, width=140, height=18, bd=1, relief="solid")
        self.cmap_canvas.pack(side=tk.LEFT, padx=4)

        # Polarity checkbox
        pol_row = tk.Frame(self.chroma_frame, bg="#F8FAFC")
        pol_row.pack(fill=tk.X, padx=12, pady=2)
        tk.Checkbutton(pol_row, text="Invert polarity (high values = flat/untextured)",
                       variable=self.chroma_polarity_var, bg="#F8FAFC",
                       font=("Segoe UI", 8), command=self._update_preview).pack(anchor="w")

        # Ramp elevation slider
        ramp_row = tk.Frame(self.chroma_frame, bg="#F8FAFC")
        ramp_row.pack(fill=tk.X, padx=12, pady=(6, 2))
        tk.Label(ramp_row, text="Ramp elevation (mm):", font=("Segoe UI", 9, "bold"),
                 fg="#334155", bg="#F8FAFC").pack(side=tk.LEFT)
        self.lbl_ramp_val = tk.Label(ramp_row, text=f"{self.chroma_ramp_var.get():.1f} mm",
                                     font=("Segoe UI", 9, "bold"), fg="#2563EB", bg="#F8FAFC")
        self.lbl_ramp_val.pack(side=tk.RIGHT)

        s_ramp = ttk.Scale(self.chroma_frame, from_=0.5, to=4.0, variable=self.chroma_ramp_var,
                           command=self._on_ramp_slider_move)
        s_ramp.pack(fill=tk.X, padx=12, pady=2)
        s_ramp.bind("<ButtonRelease-1>", lambda e: self._update_preview())
        tk.Label(self.chroma_frame, text="Macroscopic slope on top of the 1.2 mm solid base",
                 font=("Segoe UI", 7), fg="#64748B", bg="#F8FAFC").pack(anchor="w", padx=12, pady=(0, 6))

        # Texture Library grid
        tk.Label(self.chroma_frame, text="Texture library", font=("Segoe UI", 9, "bold"),
                 fg="#334155", bg="#F8FAFC").pack(anchor="w", padx=12, pady=(4, 2))

        self.tex_grid = tk.Frame(self.chroma_frame, bg="#F8FAFC")
        self.tex_grid.pack(fill=tk.X, padx=12, pady=2)
        self.tex_buttons = {}
        textures = ["Dots", "Stripes", "Grid", "Waves", "Scales", "Honeycomb"]
        for i, tex in enumerate(textures):
            card = tk.Frame(self.tex_grid, bg="#FFFFFF", bd=1, relief="solid", cursor="hand2")
            card.grid(row=0, column=i, padx=3, pady=2, sticky="nsew")
            self.tex_grid.columnconfigure(i, weight=1)

            cv = tk.Canvas(card, width=44, height=30, bd=0, highlightthickness=0, bg="#FFFFFF")
            cv.pack(padx=2, pady=2)

            lbl = tk.Label(card, text=tex, font=("Segoe UI", 7, "bold"), bg="#FFFFFF", fg="#334155")
            lbl.pack(pady=(0, 3))

            def make_handler(t=tex):
                return lambda e: self._select_texture(t)

            card.bind("<Button-1>", make_handler())
            cv.bind("<Button-1>", make_handler())
            lbl.bind("<Button-1>", make_handler())

            self.tex_buttons[tex] = {"frame": card, "canvas": cv, "label": lbl}

        # Texture relief slider
        t_relief_row = tk.Frame(self.chroma_frame, bg="#F8FAFC")
        t_relief_row.pack(fill=tk.X, padx=12, pady=(6, 2))
        tk.Label(t_relief_row, text="Texture relief (mm):", font=("Segoe UI", 9, "bold"),
                 fg="#334155", bg="#F8FAFC").pack(side=tk.LEFT)
        self.lbl_t_relief_val = tk.Label(t_relief_row, text=f"{self.chroma_relief_var.get():.2f} mm",
                                         font=("Segoe UI", 9, "bold"), fg="#2563EB", bg="#F8FAFC")
        self.lbl_t_relief_val.pack(side=tk.RIGHT)

        s_t_relief = ttk.Scale(self.chroma_frame, from_=0.2, to=1.5, variable=self.chroma_relief_var,
                               command=self._on_texture_relief_slider_move)
        s_t_relief.pack(fill=tk.X, padx=12, pady=2)
        s_t_relief.bind("<ButtonRelease-1>", lambda e: self._update_preview())
        tk.Label(self.chroma_frame, text="Height of the micro-texture (0.2–1.5 mm)",
                 font=("Segoe UI", 7), fg="#64748B", bg="#F8FAFC").pack(anchor="w", padx=12, pady=(0, 8))

        self._refresh_texture_buttons()
        self._redraw_colormap_bar()

        # -------------------- SHARED: 2. PRINTER --------------------
        p_hdr = tk.Frame(rf, bg="#FFFFFF")
        p_hdr.pack(fill=tk.X, padx=14, pady=(10, 2))
        tk.Label(p_hdr, text="2. Printer", font=("Segoe UI", 11, "bold"),
                 fg="#0F172A", bg="#FFFFFF").pack(side=tk.LEFT)

        pr_row = tk.Frame(rf, bg="#FFFFFF")
        pr_row.pack(fill=tk.X, padx=14, pady=2)
        profiles = [
            "Standard FDM / 0.4 mm nozzle",
            "Fine-detail FDM / 0.2 mm nozzle",
            "Large-nozzle FDM / 0.6 mm nozzle",
            "Custom"
        ]
        self.pr_menu = ttk.Combobox(pr_row, textvariable=self.printer_profile_var,
                                    values=profiles, state="readonly", width=30)
        self.pr_menu.pack(side=tk.LEFT)
        self.pr_menu.bind("<<ComboboxSelected>>", self._on_printer_profile_changed)

        self.lbl_pr_summary = tk.Label(pr_row, text="0.4 mm nozzle · 0.12 mm layers · 100 mm wide",
                                       font=("Segoe UI", 8), fg="#64748B", bg="#FFFFFF")
        self.lbl_pr_summary.pack(side=tk.LEFT, padx=10)

        # -------------------- SHARED: 3. QUALITY --------------------
        q_hdr = tk.Frame(rf, bg="#FFFFFF")
        q_hdr.pack(fill=tk.X, padx=14, pady=(12, 2))
        tk.Label(q_hdr, text="3. Quality", font=("Segoe UI", 11, "bold"),
                 fg="#0F172A", bg="#FFFFFF").pack(side=tk.LEFT)
        tk.Label(q_hdr, text="Click a card to apply to all images", font=("Segoe UI", 8),
                 fg="#64748B", bg="#FFFFFF").pack(side=tk.LEFT, padx=8)

        # 3 Quality cards row
        q_cards_frame = tk.Frame(rf, bg="#FFFFFF")
        q_cards_frame.pack(fill=tk.X, padx=14, pady=4)
        self.q_cards = {}
        q_specs = [
            ("Low", "Quick draft\n~2.3 MB STL · 128 px", "#F0FDF4", "#16A34A"),
            ("Medium", "Balanced detail\n~9.4 MB STL · 256 px", "#EFF6FF", "#2563EB"),
            ("High", "Maximum detail\n~37.5 MB STL · 512 px", "#FFF7ED", "#EA580C")
        ]
        for col, (name, desc, bg_c, fg_c) in enumerate(q_specs):
            card = tk.Frame(q_cards_frame, bg=bg_c, bd=1, relief="solid", cursor="hand2")
            card.grid(row=0, column=col, padx=4, pady=2, sticky="nsew")
            q_cards_frame.columnconfigure(col, weight=1)

            t_lbl = tk.Label(card, text=name, font=("Segoe UI", 10, "bold"), bg=bg_c, fg=fg_c)
            t_lbl.pack(pady=(6, 2))
            d_lbl = tk.Label(card, text=desc, font=("Segoe UI", 8), bg=bg_c, fg="#475569", justify="center")
            d_lbl.pack(padx=4, pady=(0, 6))

            def make_q_handler(q_val=name):
                return lambda e: self._select_quality_card(q_val)

            card.bind("<Button-1>", make_q_handler())
            t_lbl.bind("<Button-1>", make_q_handler())
            d_lbl.bind("<Button-1>", make_q_handler())
            self.q_cards[name] = {"frame": card, "bg": bg_c, "title": t_lbl, "desc": d_lbl}

        self.lbl_suggestion = tk.Label(rf, text="Add images to see resolution guidance.",
                                       font=("Segoe UI", 8), fg="#0284C7", bg="#FFFFFF", wraplength=480, justify="left")
        self.lbl_suggestion.pack(anchor="w", padx=14, pady=2)

        # -------------------- SHARED: 4. OUTPUT --------------------
        o_hdr = tk.Frame(rf, bg="#FFFFFF")
        o_hdr.pack(fill=tk.X, padx=14, pady=(12, 2))
        tk.Label(o_hdr, text="4. Output", font=("Segoe UI", 11, "bold"),
                 fg="#0F172A", bg="#FFFFFF").pack(side=tk.LEFT)

        out_row = tk.Frame(rf, bg="#FFFFFF")
        out_row.pack(fill=tk.X, padx=14, pady=2)
        tk.Label(out_row, text="Folder:", font=("Segoe UI", 9), fg="#334155", bg="#FFFFFF").pack(side=tk.LEFT)
        self.ent_output = tk.Entry(out_row, textvariable=self.output_dir_var, font=("Segoe UI", 8), width=36)
        self.ent_output.pack(side=tk.LEFT, padx=6)
        tk.Button(out_row, text="Browse…", font=("Segoe UI", 8),
                  command=self._browse_output_dir).pack(side=tk.LEFT)

        fmt_row = tk.Frame(rf, bg="#FFFFFF")
        fmt_row.pack(fill=tk.X, padx=14, pady=4)
        tk.Label(fmt_row, text="Formats:", font=("Segoe UI", 9), fg="#334155", bg="#FFFFFF").pack(side=tk.LEFT)
        tk.Checkbutton(fmt_row, text=".STL", variable=self.fmt_stl_var, bg="#FFFFFF", font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT, padx=6)
        tk.Checkbutton(fmt_row, text=".3MF", variable=self.fmt_3mf_var, bg="#FFFFFF", font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=6)
        tk.Checkbutton(fmt_row, text=".GLB", variable=self.fmt_glb_var, bg="#FFFFFF", font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=6)

        # -------------------- ADVANCED SETTINGS (COLLAPSIBLE) --------------------
        adv_toggle_row = tk.Frame(rf, bg="#FFFFFF")
        adv_toggle_row.pack(fill=tk.X, padx=14, pady=(12, 2))
        self.btn_adv_toggle = tk.Button(adv_toggle_row, text="▶ Advanced settings", font=("Segoe UI", 9, "bold"),
                                        fg="#475569", bg="#FFFFFF", relief="flat", cursor="hand2",
                                        command=self._toggle_advanced)
        self.btn_adv_toggle.pack(side=tk.LEFT)
        tk.Label(adv_toggle_row, text="Physical dimensions, layer height, blur, base",
                 font=("Segoe UI", 8), fg="#94A3B8", bg="#FFFFFF").pack(side=tk.LEFT, padx=6)

        self.adv_frame = tk.Frame(rf, bg="#F8FAFC", bd=1, relief="solid")
        # Populated in _build_advanced_controls
        self._build_advanced_controls()

    def _build_advanced_controls(self):
        af = self.adv_frame
        params = [
            ("Print width (mm)", self.size_x_var, "Width of lithograph"),
            ("Print height (mm)", self.size_y_var, "'auto' preserves aspect ratio"),
            ("Nozzle diameter (mm)", self.nozzle_var, "Smallest printable XY detail"),
            ("Layer height (mm)", self.layer_var, "Height of each relief step"),
            ("Relief height (mm)", self.relief_var, "Darkest to lightest (TAMP-OS mode)"),
            ("Resolution override (px)", self.res_override_var, "Overrides quality preset"),
            ("Blur (sigma)", self.blur_var, "Smooths sensor noise before meshing"),
            ("Base thickness (mm)", self.base_thickness_var, "Solid rigid base below relief"),
        ]
        for i, (label_txt, var, hint) in enumerate(params):
            r = tk.Frame(af, bg="#F8FAFC")
            r.pack(fill=tk.X, padx=10, pady=2)
            tk.Label(r, text=label_txt + ":", font=("Segoe UI", 8), fg="#334155", bg="#F8FAFC", width=20, anchor="w").pack(side=tk.LEFT)
            tk.Entry(r, textvariable=var, font=("Segoe UI", 8), width=10).pack(side=tk.LEFT, padx=4)
            tk.Label(r, text=hint, font=("Segoe UI", 7), fg="#94A3B8", bg="#F8FAFC").pack(side=tk.LEFT, padx=6)

        fl_row = tk.Frame(af, bg="#F8FAFC")
        fl_row.pack(fill=tk.X, padx=10, pady=(4, 6))
        tk.Checkbutton(fl_row, text="Flip vertically for printing (matches image orientation)",
                       variable=self.flip_var, bg="#F8FAFC", font=("Segoe UI", 8)).pack(anchor="w")

    def _toggle_advanced(self):
        if self.advanced_open.get():
            self.adv_frame.pack_forget()
            self.advanced_open.set(False)
            self.btn_adv_toggle.configure(text="▶ Advanced settings")
        else:
            self.adv_frame.pack(fill=tk.X, padx=14, pady=4, after=self.btn_adv_toggle.master)
            self.advanced_open.set(True)
            self.btn_adv_toggle.configure(text="▼ Advanced settings")

    # --------------------------------------------------------------------------
    # MODE SWITCHING & UI ADAPTATION
    # --------------------------------------------------------------------------
    def _set_mode(self, mode):
        self.mode = mode
        self.cfg["mode"] = mode
        save_settings(self.cfg)
        self._update_mode_ui()
        self._refresh_image_table()
        self._update_preview()

    def _update_mode_ui(self):
        if self.mode == "os":
            self.btn_mode_os.configure(bg="#2563EB", fg="#FFFFFF", relief="flat")
            self.btn_mode_chroma.configure(bg="#0F172A", fg="#94A3B8", relief="flat")
            self.chroma_frame.pack_forget()
            self.th_invert_lbl.configure(text="Invert")
            self.lbl_preview_title.configure(text="Relief preview")
            self.lbl_preview_hint.configure(text="Light = raised, dark = low. Check this before generating: if the feature you want to feel is sunk, tick Invert.")
            self.btn_generate.configure(text="Generate print files")
            self.plot_container.pack_forget()
        else:
            self.btn_mode_os.configure(bg="#0F172A", fg="#94A3B8", relief="flat")
            self.btn_mode_chroma.configure(bg="#2563EB", fg="#FFFFFF", relief="flat")
            # Pack chroma frame inside container at top of right column
            self.chroma_frame.pack(fill=tk.X, padx=14, pady=(12, 6))
            self.th_invert_lbl.configure(text="Polarity")
            self.lbl_preview_title.configure(text="Live tactile preview")
            self.lbl_preview_hint.configure(text=f"Shaded relief with {self.chroma_texture_var.get()} texture. Grazing light shows how it will feel under the finger.")
            self.btn_generate.configure(text="Generate tactile files")
            self.plot_container.pack(fill=tk.X, padx=14, pady=(2, 6), before=self.lbl_preview_hint)

        self._refresh_texture_buttons()
        self._update_status_summary()

    # --------------------------------------------------------------------------
    # COLORMAP & TEXTURE SELECTION
    # --------------------------------------------------------------------------
    def _on_colormap_changed(self, event=None):
        self.cfg["chroma_colormap"] = self.chroma_colormap_var.get()
        save_settings(self.cfg)
        self._redraw_colormap_bar()
        self._update_preview()

    def _redraw_colormap_bar(self):
        cm_name = self.chroma_colormap_var.get()
        lut, _ = get_colormap_tree(cm_name)
        w = 140
        h = 18
        self.cmap_canvas.delete("all")
        for i in range(w):
            idx = int((i / (w - 1)) * 255)
            r, g, b = lut[idx]
            hex_c = f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"
            self.cmap_canvas.create_line(i, 0, i, h, fill=hex_c)

    def _select_texture(self, tex_name):
        self.chroma_texture_var.set(tex_name)
        self.cfg["chroma_texture"] = tex_name
        save_settings(self.cfg)
        self._refresh_texture_buttons()
        self.lbl_preview_hint.configure(text=f"Shaded relief with {tex_name} texture. Grazing light shows how it will feel under the finger.")
        self._update_preview()

    def _refresh_texture_buttons(self):
        sel = self.chroma_texture_var.get()
        for tex, widgets in self.tex_buttons.items():
            is_sel = (tex == sel)
            border_c = "#2563EB" if is_sel else "#CBD5E1"
            bg_c = "#EFF6FF" if is_sel else "#FFFFFF"
            fg_c = "#2563EB" if is_sel else "#334155"
            widgets["frame"].configure(bg=bg_c, highlightbackground=border_c, highlightthickness=2 if is_sel else 1)
            widgets["label"].configure(bg=bg_c, fg=fg_c)
            draw_texture_icon(widgets["canvas"], tex, is_selected=is_sel)

    def _on_ramp_slider_move(self, val):
        self.lbl_ramp_val.configure(text=f"{float(val):.1f} mm")

    def _on_texture_relief_slider_move(self, val):
        self.lbl_t_relief_val.configure(text=f"{float(val):.2f} mm")

    def _select_quality_card(self, q_val):
        self.selected_preset_var.set(q_val)
        self.cfg["selected_preset"] = q_val
        save_settings(self.cfg)
        for img in self.images_data:
            img["quality"] = q_val
        self._refresh_image_table()
        self._update_preview()
        self._update_status_summary()

    def _on_printer_profile_changed(self, event=None):
        prof = self.printer_profile_var.get()
        profiles = {
            "Standard FDM / 0.4 mm nozzle": ("0.4", "0.12", "100"),
            "Fine-detail FDM / 0.2 mm nozzle": ("0.2", "0.08", "80"),
            "Large-nozzle FDM / 0.6 mm nozzle": ("0.6", "0.20", "120"),
        }
        if prof in profiles:
            nz, ly, sz = profiles[prof]
            self.nozzle_var.set(nz)
            self.layer_var.set(ly)
            self.size_x_var.set(sz)
            self.lbl_pr_summary.configure(text=f"{nz} mm nozzle · {ly} mm layers · {sz} mm wide")
        else:
            self.lbl_pr_summary.configure(text="using values in Advanced settings")
        self._update_preview()

    # --------------------------------------------------------------------------
    # IMAGE MANAGEMENT & TABLE
    # --------------------------------------------------------------------------
    def _add_images_dialog(self):
        fnames = filedialog.askopenfilenames(
            title="Select Microscopy / Gradient Images",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp"), ("All files", "*.*")]
        )
        if fnames:
            self._add_image_paths(fnames)

    def _load_default_examples_if_available(self):
        """Pre-populate with example images from examples/ directory if present."""
        ex_dir = Path(__file__).parent / "examples"
        if ex_dir.exists():
            ex_files = []
            for name in ["SEM_5um_raw.png", "crab_spider.jpg", "input_li_gradient.png"]:
                p = ex_dir / name
                if p.exists():
                    ex_files.append(str(p))
            if ex_files:
                self._add_image_paths(ex_files, select_first=True)

    def _add_image_paths(self, paths, select_first=False):
        existing = {img["path"] for img in self.images_data}
        added_any = False
        for p in paths:
            if p not in existing and Path(p).exists():
                try:
                    analysis = analyze_image_quality(p)
                    suggested = recommend_preset_from_analysis(analysis)
                    self.images_data.append({
                        "path": p,
                        "name": Path(p).name,
                        "width": analysis["width"],
                        "height": analysis["height"],
                        "quality": suggested,
                        "invert": False,
                        "analysis": analysis
                    })
                    added_any = True
                except Exception as e:
                    print(f"Error loading {p}: {e}")

        if added_any:
            if select_first or self.selected_idx >= len(self.images_data):
                self.selected_idx = 0
            self._refresh_image_table()
            self._update_preview()
            self._update_status_summary()

    def _clear_images(self):
        self.images_data = []
        self.selected_idx = 0
        self._refresh_image_table()
        self._update_preview()
        self._update_status_summary()

    def _refresh_image_table(self):
        for w in self.tbl_inner.winfo_children():
            w.destroy()

        count = len(self.images_data)
        self.lbl_img_count.configure(text=f"{count} image{'s' if count != 1 else ''}")

        if not self.images_data:
            empty_lbl = tk.Label(self.tbl_inner, text="No images loaded. Click '+ Add images…' to get started.",
                                 font=("Segoe UI", 9), fg="#94A3B8", bg="#FFFFFF")
            empty_lbl.pack(pady=20)
            return

        for idx, img in enumerate(self.images_data):
            is_sel = (idx == self.selected_idx)
            row_bg = "#EFF6FF" if is_sel else "#FFFFFF"

            row = tk.Frame(self.tbl_inner, bg=row_bg, cursor="hand2")
            row.pack(fill=tk.X, pady=1)

            # Name & info label
            info_txt = f"{img['name']}\n{img['width']} × {img['height']} px · suggested {img['analysis'].get('exposure', '')[:10]}"
            n_lbl = tk.Label(row, text=info_txt, font=("Segoe UI", 8), fg="#0F172A", bg=row_bg,
                             width=28, anchor="w", justify="left")
            n_lbl.pack(side=tk.LEFT, padx=6, pady=2)

            # Quality Combobox
            q_var = tk.StringVar(value=img["quality"])
            cb = ttk.Combobox(row, textvariable=q_var, values=["Low", "Medium", "High"],
                              state="readonly", width=8)
            cb.pack(side=tk.LEFT, padx=4)

            def make_q_change(i=idx, v=q_var):
                def handler(e):
                    self.images_data[i]["quality"] = v.get()
                    self._update_preview()
                    self._update_status_summary()
                return handler

            cb.bind("<<ComboboxSelected>>", make_q_change())

            # Invert / Polarity button
            inv_text = ("Inverted" if img["invert"] else "Normal") if self.mode == "chroma" else ("On" if img["invert"] else "Off")
            inv_btn = tk.Button(row, text=inv_text, font=("Segoe UI", 8),
                                bg="#EFF6FF" if img["invert"] else "#F1F5F9",
                                fg="#2563EB" if img["invert"] else "#64748B",
                                width=8, relief="flat")
            inv_btn.pack(side=tk.LEFT, padx=4)

            def make_inv_toggle(i=idx, b=inv_btn):
                def handler():
                    self.images_data[i]["invert"] = not self.images_data[i]["invert"]
                    t = ("Inverted" if self.images_data[i]["invert"] else "Normal") if self.mode == "chroma" else ("On" if self.images_data[i]["invert"] else "Off")
                    b.configure(text=t, bg="#EFF6FF" if self.images_data[i]["invert"] else "#F1F5F9",
                                fg="#2563EB" if self.images_data[i]["invert"] else "#64748B")
                    self._update_preview()
                return handler

            inv_btn.configure(command=make_inv_toggle())

            # Row click selection
            def make_row_click(i=idx):
                def handler(e):
                    self.selected_idx = i
                    self._refresh_image_table()
                    self._update_preview()
                return handler

            row.bind("<Button-1>", make_row_click())
            n_lbl.bind("<Button-1>", make_row_click())

        # Update batch suggestion banner
        self._update_recommendation_banner()

    def _update_recommendation_banner(self):
        if not self.images_data:
            self.lbl_suggestion.configure(text="Add images to see resolution guidance.")
            return

        presets = [img["quality"] for img in self.images_data]
        rec = max(["Low", "Medium", "High"], key=presets.count)
        avg_range = sum(img["analysis"]["dynamic_range"] for img in self.images_data) / len(self.images_data)
        self.lbl_suggestion.configure(
            text=f"For these images we suggest {rec} (average contrast {avg_range:.0f}/255). Click to apply."
        )

    # --------------------------------------------------------------------------
    # LIVE TACTILE PREVIEW & CROSS-SECTION
    # --------------------------------------------------------------------------
    def _update_preview(self):
        if not self.images_data or self.selected_idx >= len(self.images_data):
            self.lbl_preview_image.configure(image="", text="No preview available")
            return

        active = self.images_data[self.selected_idx]
        img_path = active["path"]
        quality = active["quality"]
        invert = active["invert"]

        try:
            sz_x = float(self.size_x_var.get())
        except Exception:
            sz_x = 100.0

        # Determine target resolution
        q_res = {"Low": 128, "Medium": 256, "High": 512}.get(quality, 256)
        if self.res_override_var.get().strip():
            try:
                q_res = int(self.res_override_var.get().strip())
            except Exception:
                pass

        aspect = active["height"] / max(1, active["width"])
        sz_y = round(sz_x * aspect, 1)

        # Update preview badges
        self.lbl_meta_size.configure(text=f"Size: {sz_x:.0f} × {sz_y:.0f} mm")
        self.lbl_meta_res.configure(text=f"Res: {q_res} px")
        est_mb = estimate_stl_file_size(q_res, aspect)
        self.lbl_meta_stl.configure(text=f"Est. STL: ~{format_file_size(est_mb)}")

        target_cols = min(256, q_res)  # Fast preview resolution
        target_rows = max(2, int(round(target_cols * aspect)))

        raw_img = Image.open(img_path)

        if self.mode == "os":
            # Grayscale heightmap mode
            gray = raw_img.convert("L").resize((target_cols, target_rows), Image.LANCZOS)
            arr = np.array(gray, dtype=np.float32) / 255.0
            if invert:
                arr = 1.0 - arr
            self.lbl_meta_raised.configure(text="Raised: Dark areas" if invert else "Raised: Light areas")

            # Convert to PIL preview
            arr_u8 = (arr * 255).astype(np.uint8)
            prev_pil = Image.fromarray(arr_u8).resize((320, int(320 * aspect)), Image.NEAREST)
            self._display_preview_image(prev_pil)

        else:
            # Chroma mode: Hillshade + Cross-section
            self.lbl_meta_raised.configure(text="Raised: Low values" if invert else "Raised: High values")
            cm_name = self.chroma_colormap_var.get()
            s = decode_colormap(raw_img.resize((target_cols, target_rows), Image.LANCZOS), cm_name)

            ramp_elev = float(self.chroma_ramp_var.get())
            t_relief = float(self.chroma_relief_var.get())
            tex_type = self.chroma_texture_var.get()
            pol_inv = invert or self.chroma_polarity_var.get()

            z_base = float(self.base_thickness_var.get() or 1.2)
            z_ramp = build_ramp(target_rows, target_cols, (sz_x, sz_y), ramp_elev)
            z_tex = apply_texture(s, tex_type, (sz_x, sz_y), t_relief, polarity_inverted=pol_inv)
            Z = z_base + z_ramp + z_tex

            # 1. Hillshade rendering
            ls = LightSource(azdeg=315, altdeg=20)  # Grazing sunlight
            shaded = ls.shade(Z, cmap=plt.cm.copper, vert_exag=1.8, blend_mode="overlay")
            shaded_u8 = (shaded[:, :, :3] * 255).astype(np.uint8)
            hill_pil = Image.fromarray(shaded_u8).resize((320, int(320 * aspect)), Image.BILINEAR)
            self._display_preview_image(hill_pil)

            # 2. Cross section plot Z(x) in mm
            self._draw_cross_section_plot(Z, sz_x, z_base)

    def _display_preview_image(self, pil_img):
        tk_img = ImageTk.PhotoImage(pil_img)
        self.lbl_preview_image.configure(image=tk_img, text="")
        self.lbl_preview_image.image = tk_img

    def _draw_cross_section_plot(self, Z, width_mm, z_base):
        rows, cols = Z.shape
        mid_row = rows // 2
        z_slice = Z[mid_row, :]
        xs = np.linspace(0, width_mm, cols)

        fig = plt.Figure(figsize=(4.4, 0.9), dpi=80, facecolor="#FFFFFF")
        ax = fig.add_subplot(111)
        fig.subplots_adjust(left=0.14, right=0.96, top=0.88, bottom=0.28)

        ax.plot(xs, z_slice, color="#2563EB", lw=1.5, label="Surface Z(x)")
        ax.axhline(z_base, color="#94A3B8", ls="--", lw=1.0, label="Base 1.2mm")
        ax.set_ylabel("Z (mm)", fontsize=7, color="#475569")
        ax.set_xlabel("X width (mm)", fontsize=7, color="#475569")
        ax.tick_params(axis="both", labelsize=6, colors="#64748B")
        ax.set_ylim(0, max(4.0, float(np.max(Z)) + 0.5))

        for w in self.plot_container.winfo_children():
            w.destroy()

        self.plot_canvas = FigureCanvasTkAgg(fig, master=self.plot_container)
        self.plot_canvas.draw()
        self.plot_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    # --------------------------------------------------------------------------
    # 3D INTERACTIVE VISUALIZATION (PYVISTA)
    # --------------------------------------------------------------------------
    def _launch_pyvista_3d(self):
        if not PYVISTA_AVAILABLE:
            messagebox.showwarning("PyVista not installed", "Interactive 3D viewing requires pyvista. Run:\npip install pyvista")
            return

        if not self.images_data:
            messagebox.showinfo("No image", "Please load an image first.")
            return

        active = self.images_data[self.selected_idx]
        img_path = active["path"]
        quality = active["quality"]
        invert = active["invert"]

        try:
            sz_x = float(self.size_x_var.get())
        except Exception:
            sz_x = 100.0

        q_res = {"Low": 128, "Medium": 256, "High": 512}.get(quality, 256)
        aspect = active["height"] / max(1, active["width"])
        sz_y = round(sz_x * aspect, 1)

        cols = min(256, q_res)
        rows = max(2, int(round(cols * aspect)))

        def run_viewer():
            raw_img = Image.open(img_path)
            z_base = float(self.base_thickness_var.get() or 1.2)

            if self.mode == "os":
                gray = raw_img.convert("L").resize((cols, rows), Image.LANCZOS)
                arr = np.array(gray, dtype=np.float32) / 255.0
                if invert:
                    arr = 1.0 - arr
                relief_mm = float(self.relief_var.get() or 3.0)
                Z = z_base + arr * relief_mm
                title = f"TAMP-OS 3D: {active['name']}"
            else:
                s = decode_colormap(raw_img.resize((cols, rows), Image.LANCZOS), self.chroma_colormap_var.get())
                ramp_elev = float(self.chroma_ramp_var.get())
                t_relief = float(self.chroma_relief_var.get())
                tex_type = self.chroma_texture_var.get()
                pol_inv = invert or self.chroma_polarity_var.get()
                z_ramp = build_ramp(rows, cols, (sz_x, sz_y), ramp_elev)
                z_tex = apply_texture(s, tex_type, (sz_x, sz_y), t_relief, polarity_inverted=pol_inv)
                Z = z_base + z_ramp + z_tex
                title = f"TAMP-OS Chroma 3D: {active['name']} ({tex_type})"

            xs = np.linspace(0, sz_x, cols)
            ys = np.linspace(0, sz_y, rows)
            X, Y = np.meshgrid(xs, ys)

            grid = pv.StructuredGrid(X, Y, Z)
            grid["Elevation (mm)"] = Z.ravel(order="C")

            p = pv.Plotter(title=title)
            p.set_background("#0F172A")
            p.add_mesh(grid, cmap="copper" if self.mode == "chroma" else "viridis",
                       scalars="Elevation (mm)", show_scalar_bar=True, smooth_shading=True)
            p.show_grid(color="#475569")
            p.show()

        threading.Thread(target=run_viewer, daemon=True).start()

    # --------------------------------------------------------------------------
    # BATCH GENERATION (BACKGROUND THREAD)
    # --------------------------------------------------------------------------
    def _start_generation(self):
        if self.is_generating:
            return
        if not self.images_data:
            messagebox.showinfo("No images", "Please add at least one image to generate files.")
            return

        out_dir = Path(self.output_dir_var.get().strip() or str(Path.home() / "TAMP_output"))
        out_dir.mkdir(parents=True, exist_ok=True)
        self.cfg["output_dir"] = str(out_dir)
        save_settings(self.cfg)

        fmts = {
            "stl": self.fmt_stl_var.get(),
            "3mf": self.fmt_3mf_var.get(),
            "glb": self.fmt_glb_var.get(),
        }
        if not any(fmts.values()):
            messagebox.showwarning("No format selected", "Please select at least one format (.STL, .3MF, .GLB).")
            return

        self.is_generating = True
        self.btn_generate.configure(state="disabled", text="Generating…")
        self.progress_bar.configure(value=0, maximum=len(self.images_data))

        threading.Thread(target=self._generation_worker, args=(out_dir, fmts), daemon=True).start()

    def _generation_worker(self, out_dir, fmts):
        total = len(self.images_data)
        success_count = 0

        for i, img_info in enumerate(self.images_data):
            name_stem = Path(img_info["path"]).stem
            self.root.after(0, lambda n=img_info['name'], idx=i+1: self.status_var.set(f"Processing ({idx}/{total}): {n}…"))

            try:
                if self.mode == "os":
                    self._generate_os_item(img_info, out_dir, name_stem, fmts)
                else:
                    self._generate_chroma_item(img_info, out_dir, name_stem, fmts)
                success_count += 1
            except Exception as e:
                print(f"Error processing {img_info['name']}: {e}")

            self.root.after(0, lambda v=i+1: self.progress_bar.configure(value=v))

        self.root.after(0, lambda: self._on_generation_finished(success_count, total, out_dir))

    def _generate_os_item(self, img_info, out_dir, stem, fmts):
        quality = img_info["quality"]
        res = {"Low": 128, "Medium": 256, "High": 512}.get(quality, 256)
        if self.res_override_var.get().strip():
            try:
                res = int(self.res_override_var.get().strip())
            except Exception:
                pass

        try:
            sz_x = float(self.size_x_var.get())
        except Exception:
            sz_x = 100.0

        aspect = img_info["height"] / max(1, img_info["width"])
        sz_y = round(sz_x * aspect, 1)

        raw = Image.open(img_info["path"]).convert("L")
        target_rows = max(2, int(round(res * aspect)))
        resized = raw.resize((res, target_rows), Image.LANCZOS)
        arr = np.array(resized, dtype=np.float32)

        # Contrast stretch
        lo, hi = np.percentile(arr, [2.0, 98.0])
        arr = np.clip((arr - lo) / (hi - lo + 1e-8), 0.0, 1.0)

        # Blur
        blur_s = float(self.blur_var.get() or 1.2)
        if blur_s > 0:
            arr = gaussian_filter(arr, sigma=blur_s)

        if img_info["invert"]:
            arr = 1.0 - arr

        if self.flip_var.get():
            arr = np.flipud(arr)

        base_th = float(self.base_thickness_var.get() or 1.2)
        relief = float(self.relief_var.get() or 3.0)

        stl_path = out_dir / f"{stem}_TAMP_OS_{quality}.stl"
        heightmap_to_stl(arr, stl_path, base_thickness_mm=base_th, max_relief_mm=relief,
                         physical_size_mm=(sz_x, sz_y))
        convert_stl(stl_path, fmts)

    def _generate_chroma_item(self, img_info, out_dir, stem, fmts):
        quality = img_info["quality"]
        res = {"Low": 128, "Medium": 256, "High": 512}.get(quality, 256)
        if self.res_override_var.get().strip():
            try:
                res = int(self.res_override_var.get().strip())
            except Exception:
                pass

        try:
            sz_x = float(self.size_x_var.get())
        except Exception:
            sz_x = 100.0

        aspect = img_info["height"] / max(1, img_info["width"])
        sz_y = round(sz_x * aspect, 1)
        target_rows = max(2, int(round(res * aspect)))

        raw = Image.open(img_info["path"]).resize((res, target_rows), Image.LANCZOS)
        cm_name = self.chroma_colormap_var.get()
        s = decode_colormap(raw, cm_name)

        pol_inv = img_info["invert"] or self.chroma_polarity_var.get()
        ramp_elev = float(self.chroma_ramp_var.get())
        t_relief = float(self.chroma_relief_var.get())
        tex_type = self.chroma_texture_var.get()
        base_th = float(self.base_thickness_var.get() or 1.2)

        z_ramp = build_ramp(target_rows, res, (sz_x, sz_y), ramp_elev)
        z_tex = apply_texture(s, tex_type, (sz_x, sz_y), t_relief, polarity_inverted=pol_inv)
        Z = base_th + z_ramp + z_tex

        if self.flip_var.get():
            Z = np.flipud(Z)

        stl_path = out_dir / f"{stem}_Chroma_{tex_type}_{quality}.stl"
        surface_z_to_stl(Z, stl_path, physical_size_mm=(sz_x, sz_y))
        convert_stl(stl_path, fmts)

    def _on_generation_finished(self, count, total, out_dir):
        self.is_generating = False
        btn_txt = "Generate tactile files" if self.mode == "chroma" else "Generate print files"
        self.btn_generate.configure(state="normal", text=btn_txt)
        self.status_var.set(f"Finished: {count}/{total} files generated in {out_dir.name}")
        messagebox.showinfo("Generation Complete", f"Successfully generated tactile 3D models for {count} of {total} images!\nSaved to: {out_dir}")

    def _open_output_folder(self):
        folder = Path(self.output_dir_var.get().strip() or str(Path.home() / "TAMP_output"))
        folder.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(str(folder))
        elif sys.platform == "darwin":
            os.system(f"open '{folder}'")
        else:
            os.system(f"xdg-open '{folder}'")

    def _browse_output_dir(self):
        d = filedialog.askdirectory(title="Select Output Directory", initialdir=self.output_dir_var.get())
        if d:
            self.output_dir_var.set(d)
            self.cfg["output_dir"] = d
            save_settings(self.cfg)

    def _update_status_summary(self):
        count = len(self.images_data)
        fmts = [f for f, v in [(".STL", self.fmt_stl_var.get()), (".3MF", self.fmt_3mf_var.get()), (".GLB", self.fmt_glb_var.get())] if v]
        fmt_count = len(fmts) or 1
        est_tot_mb = sum(estimate_stl_file_size(
            {"Low": 128, "Medium": 256, "High": 512}.get(img["quality"], 256),
            img["height"] / max(1, img["width"])
        ) for img in self.images_data) if self.images_data else 0.0

        self.status_var.set(f"Ready · {count} image{'s' if count != 1 else ''} · {fmt_count} format{'s' if fmt_count != 1 else ''} · ≈ {format_file_size(est_tot_mb)} of STL")

    def _show_help(self):
        guide = (
            "TAMP-OS v2 Quick Guide\n\n"
            "1. Mode Switch:\n"
            "   - TAMP-OS: Translates grayscale microscopy images into tactile relief.\n"
            "   - TAMP-OS Chroma: Decodes scientific colormaps (Inferno, Viridis, Turbo, SVD)\n"
            "     into dual-scale tactile models (macroscopic ramp + micro-textures).\n\n"
            "2. Texture Library (Chroma):\n"
            "   - Dots: Point stippling lattice for granular feel.\n"
            "   - Stripes: 1D grooves for directional tactile flow.\n"
            "   - Grid: Orthogonal crosshatch for dense isotropic feel.\n"
            "   - Waves: Continuous sinusoidal undulations.\n"
            "   - Scales: Shingle scallop arches for asymmetric orientation.\n"
            "   - Honeycomb: Hexagonal cells for distinct cellular partitions.\n\n"
            "3. 3D Preview:\n"
            "   - Click 'Open 3D view' to interact with the full 3D surface mesh in PyVista.\n\n"
            "Full documentation and parameter matrix in README.md."
        )
        messagebox.showinfo("TAMP-OS v2 Help & Guide", guide)


# ==============================================================================
# SECTION 7: MAIN ENTRYPOINT
# ==============================================================================

def main():
    root = tk.Tk()
    # Set default app styling
    root.tk_setPalette(background="#F8FAFC", foreground="#0F172A",
                       activeBackground="#E2E8F0", activeForeground="#0F172A")
    app = TAMPGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()

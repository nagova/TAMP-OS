#!/usr/bin/env python3
"""
TAMP-OS v2: Tactile Microscopy & Scientific Image Printing
Standalone Desktop Application

Unified interface supporting both:
  1. TAMP-OS Mode: Grayscale heightmap lithographs from microscopy images.
  2. TAMP-OS Chroma Mode: Multi-color gradient and colormap tactile encoding
     with macroscopic ramp + micro-texture modulation.

Run:
  python tamp_os_gui.py
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
import customtkinter as ctk
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


def decode_colormap(img_pil, colormap_name="Inferno", return_fallback_status=False):
    """
    Fast RGB-to-scalar projection using scipy.spatial.cKDTree.
    Returns normalized scalar array [0, 1] of shape (H, W).
    If return_fallback_status=True, returns (scalar, fell_back_to_luminance).
    """
    if colormap_name == "Luminance":
        gray = img_pil.convert("L")
        res = np.array(gray, dtype=np.float32) / 255.0
        return (res, False) if return_fallback_status else res

    rgb = img_pil.convert("RGB")
    arr = np.array(rgb, dtype=np.float32) / 255.0
    h, w, _ = arr.shape

    # Check if image is grayscale (R ≈ G ≈ B)
    diff_rg = float(np.mean(np.abs(arr[:, :, 0] - arr[:, :, 1])))
    diff_rb = float(np.mean(np.abs(arr[:, :, 0] - arr[:, :, 2])))
    if diff_rg < 0.02 and diff_rb < 0.02:
        gray = img_pil.convert("L")
        res = np.array(gray, dtype=np.float32) / 255.0
        return (res, True) if return_fallback_status else res

    flat_rgb = arr.reshape(-1, 3)
    lut, tree = get_colormap_tree(colormap_name)
    dists, indices = tree.query(flat_rgb)
    mean_dist = float(np.mean(dists))

    # If mean distance to colormap is large, fall back to Luminance
    if mean_dist > 0.15:
        gray = img_pil.convert("L")
        res = np.array(gray, dtype=np.float32) / 255.0
        return (res, True) if return_fallback_status else res

    scalar = (indices / 255.0).reshape(h, w).astype(np.float32)
    return (scalar, False) if return_fallback_status else scalar


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
    try:
        w = int(canvas.cget("width"))
    except Exception:
        w = 44
    try:
        h = int(canvas.cget("height"))
    except Exception:
        h = 30

    fg = "#2563EB" if is_selected else "#64748B"
    bg = "#EFF6FF" if is_selected else "#FFFFFF"
    canvas.configure(bg=bg)

    if texture_name == "Dots":
        # 3 staggered rows centered in (44, 30)
        r_dot = 2.0
        for row in range(3):
            y = 6.0 + row * 9.0
            xs = [8.0, 17.0, 26.0, 35.0] if row % 2 == 0 else [12.5, 21.5, 30.5]
            for x in xs:
                canvas.create_oval(x - r_dot, y - r_dot, x + r_dot, y + r_dot, fill=fg, outline="")

    elif texture_name == "Stripes":
        for x in [11, 19, 27, 35]:
            canvas.create_line(x, 5, x, h - 5, fill=fg, width=2.2)

    elif texture_name == "Grid":
        for x in [12, 22, 32]:
            canvas.create_line(x, 5, x, h - 5, fill=fg, width=1.6)
        for y in [7, 15, 23]:
            canvas.create_line(6, y, w - 6, y, fill=fg, width=1.6)

    elif texture_name == "Waves":
        pts1, pts2 = [], []
        for xi in range(6, w - 5, 2):
            phase = (xi - 6) / max(1, (w - 12)) * 2 * math.pi
            pts1.extend([xi, 10 + int(4.0 * math.sin(phase))])
            pts2.extend([xi, 20 + int(4.0 * math.sin(phase))])
        if len(pts1) >= 4:
            canvas.create_line(*pts1, fill=fg, width=1.8, smooth=True)
            canvas.create_line(*pts2, fill=fg, width=1.8, smooth=True)

    elif texture_name == "Scales":
        # Scallop arches
        for x in [6, 17, 28]:
            canvas.create_arc(x, 12 - 5, x + 10, 12 + 5, start=0, extent=180,
                              style="arc", outline=fg, width=1.6)
        for x in [11.5, 22.5]:
            canvas.create_arc(x, 20 - 5, x + 10, 20 + 5, start=0, extent=180,
                              style="arc", outline=fg, width=1.6)

    elif texture_name == "Honeycomb":
        # Hexagonal rings
        def hex_pts(cx, cy, r):
            pts = []
            for i in range(6):
                ang = i * math.pi / 3.0
                pts.extend([cx + r * math.cos(ang), cy + r * math.sin(ang)])
            return pts

        canvas.create_polygon(hex_pts(15, 15, 7.0), outline=fg, fill="", width=1.6)
        canvas.create_polygon(hex_pts(29, 15, 7.0), outline=fg, fill="", width=1.6)



# ==============================================================================
# SECTION 6: USER INTERFACE (TAMP-OS v2 MODERN DESKTOP GUI)
# ==============================================================================

class TAMPGUI:
    def __init__(self, root=None):
        if root is None:
            ctk.set_appearance_mode("light")
            ctk.set_default_color_theme("blue")
            self.root = ctk.CTk()
        else:
            self.root = root

        self.root.title("TAMP-OS Lithograph Maker v2")
        self.root.geometry("1180x880")
        self.root.minsize(1020, 740)
        self.root.configure(fg_color="#F8FAFC")

        self.cfg = load_settings()
        self.mode = self.cfg.get("mode", "os")  # "os" or "chroma"

        self.images_data = []  # list of dicts: {"path", "name", "width", "height", "quality", "invert", "analysis"}
        self.selected_idx = 0
        self.is_generating = False
        self.thumbnail_cache = {}
        self.ctk_preview_img = None
        self.suggested_overall_preset = "Medium"

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

        # Chroma specific
        self.chroma_colormap_var = tk.StringVar(value=self.cfg.get("chroma_colormap", "Inferno"))
        self.chroma_ramp_var = tk.DoubleVar(value=float(self.cfg.get("chroma_ramp_elevation", 1.8)))
        self.chroma_texture_var = tk.StringVar(value=self.cfg.get("chroma_texture", "Honeycomb"))
        self.chroma_relief_var = tk.DoubleVar(value=float(self.cfg.get("chroma_texture_relief", 0.6)))
        self.chroma_polarity_var = tk.BooleanVar(value=self.cfg.get("chroma_polarity_inverted", False))

        self.advanced_open = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Ready.")

    def _build_layout(self):
        # 1. Top Header Bar
        header = ctk.CTkFrame(self.root, corner_radius=0, fg_color="#1E293B", height=62)
        header.pack(side="top", fill="x")
        header.pack_propagate(False)

        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.pack(side="left", padx=20, pady=8)
        ctk.CTkLabel(title_box, text="TAMP-OS Lithograph Maker", font=("Segoe UI", 16, "bold"),
                     text_color="#F8FAFC").pack(anchor="w")
        ctk.CTkLabel(title_box, text="Microscopy images to tactile 3D prints", font=("Segoe UI", 11),
                     text_color="#94A3B8").pack(anchor="w")

        header_right = ctk.CTkFrame(header, fg_color="transparent")
        header_right.pack(side="right", padx=20, pady=12)

        ctk.CTkButton(header_right, text="Help & guide", font=("Segoe UI", 11, "bold"),
                      fg_color="#334155", text_color="#F8FAFC", hover_color="#475569",
                      corner_radius=8, width=100, height=32, command=self._show_help).pack(side="right", padx=6)

        ctk.CTkLabel(header_right, text="v2.1", font=("Segoe UI", 11, "bold"),
                     text_color="#38BDF8").pack(side="right", padx=10)

        # Segmented Mode Switch [ TAMP-OS | TAMP-OS Chroma ]
        self.mode_seg = ctk.CTkSegmentedButton(
            header_right, values=["TAMP-OS", "TAMP-OS Chroma"],
            font=("Segoe UI", 11, "bold"), corner_radius=8,
            selected_color="#2563EB", selected_hover_color="#1D4ED8",
            unselected_color="#0F172A", unselected_hover_color="#1E293B",
            text_color="#FFFFFF", command=self._on_segmented_mode_changed
        )
        self.mode_seg.set("TAMP-OS" if self.mode == "os" else "TAMP-OS Chroma")
        self.mode_seg.pack(side="right", padx=14)

        # 2. Bottom Action Bar (packed with side='bottom' before main_content to reserve 60 px)
        bottom_bar = ctk.CTkFrame(self.root, corner_radius=12, fg_color="#FFFFFF", border_width=1, border_color="#E2E8F0", height=60)
        bottom_bar.pack(side="bottom", fill="x", padx=16, pady=(0, 12))
        bottom_bar.pack_propagate(False)

        self.status_label = ctk.CTkLabel(bottom_bar, textvariable=self.status_var,
                                         font=("Segoe UI", 11), text_color="#475569")
        self.status_label.pack(side="left", padx=18, pady=14)

        self.progress_bar = ctk.CTkProgressBar(bottom_bar, orientation="horizontal", width=220, mode="determinate",
                                               corner_radius=6, progress_color="#2563EB", fg_color="#E2E8F0")
        self.progress_bar.set(0)
        self.progress_bar.pack(side="left", padx=12, pady=18)

        self.btn_generate = ctk.CTkButton(
            bottom_bar, text="Generate print files", font=("Segoe UI", 12, "bold"),
            fg_color="#1D4ED8", hover_color="#1E40AF", text_color="#FFFFFF",
            corner_radius=8, width=170, height=36, command=self._start_generation
        )
        self.btn_generate.pack(side="right", padx=18, pady=12)

        ctk.CTkButton(
            bottom_bar, text="Open output folder", font=("Segoe UI", 11),
            fg_color="#FFFFFF", hover_color="#F8FAFC", text_color="#334155",
            border_width=1, border_color="#CBD5E1", corner_radius=8,
            width=140, height=36, command=self._open_output_folder
        ).pack(side="right", padx=6, pady=12)

        # 3. Main 2-Column Content Split
        main_content = ctk.CTkFrame(self.root, fg_color="transparent")
        main_content.pack(fill="both", expand=True, padx=16, pady=(10, 6))

        # Left Column (Images & Live Preview)
        self.left_col = ctk.CTkFrame(main_content, fg_color="transparent", width=560)
        self.left_col.pack(side="left", fill="both", expand=True, padx=(0, 8))

        # Right Column (Settings & Chroma parameters) - scrollable with smooth mousewheel
        self.r_scroll = ctk.CTkScrollableFrame(
            main_content, corner_radius=12, fg_color="transparent", width=560
        )
        self.r_scroll.pack(side="right", fill="both", expand=True, padx=(8, 0))

        # Build column internals
        self._build_left_column()
        self._build_right_column()

    # --------------------------------------------------------------------------
    # LEFT COLUMN: IMAGES & PREVIEW
    # --------------------------------------------------------------------------
    def _build_left_column(self):
        f = self.left_col

        # Card 1: Images
        self.card_images = ctk.CTkFrame(f, corner_radius=12, fg_color="#FFFFFF", border_width=1, border_color="#E2E8F0")
        self.card_images.pack(fill="x", pady=(0, 10))

        c1_hdr = ctk.CTkFrame(self.card_images, fg_color="transparent")
        c1_hdr.pack(fill="x", padx=16, pady=(12, 4))

        ctk.CTkLabel(c1_hdr, text="1. Images", font=("Segoe UI", 14, "bold"),
                     text_color="#0F172A").pack(side="left")
        self.lbl_img_count = ctk.CTkLabel(c1_hdr, text="0 images", font=("Segoe UI", 11),
                                          text_color="#64748B")
        self.lbl_img_count.pack(side="left", padx=10)

        ctk.CTkButton(c1_hdr, text="Clear", font=("Segoe UI", 11),
                      fg_color="transparent", text_color="#94A3B8", hover_color="#F1F5F9",
                      width=48, height=24, corner_radius=6,
                      command=self._clear_images).pack(side="right")

        # Dropzone / Add button box
        dz = ctk.CTkFrame(self.card_images, corner_radius=8, fg_color="#F8FAFC", border_width=1, border_color="#CBD5E1")
        dz.pack(fill="x", padx=16, pady=4)

        dz_content = ctk.CTkFrame(dz, fg_color="transparent")
        dz_content.pack(pady=8)
        ctk.CTkLabel(dz_content, text="↑  Drop images here or", font=("Segoe UI", 11),
                     text_color="#64748B").pack(side="left", padx=(0, 8))
        ctk.CTkButton(dz_content, text="Add images…", font=("Segoe UI", 11, "bold"),
                      fg_color="#FFFFFF", text_color="#2563EB", hover_color="#EFF6FF",
                      border_width=1, border_color="#2563EB", corner_radius=6,
                      width=96, height=28, command=self._add_images_dialog).pack(side="left")

        # Table header row
        th = ctk.CTkFrame(self.card_images, fg_color="transparent")
        th.pack(fill="x", padx=20, pady=(6, 2))
        th.columnconfigure(0, weight=1)
        th.columnconfigure(1, minsize=96)
        th.columnconfigure(2, minsize=80)
        th.columnconfigure(3, minsize=32)

        ctk.CTkLabel(th, text="Image", font=("Segoe UI", 11, "bold"), text_color="#64748B", anchor="w").grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(th, text="Quality", font=("Segoe UI", 11, "bold"), text_color="#64748B").grid(row=0, column=1)
        self.th_invert_lbl = ctk.CTkLabel(th, text="Invert", font=("Segoe UI", 11, "bold"), text_color="#64748B")
        self.th_invert_lbl.grid(row=0, column=2)
        ctk.CTkLabel(th, text="").grid(row=0, column=3)

        # Image list items container
        self.tbl_items_frame = ctk.CTkScrollableFrame(self.card_images, corner_radius=8, fg_color="transparent", height=130)
        self.tbl_items_frame.pack(fill="both", expand=True, padx=14, pady=(2, 12))

        # Card 2: Relief Preview
        self.card_preview = ctk.CTkFrame(f, corner_radius=12, fg_color="#FFFFFF", border_width=1, border_color="#E2E8F0")
        self.card_preview.pack(fill="both", expand=True, pady=(0, 6))

        p_hdr = ctk.CTkFrame(self.card_preview, fg_color="transparent")
        p_hdr.pack(fill="x", padx=16, pady=(12, 6))
        self.lbl_preview_title = ctk.CTkLabel(p_hdr, text="Relief preview", font=("Segoe UI", 14, "bold"),
                                              text_color="#0F172A")
        self.lbl_preview_title.pack(side="left")

        self.lbl_preview_fname = ctk.CTkLabel(p_hdr, text="", font=("Segoe UI", 11),
                                              text_color="#64748B")
        self.lbl_preview_fname.pack(side="left", padx=10)

        ctk.CTkButton(p_hdr, text="Open 3D view", font=("Segoe UI", 11, "bold"),
                      fg_color="#F0FDF4", text_color="#16A34A", hover_color="#DCFCE7",
                      border_width=1, border_color="#BBF7D0", corner_radius=6,
                      width=110, height=28, command=self._launch_pyvista_3d).pack(side="right")

        # Preview content body: 2-column layout (Image on left, Meta specs on right)
        prev_body = ctk.CTkFrame(self.card_preview, fg_color="transparent")
        prev_body.pack(fill="both", expand=True, padx=16, pady=4)

        # Left side: Preview display
        self.prev_img_box = ctk.CTkFrame(prev_body, corner_radius=8, fg_color="#0F172A", width=280, height=210)
        self.prev_img_box.pack(side="left", padx=(0, 14), fill="both", expand=True)
        self.prev_img_box.pack_propagate(False)

        self.lbl_preview_image = ctk.CTkLabel(self.prev_img_box, text="No preview available",
                                              text_color="#94A3B8")
        self.lbl_preview_image.pack(fill="both", expand=True)

        # Right side: Meta Specs Grid
        self.meta_frame = ctk.CTkFrame(prev_body, fg_color="transparent", width=200)
        self.meta_frame.pack(side="right", fill="y", anchor="n", pady=6)

        specs = [
            ("Raised areas", "Light areas", "lbl_meta_raised"),
            ("Print size", "100 × 75 mm", "lbl_meta_size"),
            ("Resolution", "128 px", "lbl_meta_res"),
            ("Est. STL", "~2.3 MB", "lbl_meta_stl"),
        ]
        for key, default_val, attr_name in specs:
            row = ctk.CTkFrame(self.meta_frame, fg_color="transparent")
            row.pack(fill="x", pady=4)
            ctk.CTkLabel(row, text=key + ":", font=("Segoe UI", 11),
                         text_color="#64748B", width=85, anchor="w").pack(side="left")
            val_lbl = ctk.CTkLabel(row, text=default_val, font=("Segoe UI", 11, "bold"),
                                   text_color="#0F172A", anchor="w")
            val_lbl.pack(side="left", padx=4)
            setattr(self, attr_name, val_lbl)

        # Cross section plot container (visible in Chroma mode)
        self.plot_container = ctk.CTkFrame(self.card_preview, fg_color="transparent", height=100)
        self.plot_canvas = None

        # Helper hint text
        self.lbl_colormap_fallback = ctk.CTkLabel(
            self.card_preview, text="",
            font=("Segoe UI", 10, "bold"), text_color="#D97706", anchor="w"
        )

        self.lbl_preview_hint = ctk.CTkLabel(
            self.card_preview,
            text="Light = raised, dark = low. Check this before generating: if the feature you want to feel is sunk, tick Invert.",
            font=("Segoe UI", 10), text_color="#64748B", wraplength=500, justify="left"
        )
        self.lbl_preview_hint.pack(fill="x", padx=16, pady=(4, 12))

    # --------------------------------------------------------------------------
    # RIGHT COLUMN: CHROMA CONTROLS + SHARED SETTINGS
    # --------------------------------------------------------------------------
    def _build_right_column(self):
        rf = self.r_scroll

        # -------------------- CHROMA CONTAINER (TOP OF RIGHT COL) --------------------
        self.card_chroma = ctk.CTkFrame(rf, corner_radius=12, fg_color="#FFFFFF", border_width=1, border_color="#E2E8F0")
        # Do not pack card_chroma initially; _update_mode_ui() packs it if mode == "chroma"

        ch_hdr = ctk.CTkFrame(self.card_chroma, fg_color="transparent")
        ch_hdr.pack(fill="x", padx=16, pady=(12, 4))
        ctk.CTkLabel(ch_hdr, text="Chroma · colormap & texture", font=("Segoe UI", 14, "bold"),
                     text_color="#0F172A").pack(anchor="w")
        ctk.CTkLabel(ch_hdr, text="Color value → ramp height + texture", font=("Segoe UI", 11),
                     text_color="#64748B").pack(anchor="w")

        # Colormap row
        cm_row = ctk.CTkFrame(self.card_chroma, fg_color="transparent")
        cm_row.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(cm_row, text="Colormap:", font=("Segoe UI", 11, "bold"),
                     text_color="#334155").pack(side="left")

        self.cm_combo = ctk.CTkComboBox(
            cm_row, values=SUPPORTED_COLORMAPS, state="readonly", width=140, height=28,
            corner_radius=6, fg_color="#FFFFFF", border_width=1, border_color="#CBD5E1",
            button_color="#F1F5F9", button_hover_color="#E2E8F0", text_color="#0F172A",
            dropdown_fg_color="#FFFFFF", dropdown_text_color="#0F172A", dropdown_hover_color="#EFF6FF",
            command=self._on_colormap_changed
        )
        self.cm_combo.set(self.chroma_colormap_var.get())
        self.cm_combo.pack(side="left", padx=8)

        # Gradient Canvas preview bar
        self.cmap_canvas = tk.Canvas(cm_row, width=140, height=18, bd=1, relief="solid", highlightthickness=0)
        self.cmap_canvas.pack(side="left", padx=4)

        # Ramp elevation slider
        ramp_row = ctk.CTkFrame(self.card_chroma, fg_color="transparent")
        ramp_row.pack(fill="x", padx=16, pady=(6, 2))
        ctk.CTkLabel(ramp_row, text="Ramp elevation (mm):", font=("Segoe UI", 11, "bold"),
                     text_color="#334155").pack(side="left")
        self.lbl_ramp_val = ctk.CTkLabel(ramp_row, text=f"{self.chroma_ramp_var.get():.1f} mm",
                                         font=("Segoe UI", 11, "bold"), text_color="#2563EB")
        self.lbl_ramp_val.pack(side="right")

        s_ramp = ctk.CTkSlider(self.card_chroma, from_=0.5, to=4.0, variable=self.chroma_ramp_var,
                               progress_color="#2563EB", button_color="#2563EB", button_hover_color="#1D4ED8",
                               command=self._on_ramp_slider_move)
        s_ramp.pack(fill="x", padx=16, pady=2)
        s_ramp.bind("<ButtonRelease-1>", lambda e: self._update_preview())
        ctk.CTkLabel(self.card_chroma, text="Macroscopic slope on top of the 1.2 mm solid base",
                     font=("Segoe UI", 9), text_color="#64748B").pack(anchor="w", padx=16, pady=(0, 6))

        # Texture Library grid
        ctk.CTkLabel(self.card_chroma, text="Texture library", font=("Segoe UI", 11, "bold"),
                     text_color="#334155").pack(anchor="w", padx=16, pady=(4, 2))

        self.tex_grid = ctk.CTkFrame(self.card_chroma, fg_color="transparent")
        self.tex_grid.pack(fill="x", padx=16, pady=2)
        self.tex_buttons = {}
        textures = ["Dots", "Stripes", "Grid", "Waves", "Scales", "Honeycomb"]
        for i, tex in enumerate(textures):
            card = ctk.CTkFrame(self.tex_grid, corner_radius=8, fg_color="#FFFFFF", border_width=1, border_color="#E2E8F0", cursor="hand2")
            card.grid(row=0, column=i, padx=3, pady=2, sticky="nsew")
            self.tex_grid.columnconfigure(i, weight=1)

            cv = tk.Canvas(card, width=44, height=30, bd=0, highlightthickness=0, bg="#FFFFFF")
            cv.pack(padx=2, pady=2)

            lbl = ctk.CTkLabel(card, text=tex, font=("Segoe UI", 9, "bold"), text_color="#334155")
            lbl.pack(pady=(0, 3))

            def make_handler(t=tex):
                return lambda e: self._select_texture(t)

            card.bind("<Button-1>", make_handler())
            cv.bind("<Button-1>", make_handler())
            lbl.bind("<Button-1>", make_handler())

            self.tex_buttons[tex] = {"frame": card, "canvas": cv, "label": lbl}

        # Texture relief slider
        t_relief_row = ctk.CTkFrame(self.card_chroma, fg_color="transparent")
        t_relief_row.pack(fill="x", padx=16, pady=(6, 2))
        ctk.CTkLabel(t_relief_row, text="Texture relief (mm):", font=("Segoe UI", 11, "bold"),
                     text_color="#334155").pack(side="left")
        self.lbl_t_relief_val = ctk.CTkLabel(t_relief_row, text=f"{self.chroma_relief_var.get():.2f} mm",
                                             font=("Segoe UI", 11, "bold"), text_color="#2563EB")
        self.lbl_t_relief_val.pack(side="right")

        s_t_relief = ctk.CTkSlider(self.card_chroma, from_=0.2, to=1.5, variable=self.chroma_relief_var,
                                   progress_color="#2563EB", button_color="#2563EB", button_hover_color="#1D4ED8",
                                   command=self._on_texture_relief_slider_move)
        s_t_relief.pack(fill="x", padx=16, pady=2)
        s_t_relief.bind("<ButtonRelease-1>", lambda e: self._update_preview())
        ctk.CTkLabel(self.card_chroma, text="Height of the micro-texture (0.2–1.5 mm)",
                     font=("Segoe UI", 9), text_color="#64748B").pack(anchor="w", padx=16, pady=(0, 10))

        self._refresh_texture_buttons()
        self._redraw_colormap_bar()

        # -------------------- SHARED: 2. PRINTER --------------------
        self.card_printer = ctk.CTkFrame(rf, corner_radius=12, fg_color="#FFFFFF", border_width=1, border_color="#E2E8F0")
        self.card_printer.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(self.card_printer, text="2. Printer", font=("Segoe UI", 14, "bold"),
                     text_color="#0F172A").pack(anchor="w", padx=16, pady=(12, 4))
        ctk.CTkLabel(self.card_printer, text="Printer preset", font=("Segoe UI", 11),
                     text_color="#64748B").pack(anchor="w", padx=16, pady=(0, 2))

        self.pr_menu = ctk.CTkComboBox(
            self.card_printer, values=[
                "Standard FDM · 0.4 mm nozzle",
                "Fine-detail FDM · 0.2 mm nozzle",
                "Large-nozzle FDM · 0.6 mm nozzle",
                "Custom"
            ], state="readonly", corner_radius=8, height=32,
            fg_color="#FFFFFF", border_width=1, border_color="#CBD5E1",
            button_color="#F1F5F9", button_hover_color="#E2E8F0",
            text_color="#0F172A", dropdown_fg_color="#FFFFFF",
            dropdown_text_color="#0F172A", dropdown_hover_color="#EFF6FF",
            command=self._on_printer_profile_changed
        )
        self.pr_menu.set(self.printer_profile_var.get())
        self.pr_menu.pack(fill="x", padx=16, pady=4)

        # Chips row
        self.chips_frame = ctk.CTkFrame(self.card_printer, fg_color="transparent")
        self.chips_frame.pack(fill="x", padx=16, pady=(6, 14))
        self.lbl_chip_nozzle = ctk.CTkLabel(self.chips_frame, text="0.4 mm nozzle", corner_radius=10, fg_color="#F1F5F9", text_color="#475569", font=("Segoe UI", 10), padx=8, pady=3)
        self.lbl_chip_nozzle.pack(side="left", padx=(0, 6))
        self.lbl_chip_layer = ctk.CTkLabel(self.chips_frame, text="0.12 mm layers", corner_radius=10, fg_color="#F1F5F9", text_color="#475569", font=("Segoe UI", 10), padx=6)
        self.lbl_chip_layer.pack(side="left", padx=6)
        self.lbl_chip_size = ctk.CTkLabel(self.chips_frame, text="100 mm wide", corner_radius=10, fg_color="#F1F5F9", text_color="#475569", font=("Segoe UI", 10), padx=6)
        self.lbl_chip_size.pack(side="left", padx=6)

        # -------------------- SHARED: 3. QUALITY --------------------
        self.card_quality = ctk.CTkFrame(rf, corner_radius=12, fg_color="#FFFFFF", border_width=1, border_color="#E2E8F0")
        self.card_quality.pack(fill="x", pady=(0, 10))

        q_hdr = ctk.CTkFrame(self.card_quality, fg_color="transparent")
        q_hdr.pack(fill="x", padx=16, pady=(12, 6))
        ctk.CTkLabel(q_hdr, text="3. Quality", font=("Segoe UI", 14, "bold"),
                     text_color="#0F172A").pack(side="left")
        self.lbl_quality_subtitle = ctk.CTkLabel(q_hdr, text="Click a card to apply it to all images", font=("Segoe UI", 11),
                                                 text_color="#64748B")
        self.lbl_quality_subtitle.pack(side="right")

        # 3 Side by side cards
        q_cards_frame = ctk.CTkFrame(self.card_quality, fg_color="transparent")
        q_cards_frame.pack(fill="x", padx=14, pady=4)
        q_cards_frame.columnconfigure(0, weight=1)
        q_cards_frame.columnconfigure(1, weight=1)
        q_cards_frame.columnconfigure(2, weight=1)

        self.q_cards = {}
        q_specs = [
            ("Low", "Quick draft", "~2.3 MB STL · 128 px"),
            ("Medium", "Balanced detail", "~9.4 MB STL · 256 px"),
            ("High", "Maximum detail", "~37.5 MB STL · 512 px")
        ]
        for col_idx, (name, subtitle, details) in enumerate(q_specs):
            card = ctk.CTkFrame(q_cards_frame, corner_radius=10, fg_color="#F8FAFC", border_width=1.5, border_color="#E2E8F0", cursor="hand2")
            card.grid(row=0, column=col_idx, padx=4, pady=2, sticky="nsew")

            top_r = ctk.CTkFrame(card, fg_color="transparent")
            top_r.pack(fill="x", padx=10, pady=(8, 2))
            t_lbl = ctk.CTkLabel(top_r, text=name, font=("Segoe UI", 13, "bold"), text_color="#0F172A")
            t_lbl.pack(side="left")

            sug_badge = ctk.CTkLabel(top_r, text="Suggested", font=("Segoe UI", 9, "bold"),
                                     fg_color="#0F172A", text_color="#FFFFFF", corner_radius=6, padx=6, pady=1)

            s_lbl = ctk.CTkLabel(card, text=subtitle, font=("Segoe UI", 10), text_color="#475569")
            s_lbl.pack(anchor="w", padx=10, pady=1)
            d_lbl = ctk.CTkLabel(card, text=details, font=("Segoe UI", 9), text_color="#64748B")
            d_lbl.pack(anchor="w", padx=10, pady=(1, 8))

            def make_handler(q_name=name):
                return lambda e: self._select_quality_card(q_name)

            card.bind("<Button-1>", make_handler())
            t_lbl.bind("<Button-1>", make_handler())
            s_lbl.bind("<Button-1>", make_handler())
            d_lbl.bind("<Button-1>", make_handler())
            self.q_cards[name] = {"frame": card, "title": t_lbl, "badge": sug_badge}

        # Suggestion Banner
        self.sug_banner = ctk.CTkFrame(self.card_quality, corner_radius=8, fg_color="#EFF6FF", border_width=1, border_color="#BFDBFE")
        self.sug_banner.pack(fill="x", padx=16, pady=(6, 14))

        self.lbl_suggestion = ctk.CTkLabel(self.sug_banner, text="Add images to see resolution guidance.",
                                           font=("Segoe UI", 11), text_color="#1E40AF", justify="left")
        self.lbl_suggestion.pack(side="left", padx=12, pady=8)

        self.btn_use_suggestion = ctk.CTkButton(
            self.sug_banner, text="Use suggestion", font=("Segoe UI", 11, "bold"),
            fg_color="#FFFFFF", text_color="#2563EB", hover_color="#DBEAFE",
            border_width=1, border_color="#2563EB", corner_radius=6,
            width=110, height=26, command=self._apply_suggested_preset
        )
        self.btn_use_suggestion.pack(side="right", padx=12, pady=8)

        # -------------------- SHARED: 4. OUTPUT --------------------
        self.card_output = ctk.CTkFrame(rf, corner_radius=12, fg_color="#FFFFFF", border_width=1, border_color="#E2E8F0")
        self.card_output.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(self.card_output, text="4. Output", font=("Segoe UI", 14, "bold"),
                     text_color="#0F172A").pack(anchor="w", padx=16, pady=(12, 4))

        ctk.CTkLabel(self.card_output, text="Save to folder", font=("Segoe UI", 11),
                     text_color="#64748B").pack(anchor="w", padx=16, pady=(0, 2))

        out_row = ctk.CTkFrame(self.card_output, fg_color="transparent")
        out_row.pack(fill="x", padx=16, pady=4)
        self.ent_output = ctk.CTkEntry(out_row, textvariable=self.output_dir_var, corner_radius=8, height=32,
                                       border_color="#CBD5E1", fg_color="#FFFFFF", text_color="#0F172A", font=("Segoe UI", 11))
        self.ent_output.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(out_row, text="Browse…", font=("Segoe UI", 11),
                      fg_color="#FFFFFF", text_color="#334155", hover_color="#F1F5F9",
                      border_width=1, border_color="#CBD5E1", corner_radius=8,
                      width=80, height=32, command=self._browse_output_dir).pack(side="right")

        ctk.CTkLabel(self.card_output, text="File formats", font=("Segoe UI", 11),
                     text_color="#64748B").pack(anchor="w", padx=16, pady=(6, 2))

        fmt_row = ctk.CTkFrame(self.card_output, fg_color="transparent")
        fmt_row.pack(fill="x", padx=16, pady=(2, 14))
        ctk.CTkCheckBox(fmt_row, text=".STL", variable=self.fmt_stl_var, corner_radius=4,
                        fg_color="#2563EB", text_color="#0F172A", font=("Segoe UI", 11, "bold")).pack(side="left", padx=(0, 14))
        ctk.CTkCheckBox(fmt_row, text=".3MF", variable=self.fmt_3mf_var, corner_radius=4,
                        fg_color="#2563EB", text_color="#0F172A", font=("Segoe UI", 11)).pack(side="left", padx=14)
        ctk.CTkCheckBox(fmt_row, text=".GLB", variable=self.fmt_glb_var, corner_radius=4,
                        fg_color="#2563EB", text_color="#0F172A", font=("Segoe UI", 11)).pack(side="left", padx=14)

        # -------------------- ADVANCED SETTINGS (COLLAPSIBLE) --------------------
        self.card_advanced = ctk.CTkFrame(rf, corner_radius=12, fg_color="#FFFFFF", border_width=1, border_color="#E2E8F0")
        self.card_advanced.pack(fill="x", pady=(0, 14))

        adv_hdr = ctk.CTkFrame(self.card_advanced, fg_color="transparent", cursor="hand2")
        adv_hdr.pack(fill="x", padx=16, pady=12)

        self.btn_adv_toggle = ctk.CTkButton(
            adv_hdr, text="▶  Advanced settings", font=("Segoe UI", 12, "bold"),
            fg_color="transparent", text_color="#0F172A", hover_color="#F8FAFC",
            anchor="w", command=self._toggle_advanced
        )
        self.btn_adv_toggle.pack(side="left")
        ctk.CTkLabel(adv_hdr, text="Print size, nozzle, layers, relief, blur, base",
                     font=("Segoe UI", 10), text_color="#64748B").pack(side="right")

        self.adv_content = ctk.CTkFrame(self.card_advanced, fg_color="transparent")
        self._build_advanced_controls()

    def _build_advanced_controls(self):
        af = self.adv_content
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
        for label_txt, var, hint in params:
            r = ctk.CTkFrame(af, fg_color="transparent")
            r.pack(fill="x", padx=16, pady=3)
            ctk.CTkLabel(r, text=label_txt + ":", font=("Segoe UI", 10), text_color="#334155", width=160, anchor="w").pack(side="left")
            ctk.CTkEntry(r, textvariable=var, font=("Segoe UI", 10), width=80, height=28, corner_radius=6).pack(side="left", padx=6)
            ctk.CTkLabel(r, text=hint, font=("Segoe UI", 9), text_color="#475569").pack(side="left", padx=6)

        fl_row = ctk.CTkFrame(af, fg_color="transparent")
        fl_row.pack(fill="x", padx=16, pady=(6, 12))
        ctk.CTkCheckBox(fl_row, text="Flip vertically for printing (matches image orientation)",
                        variable=self.flip_var, corner_radius=4, fg_color="#2563EB",
                        text_color="#334155", font=("Segoe UI", 10)).pack(anchor="w")

    def _toggle_advanced(self):
        if self.advanced_open.get():
            self.adv_content.pack_forget()
            self.advanced_open.set(False)
            self.btn_adv_toggle.configure(text="▶  Advanced settings")
        else:
            self.adv_content.pack(fill="x", padx=0, pady=(0, 8))
            self.advanced_open.set(True)
            self.btn_adv_toggle.configure(text="▼  Advanced settings")

    # --------------------------------------------------------------------------
    # MODE SWITCHING & UI ADAPTATION
    # --------------------------------------------------------------------------
    def _on_segmented_mode_changed(self, value):
        mode = "chroma" if "chroma" in value.lower() else "os"
        self._set_mode(mode)

    def _set_mode(self, mode):
        self.mode = mode
        self.cfg["mode"] = mode
        save_settings(self.cfg)
        self.mode_seg.set("TAMP-OS Chroma" if mode == "chroma" else "TAMP-OS")
        self._update_mode_ui()
        self._refresh_image_table()
        self._update_preview()

    def _update_mode_ui(self):
        if self.mode == "os":
            self.card_chroma.pack_forget()
            if hasattr(self, "lbl_colormap_fallback"):
                self.lbl_colormap_fallback.pack_forget()
            self.th_invert_lbl.configure(text="Invert")
            self.lbl_preview_title.configure(text="Relief preview")
            self.lbl_preview_hint.configure(text="Light = raised, dark = low. Check this before generating: if the feature you want to feel is sunk, tick Invert.")
            self.btn_generate.configure(text="Generate print files")
            self.plot_container.pack_forget()
        else:
            self.card_chroma.pack(fill="x", pady=(0, 10), before=self.card_printer)
            self.th_invert_lbl.configure(text="Polarity")
            self.lbl_preview_title.configure(text="Live tactile preview")
            self.lbl_preview_hint.configure(text=f"Shaded relief with {self.chroma_texture_var.get()} texture. Grazing light shows how it will feel under the finger.")
            self.btn_generate.configure(text="Generate tactile files")
            self.plot_container.pack(fill="x", padx=16, pady=(4, 6), before=self.lbl_preview_hint)

        if hasattr(self, "r_scroll") and hasattr(self.r_scroll, "_parent_canvas"):
            self.r_scroll._parent_canvas.yview_moveto(0.0)

        self._refresh_texture_buttons()
        self._update_status_summary()

    # --------------------------------------------------------------------------
    # COLORMAP & TEXTURE SELECTION
    # --------------------------------------------------------------------------
    def _on_colormap_changed(self, choice=None):
        if choice:
            self.chroma_colormap_var.set(choice)
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
            border_c = "#2563EB" if is_sel else "#E2E8F0"
            bg_c = "#EFF6FF" if is_sel else "#FFFFFF"
            fg_c = "#2563EB" if is_sel else "#334155"
            widgets["frame"].configure(fg_color=bg_c, border_color=border_c, border_width=1.5 if is_sel else 1)
            widgets["label"].configure(text_color=fg_c)
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

    def _apply_suggested_preset(self):
        if self.suggested_overall_preset:
            self._select_quality_card(self.suggested_overall_preset)

    def _on_printer_profile_changed(self, choice=None):
        p = choice or self.pr_menu.get()
        self.printer_profile_var.set(p)
        self.cfg["printer_profile"] = p
        save_settings(self.cfg)

        if "0.2 mm" in p:
            self.nozzle_var.set("0.2")
            self.layer_var.set("0.08")
            self.size_x_var.set("80")
            self.lbl_chip_nozzle.configure(text="0.2 mm nozzle")
            self.lbl_chip_layer.configure(text="0.08 mm layers")
            self.lbl_chip_size.configure(text="80 mm wide")
        elif "0.6 mm" in p:
            self.nozzle_var.set("0.6")
            self.layer_var.set("0.20")
            self.size_x_var.set("150")
            self.lbl_chip_nozzle.configure(text="0.6 mm nozzle")
            self.lbl_chip_layer.configure(text="0.20 mm layers")
            self.lbl_chip_size.configure(text="150 mm wide")
        elif "Standard" in p or "0.4 mm" in p:
            self.nozzle_var.set("0.4")
            self.layer_var.set("0.12")
            self.size_x_var.set("100")
            self.lbl_chip_nozzle.configure(text="0.4 mm nozzle")
            self.lbl_chip_layer.configure(text="0.12 mm layers")
            self.lbl_chip_size.configure(text="100 mm wide")

        self._update_preview()
        self._update_status_summary()

    # --------------------------------------------------------------------------
    # IMAGE MANAGEMENT
    # --------------------------------------------------------------------------
    def _add_images_dialog(self):
        filetypes = [
            ("Image files", "*.png *.jpg *.jpeg *.tif *.tiff *.bmp"),
            ("All files", "*.*")
        ]
        paths = filedialog.askopenfilenames(title="Select microscopy / scientific images", filetypes=filetypes)
        if paths:
            self._add_image_paths(paths)

    def _load_default_examples_if_available(self):
        base_dir = Path(__file__).resolve().parent
        candidates = [
            base_dir / "examples" / "SEM_5um_raw.png",
            base_dir / "examples" / "crab_spider.jpg",
            base_dir / "examples" / "input_li_gradient.png"
        ]
        found = [str(p) for p in candidates if p.exists()]
        if found:
            self._add_image_paths(found, select_first=True)

    def _add_image_paths(self, paths, select_first=False):
        added_any = False
        for p in paths:
            if any(img["path"] == p for img in self.images_data):
                continue
            if Path(p).exists():
                try:
                    analysis = analyze_image_quality(p)
                    suggested = recommend_preset_from_analysis(analysis)
                    self.images_data.append({
                        "path": p,
                        "name": Path(p).name,
                        "width": analysis["width"],
                        "height": analysis["height"],
                        "quality": suggested,
                        "invert": bool(self.cfg.get("chroma_polarity_inverted", False)) if self.mode == "chroma" else False,
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
        self.images_data.clear()
        self.selected_idx = 0
        self._refresh_image_table()
        self._update_preview()
        self._update_status_summary()

    def _remove_single_image(self, idx):
        if 0 <= idx < len(self.images_data):
            del self.images_data[idx]
            if not self.images_data:
                self.selected_idx = 0
            elif self.selected_idx >= len(self.images_data):
                self.selected_idx = len(self.images_data) - 1
            elif self.selected_idx == idx:
                self.selected_idx = max(0, min(idx, len(self.images_data) - 1))
            elif self.selected_idx > idx:
                self.selected_idx -= 1
            self._refresh_image_table()
            self._update_preview()
            self._update_status_summary()

    def _refresh_image_table(self):
        for w in self.tbl_items_frame.winfo_children():
            w.destroy()

        count = len(self.images_data)
        self.lbl_img_count.configure(text=f"{count} image{'s' if count != 1 else ''}")

        if not self.images_data:
            empty_lbl = ctk.CTkLabel(self.tbl_items_frame, text="No images loaded. Click 'Add images…' to get started.",
                                     font=("Segoe UI", 11), text_color="#94A3B8")
            empty_lbl.pack(pady=20)
            return

        for idx, img in enumerate(self.images_data):
            is_sel = (idx == self.selected_idx)
            card_bg = "#EFF6FF" if is_sel else "#FFFFFF"
            card_border = "#93C5FD" if is_sel else "#E2E8F0"
            border_w = 1.5 if is_sel else 1

            row_card = ctk.CTkFrame(self.tbl_items_frame, corner_radius=8, fg_color=card_bg,
                                    border_width=border_w, border_color=card_border, height=52)
            row_card.pack(fill="x", pady=2, padx=2)

            def make_row_click(i=idx):
                def handler(e=None):
                    self.selected_idx = i
                    self._refresh_image_table()
                    self._update_preview()
                return handler

            # Thumbnail
            if img["path"] not in self.thumbnail_cache:
                try:
                    p_img = Image.open(img["path"]).convert("RGB")
                    p_img.thumbnail((36, 36))
                    self.thumbnail_cache[img["path"]] = ctk.CTkImage(light_image=p_img, dark_image=p_img, size=(36, 36))
                except Exception:
                    self.thumbnail_cache[img["path"]] = None

            thumb = self.thumbnail_cache.get(img["path"])
            if thumb:
                t_lbl = ctk.CTkLabel(row_card, text="", image=thumb, width=36, height=36, fg_color=card_bg)
                t_lbl.pack(side="left", padx=(8, 6), pady=6)
                t_lbl.bind("<Button-1>", make_row_click(idx))

            # Text Block
            txt_box = ctk.CTkFrame(row_card, fg_color=card_bg)
            txt_box.pack(side="left", fill="both", expand=True, padx=4)
            txt_box.bind("<Button-1>", make_row_click(idx))

            n_lbl = ctk.CTkLabel(txt_box, text=img["name"], font=("Segoe UI", 11, "bold"), text_color="#0F172A", anchor="w", fg_color=card_bg)
            n_lbl.pack(anchor="w", pady=(4, 0))
            n_lbl.bind("<Button-1>", make_row_click(idx))

            rec_preset = recommend_preset_from_analysis(img["analysis"])
            sub_txt = f"{img['width']} × {img['height']} px · suggested {rec_preset}"
            s_lbl = ctk.CTkLabel(txt_box, text=sub_txt, font=("Segoe UI", 9), text_color="#64748B", anchor="w", fg_color=card_bg)
            s_lbl.pack(anchor="w", pady=(0, 4))
            s_lbl.bind("<Button-1>", make_row_click(idx))

            # Quality Combobox
            def make_q_change(i=idx):
                def handler(choice):
                    self.images_data[i]["quality"] = choice
                    self._update_preview()
                    self._update_status_summary()
                    self._update_recommendation_banner()
                return handler

            q_cb = ctk.CTkComboBox(row_card, values=["Low", "Medium", "High"], state="readonly", width=82, height=26, corner_radius=6,
                                   fg_color="#FFFFFF", border_width=1, border_color="#CBD5E1", button_color="#F1F5F9",
                                   button_hover_color="#E2E8F0", text_color="#0F172A", font=("Segoe UI", 11),
                                   dropdown_fg_color="#FFFFFF", dropdown_text_color="#0F172A", dropdown_hover_color="#EFF6FF",
                                   command=make_q_change(idx))
            q_cb.set(img["quality"])
            q_cb.pack(side="left", padx=6)

            # Invert / Polarity Checkbox
            inv_var = tk.BooleanVar(value=img["invert"])
            inv_txt = ("Inverted" if img["invert"] else "Normal") if self.mode == "chroma" else ("On" if img["invert"] else "Off")

            def make_inv_toggle(i=idx, v=inv_var):
                def handler():
                    self.images_data[i]["invert"] = v.get()
                    self._update_preview()
                return handler

            inv_chk = ctk.CTkCheckBox(row_card, text=inv_txt, variable=inv_var, width=20, height=20, checkbox_width=18, checkbox_height=18,
                                      corner_radius=4, fg_color="#2563EB", text_color="#0F172A", font=("Segoe UI", 11),
                                      command=make_inv_toggle(idx, inv_var))
            inv_chk.pack(side="left", padx=8)

            # Delete button (✕)
            del_btn = ctk.CTkButton(row_card, text="✕", width=24, height=24, corner_radius=12,
                                    fg_color="transparent", text_color="#94A3B8", hover_color="#FEE2E2",
                                    font=("Segoe UI", 11, "bold"),
                                    command=lambda i=idx: self._remove_single_image(i))
            del_btn.pack(side="right", padx=(4, 8))

            row_card.bind("<Button-1>", make_row_click(idx))

        self._update_recommendation_banner()

    def _update_recommendation_banner(self):
        if not self.images_data:
            self.lbl_suggestion.configure(text="Add images to see resolution guidance.")
            if hasattr(self, "lbl_quality_subtitle"):
                self.lbl_quality_subtitle.configure(text="Click a card to apply it to all images", text_color="#64748B")
            for name, w in self.q_cards.items():
                w["frame"].configure(fg_color="#F8FAFC", border_color="#E2E8F0", border_width=1.5)
                w["badge"].pack_forget()
            return

        rec_presets = [recommend_preset_from_analysis(img["analysis"]) for img in self.images_data]
        rec = max(["Low", "Medium", "High"], key=rec_presets.count)
        self.suggested_overall_preset = rec
        avg_range = sum(img["analysis"]["dynamic_range"] for img in self.images_data) / len(self.images_data)

        qualities = set(img["quality"] for img in self.images_data)
        if len(qualities) == 1:
            shared_quality = list(qualities)[0]
            self.selected_preset_var.set(shared_quality)
            if hasattr(self, "lbl_quality_subtitle"):
                self.lbl_quality_subtitle.configure(text="Click a card to apply it to all images", text_color="#64748B")
            self.lbl_suggestion.configure(
                text=f"For these images we suggest {rec} (average contrast {avg_range:.0f}/255)."
            )
        else:
            shared_quality = None
            self.selected_preset_var.set("")
            if hasattr(self, "lbl_quality_subtitle"):
                self.lbl_quality_subtitle.configure(text="Images use different qualities", text_color="#D97706")
            self.lbl_suggestion.configure(
                text=f"Images use different qualities · Suggestion: {rec} (contrast {avg_range:.0f}/255)."
            )

        # Update quality card highlights: only highlight if all images share that quality
        for name, w in self.q_cards.items():
            is_sel = (name == shared_quality) if shared_quality else False
            w["frame"].configure(
                fg_color="#EFF6FF" if is_sel else "#F8FAFC",
                border_color="#2563EB" if is_sel else "#E2E8F0",
                border_width=2 if is_sel else 1.5
            )
            if name == rec:
                w["badge"].pack(side="right")
            else:
                w["badge"].pack_forget()

    # --------------------------------------------------------------------------
    # LIVE TACTILE PREVIEW & CROSS-SECTION
    # --------------------------------------------------------------------------
    def _update_preview(self):
        if not self.images_data or self.selected_idx >= len(self.images_data):
            self.lbl_preview_fname.configure(text="")
            self.lbl_preview_image.configure(image="", text="No preview available")
            return

        active = self.images_data[self.selected_idx]
        img_path = active["path"]
        quality = active["quality"]
        invert = active["invert"]

        self.lbl_preview_fname.configure(text=active["name"])

        try:
            sz_x = float(self.size_x_var.get())
        except Exception:
            sz_x = 100.0

        q_res = {"Low": 128, "Medium": 256, "High": 512}.get(quality, 256)
        if self.res_override_var.get().strip():
            try:
                q_res = int(self.res_override_var.get().strip())
            except Exception:
                pass

        aspect = active["height"] / max(1, active["width"])
        sz_y = round(sz_x * aspect, 1)

        self.lbl_meta_size.configure(text=f"{sz_x:.0f} × {sz_y:.0f} mm")
        self.lbl_meta_res.configure(text=f"{q_res} px")
        est_mb = estimate_stl_file_size(q_res, aspect)
        self.lbl_meta_stl.configure(text=f"~{format_file_size(est_mb)}")

        target_cols = min(256, q_res)
        target_rows = max(2, int(round(target_cols * aspect)))

        try:
            raw_img = Image.open(img_path)
        except Exception as e:
            self.lbl_preview_image.configure(image="", text=f"Could not load image:\n{e}")
            return

        if self.mode == "os":
            self.lbl_colormap_fallback.pack_forget()
            gray = raw_img.convert("L").resize((target_cols, target_rows), Image.LANCZOS)
            arr = np.array(gray, dtype=np.float32) / 255.0
            if invert:
                arr = 1.0 - arr
            self.lbl_meta_raised.configure(text="Dark areas" if invert else "Light areas")

            try:
                blur_s = float(self.blur_var.get())
                if blur_s > 0.05:
                    arr = gaussian_filter(arr, sigma=blur_s * (target_cols / 256.0))
            except Exception:
                pass

            ls = LightSource(azdeg=315, altdeg=45)
            shaded = ls.shade(arr, cmap=plt.cm.gray, blend_mode="overlay", vert_exag=1.5)
            pil_shaded = Image.fromarray((shaded[:, :, :3] * 255).astype(np.uint8))
            self._display_preview_image(pil_shaded)

        else:
            self.lbl_meta_raised.configure(text="High values (ramp)")
            tex_name = self.chroma_texture_var.get()
            colormap_name = self.chroma_colormap_var.get()
            ramp_elev = float(self.chroma_ramp_var.get())
            tex_relief = float(self.chroma_relief_var.get())
            polarity_inv = bool(invert)

            try:
                base_thick = float(self.base_thickness_var.get())
            except Exception:
                base_thick = 1.2

            scalar_field, fell_back = decode_colormap(raw_img, colormap_name=colormap_name, return_fallback_status=True)
            if fell_back:
                self.lbl_colormap_fallback.configure(text=f"Not a {colormap_name} image — using luminance")
                self.lbl_colormap_fallback.pack(fill="x", padx=16, pady=(0, 4), before=self.lbl_preview_hint)
            else:
                self.lbl_colormap_fallback.pack_forget()

            s_resized = Image.fromarray((scalar_field * 255).astype(np.uint8)).resize(
                (target_cols, target_rows), Image.BILINEAR
            )
            s_arr = np.array(s_resized, dtype=np.float32) / 255.0

            Z_ramp = build_ramp(target_rows, target_cols, (sz_x, sz_y), ramp_elev, direction="horizontal")
            Z_tex = apply_texture(s_arr, tex_name, (sz_x, sz_y), tex_relief, polarity_inverted=polarity_inv)
            Z_total = base_thick + Z_ramp + Z_tex

            ls = LightSource(azdeg=315, altdeg=20)
            shaded = ls.shade(Z_total, cmap=plt.cm.copper, blend_mode="overlay", vert_exag=2.0)
            pil_shaded = Image.fromarray((shaded[:, :, :3] * 255).astype(np.uint8))
            self._display_preview_image(pil_shaded)
            self._draw_cross_section_plot(Z_total, sz_x, base_thick)

    def _display_preview_image(self, pil_img):
        w, h = pil_img.size
        max_w, max_h = 280, 210
        scale = min(max_w / max(1, w), max_h / max(1, h))
        disp_w = max(1, int(w * scale))
        disp_h = max(1, int(h * scale))
        resized = pil_img.resize((disp_w, disp_h), Image.LANCZOS)
        self.ctk_preview_img = ctk.CTkImage(light_image=resized, dark_image=resized, size=(disp_w, disp_h))
        self.lbl_preview_image.configure(image=self.ctk_preview_img, text="")

    def _draw_cross_section_plot(self, Z, width_mm, z_base):
        mid_row = Z.shape[0] // 2
        profile_z = Z[mid_row, :]
        x_mm = np.linspace(0, width_mm, len(profile_z))

        fig = plt.Figure(figsize=(4.8, 1.2), dpi=80, facecolor="#FFFFFF")
        ax = fig.add_subplot(111)
        ax.set_facecolor("#F8FAFC")
        ax.fill_between(x_mm, 0, profile_z, color="#3B82F6", alpha=0.35)
        ax.plot(x_mm, profile_z, color="#1D4ED8", lw=1.5, label="Z(x) total")
        ax.axhline(z_base, color="#94A3B8", linestyle="--", lw=0.8, label=f"Base {z_base:.1f} mm")
        ax.set_xlim(0, width_mm)
        ax.set_ylim(0, max(profile_z) * 1.25)
        ax.set_xlabel("X (mm)", fontsize=7, color="#475569")
        ax.set_ylabel("Z (mm)", fontsize=7, color="#475569")
        ax.tick_params(axis="both", labelsize=6, colors="#64748B")
        ax.legend(fontsize=6, loc="upper left", framealpha=0.6)
        fig.tight_layout(pad=0.4)

        if self.plot_canvas:
            self.plot_canvas.get_tk_widget().destroy()

        self.plot_canvas = FigureCanvasTkAgg(fig, master=self.plot_container)
        self.plot_canvas.draw()
        self.plot_canvas.get_tk_widget().pack(fill="x", padx=4, pady=2)

    def _launch_pyvista_3d(self):
        if not PYVISTA_AVAILABLE:
            messagebox.showwarning("3D View Not Available", "PyVista is not installed or trame backend is missing.")
            return

        if not self.images_data or self.selected_idx >= len(self.images_data):
            messagebox.showinfo("No Image", "Add and select an image to inspect in 3D.")
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
        sz_y = sz_x * aspect
        cols = min(256, q_res)
        rows = max(2, int(round(cols * aspect)))

        raw = Image.open(img_path)

        if self.mode == "os":
            gray = raw.convert("L").resize((cols, rows), Image.LANCZOS)
            arr = np.array(gray, dtype=np.float32) / 255.0
            if invert:
                arr = 1.0 - arr
            try:
                blur_s = float(self.blur_var.get())
                if blur_s > 0.05:
                    arr = gaussian_filter(arr, sigma=blur_s * (cols / 256.0))
            except Exception:
                pass
            relief_mm = float(self.relief_var.get())
            base_thick = float(self.base_thickness_var.get())
            Z = base_thick + arr * relief_mm
        else:
            cm = self.chroma_colormap_var.get()
            ramp_elev = float(self.chroma_ramp_var.get())
            tex_name = self.chroma_texture_var.get()
            tex_relief = float(self.chroma_relief_var.get())
            pol_inv = bool(invert)
            base_thick = float(self.base_thickness_var.get())

            scalar_field = decode_colormap(raw, colormap_name=cm)
            s_resized = Image.fromarray((scalar_field * 255).astype(np.uint8)).resize((cols, rows), Image.BILINEAR)
            s_arr = np.array(s_resized, dtype=np.float32) / 255.0

            Z_ramp = build_ramp(rows, cols, (sz_x, sz_y), ramp_elev, direction="horizontal")
            Z_tex = apply_texture(s_arr, tex_name, (sz_x, sz_y), tex_relief, polarity_inverted=pol_inv)
            Z = base_thick + Z_ramp + Z_tex

        def run_viewer():
            try:
                x = np.linspace(0, sz_x, cols)
                y = np.linspace(0, sz_y, rows)
                xx, yy = np.meshgrid(x, y)
                grid = pv.StructuredGrid(xx, yy, Z)
                plotter = pv.Plotter(title=f"TAMP-OS 3D View: {active['name']}")
                plotter.add_mesh(grid, cmap="copper" if self.mode == "chroma" else "gray", show_edges=False, smooth_shading=True)
                plotter.show_axes()
                plotter.show()
            except Exception as e:
                print(f"PyVista launch error: {e}")

        threading.Thread(target=run_viewer, daemon=True).start()

    # --------------------------------------------------------------------------
    # BATCH GENERATION WORKER
    # --------------------------------------------------------------------------
    def _start_generation(self):
        if self.is_generating:
            return
        if not self.images_data:
            messagebox.showwarning("No Images", "Please add at least one image before generating.")
            return

        out_dir = Path(self.output_dir_var.get().strip() or str(Path.home() / "TAMP_output"))
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            messagebox.showerror("Invalid Output Folder", f"Could not create folder:\n{out_dir}\n\nError: {e}")
            return

        fmts = {
            "stl": self.fmt_stl_var.get(),
            "3mf": self.fmt_3mf_var.get(),
            "glb": self.fmt_glb_var.get(),
        }
        if not any(fmts.values()):
            messagebox.showwarning("No Formats", "Select at least one output format (.STL, .3MF, or .GLB).")
            return

        self.is_generating = True
        self.btn_generate.configure(state="disabled", text="Generating…")
        self.progress_bar.set(0)

        threading.Thread(target=self._generation_worker, args=(out_dir, fmts), daemon=True).start()

    def _generation_worker(self, out_dir, fmts):
        total = len(self.images_data)
        count = 0

        for idx, img_info in enumerate(self.images_data):
            name = img_info["name"]
            stem = Path(name).stem
            self.status_var.set(f"Generating {idx+1}/{total}: {name}…")
            self.progress_bar.set(idx / total)

            try:
                if self.mode == "os":
                    self._generate_os_item(img_info, out_dir, stem, fmts)
                else:
                    self._generate_chroma_item(img_info, out_dir, stem, fmts)
                count += 1
            except Exception as e:
                print(f"Error processing {name}: {e}")

        self.root.after(0, lambda: self._on_generation_finished(count, total, out_dir))

    def _generate_os_item(self, img_info, out_dir, stem, fmts):
        img_path = img_info["path"]
        quality = img_info["quality"]
        invert = img_info["invert"]

        try:
            sz_x = float(self.size_x_var.get())
        except Exception:
            sz_x = 100.0

        q_res = {"Low": 128, "Medium": 256, "High": 512}.get(quality, 256)
        if self.res_override_var.get().strip():
            try:
                q_res = int(self.res_override_var.get().strip())
            except Exception:
                pass

        aspect = img_info["height"] / max(1, img_info["width"])
        sz_y = round(sz_x * aspect, 1)
        cols = q_res
        rows = max(2, int(round(cols * aspect)))

        raw = Image.open(img_path).convert("L")
        resized = raw.resize((cols, rows), Image.LANCZOS)
        arr = np.array(resized, dtype=np.float32)

        # Contrast stretch
        lo, hi = np.percentile(arr, [2.0, 98.0])
        arr = np.clip((arr - lo) / (hi - lo + 1e-8), 0.0, 1.0)

        # Blur
        blur_s = float(self.blur_var.get() or 1.2)
        if blur_s > 0:
            arr = gaussian_filter(arr, sigma=blur_s)

        if invert:
            arr = 1.0 - arr

        if self.flip_var.get():
            arr = np.flipud(arr)

        base_th = float(self.base_thickness_var.get() or 1.2)
        relief = float(self.relief_var.get() or 3.0)

        stl_name = f"{stem}_TAMP_OS_{quality}.stl"
        stl_path = out_dir / stl_name
        heightmap_to_stl(arr, stl_path, base_thickness_mm=base_th, max_relief_mm=relief,
                         physical_size_mm=(sz_x, sz_y))

        convert_stl(stl_path, fmts)

    def _generate_chroma_item(self, img_info, out_dir, stem, fmts):
        img_path = img_info["path"]
        quality = img_info["quality"]
        polarity_inv = bool(img_info["invert"])

        cm = self.chroma_colormap_var.get()
        ramp_elev = float(self.chroma_ramp_var.get())
        tex_name = self.chroma_texture_var.get()
        tex_relief = float(self.chroma_relief_var.get())
        base_thick = float(self.base_thickness_var.get() or 1.2)

        try:
            sz_x = float(self.size_x_var.get())
        except Exception:
            sz_x = 100.0

        q_res = {"Low": 128, "Medium": 256, "High": 512}.get(quality, 256)
        aspect = img_info["height"] / max(1, img_info["width"])
        sz_y = round(sz_x * aspect, 1)
        cols = q_res
        rows = max(2, int(round(cols * aspect)))

        raw = Image.open(img_path)
        scalar_field = decode_colormap(raw, colormap_name=cm)
        s_resized = Image.fromarray((scalar_field * 255).astype(np.uint8)).resize((cols, rows), Image.BILINEAR)
        s_arr = np.array(s_resized, dtype=np.float32) / 255.0

        Z_ramp = build_ramp(rows, cols, (sz_x, sz_y), ramp_elev, direction="horizontal")
        Z_tex = apply_texture(s_arr, tex_name, (sz_x, sz_y), tex_relief, polarity_inverted=polarity_inv)
        Z_total = base_thick + Z_ramp + Z_tex

        if self.flip_var.get():
            Z_total = np.flipud(Z_total)

        stl_name = f"{stem}_Chroma_{tex_name}_{quality}.stl"
        stl_path = out_dir / stl_name

        surface_z_to_stl(Z_total, stl_path, physical_size_mm=(sz_x, sz_y))
        convert_stl(stl_path, fmts)

    def _on_generation_finished(self, count, total, out_dir):
        self.is_generating = False
        self.progress_bar.set(1.0)
        self.btn_generate.configure(state="normal", text="Generate print files" if self.mode == "os" else "Generate tactile files")
        self.status_var.set(f"Done! {count}/{total} files generated in {out_dir.name}")
        messagebox.showinfo("Generation Complete", f"Successfully generated {count}/{total} models in:\n{out_dir}")

    def _open_output_folder(self):
        out_dir = Path(self.output_dir_var.get().strip())
        out_dir.mkdir(parents=True, exist_ok=True)
        if sys.platform.startswith("win"):
            os.startfile(out_dir)
        elif sys.platform.startswith("darwin"):
            import subprocess
            subprocess.Popen(["open", str(out_dir)])
        else:
            import subprocess
            subprocess.Popen(["xdg-open", str(out_dir)])

    def _browse_output_dir(self):
        d = filedialog.askdirectory(title="Select Output Folder", initialdir=self.output_dir_var.get())
        if d:
            self.output_dir_var.set(d)
            self.cfg["output_dir"] = d
            save_settings(self.cfg)

    def _update_status_summary(self):
        count = len(self.images_data)
        fmt_count = sum([self.fmt_stl_var.get(), self.fmt_3mf_var.get(), self.fmt_glb_var.get()])

        try:
            sz_x = float(self.size_x_var.get())
        except Exception:
            sz_x = 100.0

        est_tot_mb = sum(
            estimate_stl_file_size(
                {"Low": 128, "Medium": 256, "High": 512}.get(img["quality"], 256),
                img["height"] / max(1, img["width"])
            ) for img in self.images_data
        ) if self.images_data else 0.0

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
    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme("blue")
    root = ctk.CTk()
    app = TAMPGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()

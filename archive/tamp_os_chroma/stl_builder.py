"""
TAMP-OS-Chroma: High-Performance Vectorized STL Mesh Builder
------------------------------------------------------------
Constructs watertight, manifold 3D printable STL lithographs from heightmaps
using fully vectorized numpy operations. Supports solid bases, boundary frames,
and companion tactile legend swatches.
"""

from typing import Tuple, Optional
from pathlib import Path
import numpy as np
from stl import mesh


def heightmap_to_stl(
    heightmap: np.ndarray,
    output_path: str,
    physical_size_mm: Tuple[float, float] = (100.0, 56.25),
    base_thickness_mm: float = 1.2,
    max_relief_mm: Optional[float] = None,
    border_frame_mm: float = 0.0,
    border_height_mm: float = 0.0
) -> str:
    """
    Converts a 2D heightmap into a solid, watertight STL mesh.

    Parameters:
      heightmap: 2D float array in mm (or normalized [0, 1] if max_relief_mm is provided).
      output_path: Target .stl file path.
      physical_size_mm: (width_x, height_y) in mm.
      base_thickness_mm: Solid base floor thickness in mm (default 1.2 mm).
      max_relief_mm: If provided, scales heightmap [0, 1] to this relief. If None, assumes heightmap is already in mm.
      border_frame_mm: Optional flat raised border margin width around the tile.
      border_height_mm: Height of the border frame above the base.
    """
    rows, cols = heightmap.shape
    size_x, size_y = physical_size_mm
    dx = size_x / (cols - 1)
    dy = size_y / (rows - 1)

    if max_relief_mm is not None:
        z_relief = heightmap * max_relief_mm
    else:
        z_relief = heightmap.copy()

    z_top = base_thickness_mm + z_relief

    # Añadir marco perimetral opcional si se especifica
    if border_frame_mm > 0:
        frame_px_x = int(np.round(border_frame_mm / dx))
        frame_px_y = int(np.round(border_frame_mm / dy))
        if frame_px_x > 0 and frame_px_y > 0:
            frame_h = base_thickness_mm + border_height_mm
            z_top[:frame_px_y, :] = frame_h
            z_top[-frame_px_y:, :] = frame_h
            z_top[:, :frame_px_x] = frame_h
            z_top[:, -frame_px_x:] = frame_h

    # Coordenadas X, Y
    x_coords = np.linspace(0.0, size_x, cols, dtype=np.float32)
    y_coords = np.linspace(0.0, size_y, rows, dtype=np.float32)
    X, Y = np.meshgrid(x_coords, y_coords)

    # Cálculo del total de triángulos
    num_grid_cells = (rows - 1) * (cols - 1)
    num_tris_top = num_grid_cells * 2
    num_tris_bottom = num_grid_cells * 2
    num_tris_walls = 2 * ((rows - 1) + (cols - 1)) * 2
    total_tris = num_tris_top + num_tris_bottom + num_tris_walls

    litho_mesh = mesh.Mesh(np.zeros(total_tris, dtype=mesh.Mesh.dtype))

    # --- Triangulación vectorizada de superficie superior ---
    # Esquinas de cada celda: (r, c), (r, c+1), (r+1, c), (r+1, c+1)
    # v0: (r, c), v1: (r, c+1), v2: (r+1, c), v3: (r+1, c+1)
    v0 = np.stack([X[:-1, :-1], Y[:-1, :-1], z_top[:-1, :-1]], axis=-1).reshape(-1, 3)
    v1 = np.stack([X[:-1, 1:], Y[:-1, 1:], z_top[:-1, 1:]], axis=-1).reshape(-1, 3)
    v2 = np.stack([X[1:, :-1], Y[1:, :-1], z_top[1:, :-1]], axis=-1).reshape(-1, 3)
    v3 = np.stack([X[1:, 1:], Y[1:, 1:], z_top[1:, 1:]], axis=-1).reshape(-1, 3)

    # Triángulo superior 1: v0 -> v1 -> v2
    litho_mesh.vectors[0:num_grid_cells] = np.stack([v0, v1, v2], axis=1)
    # Triángulo superior 2: v1 -> v3 -> v2
    litho_mesh.vectors[num_grid_cells:2*num_grid_cells] = np.stack([v1, v3, v2], axis=1)

    # --- Triangulación vectorizada de base inferior (z = 0) ---
    b0 = np.stack([X[:-1, :-1], Y[:-1, :-1], np.zeros_like(z_top[:-1, :-1])], axis=-1).reshape(-1, 3)
    b1 = np.stack([X[:-1, 1:], Y[:-1, 1:], np.zeros_like(z_top[:-1, 1:])], axis=-1).reshape(-1, 3)
    b2 = np.stack([X[1:, :-1], Y[1:, :-1], np.zeros_like(z_top[1:, :-1])], axis=-1).reshape(-1, 3)
    b3 = np.stack([X[1:, 1:], Y[1:, 1:], np.zeros_like(z_top[1:, 1:])], axis=-1).reshape(-1, 3)

    # Base inferior con normales apuntando hacia abajo: b0 -> b2 -> b1 y b1 -> b2 -> b3
    litho_mesh.vectors[2*num_grid_cells:3*num_grid_cells] = np.stack([b0, b2, b1], axis=1)
    litho_mesh.vectors[3*num_grid_cells:4*num_grid_cells] = np.stack([b1, b2, b3], axis=1)

    # --- Paredes perimetrales ---
    curr_idx = 4 * num_grid_cells

    # Pared Sur (r = 0, Y = 0)
    w_x0 = x_coords[:-1]
    w_x1 = x_coords[1:]
    w_z0 = z_top[0, :-1]
    w_z1 = z_top[0, 1:]
    n_cols = cols - 1

    p0 = np.stack([w_x0, np.zeros(n_cols), np.zeros(n_cols)], axis=-1)
    p1 = np.stack([w_x1, np.zeros(n_cols), np.zeros(n_cols)], axis=-1)
    p2 = np.stack([w_x0, np.zeros(n_cols), w_z0], axis=-1)
    p3 = np.stack([w_x1, np.zeros(n_cols), w_z1], axis=-1)

    litho_mesh.vectors[curr_idx:curr_idx + n_cols] = np.stack([p0, p1, p2], axis=1)
    curr_idx += n_cols
    litho_mesh.vectors[curr_idx:curr_idx + n_cols] = np.stack([p1, p3, p2], axis=1)
    curr_idx += n_cols

    # Pared Norte (r = rows-1, Y = size_y)
    w_z0 = z_top[-1, :-1]
    w_z1 = z_top[-1, 1:]
    y_max = np.full(n_cols, size_y, dtype=np.float32)

    p0 = np.stack([w_x0, y_max, np.zeros(n_cols)], axis=-1)
    p1 = np.stack([w_x1, y_max, np.zeros(n_cols)], axis=-1)
    p2 = np.stack([w_x0, y_max, w_z0], axis=-1)
    p3 = np.stack([w_x1, y_max, w_z1], axis=-1)

    litho_mesh.vectors[curr_idx:curr_idx + n_cols] = np.stack([p0, p2, p1], axis=1)
    curr_idx += n_cols
    litho_mesh.vectors[curr_idx:curr_idx + n_cols] = np.stack([p1, p2, p3], axis=1)
    curr_idx += n_cols

    # Pared Oeste (c = 0, X = 0)
    w_y0 = y_coords[:-1]
    w_y1 = y_coords[1:]
    w_z0 = z_top[:-1, 0]
    w_z1 = z_top[1:, 0]
    n_rows = rows - 1

    p0 = np.stack([np.zeros(n_rows), w_y0, np.zeros(n_rows)], axis=-1)
    p1 = np.stack([np.zeros(n_rows), w_y1, np.zeros(n_rows)], axis=-1)
    p2 = np.stack([np.zeros(n_rows), w_y0, w_z0], axis=-1)
    p3 = np.stack([np.zeros(n_rows), w_y1, w_z1], axis=-1)

    litho_mesh.vectors[curr_idx:curr_idx + n_rows] = np.stack([p0, p2, p1], axis=1)
    curr_idx += n_rows
    litho_mesh.vectors[curr_idx:curr_idx + n_rows] = np.stack([p1, p2, p3], axis=1)
    curr_idx += n_rows

    # Pared Este (c = cols-1, X = size_x)
    w_z0 = z_top[:-1, -1]
    w_z1 = z_top[1:, -1]
    x_max = np.full(n_rows, size_x, dtype=np.float32)

    p0 = np.stack([x_max, w_y0, np.zeros(n_rows)], axis=-1)
    p1 = np.stack([x_max, w_y1, np.zeros(n_rows)], axis=-1)
    p2 = np.stack([x_max, w_y0, w_z0], axis=-1)
    p3 = np.stack([x_max, w_y1, w_z1], axis=-1)

    litho_mesh.vectors[curr_idx:curr_idx + n_rows] = np.stack([p0, p1, p2], axis=1)
    curr_idx += n_rows
    litho_mesh.vectors[curr_idx:curr_idx + n_rows] = np.stack([p1, p3, p2], axis=1)
    curr_idx += n_rows

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    litho_mesh.save(str(output_path))
    return str(output_path)


def generate_tactile_legend_stl(
    output_path: str,
    num_zones: int = 5,
    swatch_size_mm: Tuple[float, float] = (15.0, 18.0),
    base_thickness_mm: float = 1.2,
    max_relief_mm: float = 0.8
) -> str:
    """
    Generates a 3D printable companion tactile legend card (muestrario táctil).
    Contains each of the 5 textures in isolated swatches, with tactile indicator
    dots (1 to 5 dots) underneath each swatch for tactile identification.
    """
    total_w_mm = num_zones * swatch_size_mm[0] + (num_zones + 1) * 3.0
    total_h_mm = swatch_size_mm[1] + 12.0  # Espacio para swatch + indicadores braille/puntos

    cols = int(total_w_mm * 5)  # 0.2 mm resolución de muestreo
    rows = int(total_h_mm * 5)

    x = np.linspace(0.0, total_w_mm, cols, dtype=np.float32)
    y = np.linspace(0.0, total_h_mm, rows, dtype=np.float32)
    XX, YY = np.meshgrid(x, y)

    legend_map = np.zeros((rows, cols), dtype=np.float32)

    spacing_border = 3.0
    for z in range(num_zones):
        x_start = spacing_border + z * (swatch_size_mm[0] + spacing_border)
        x_end = x_start + swatch_size_mm[0]
        y_start = 10.0
        y_end = y_start + swatch_size_mm[1]

        mask = (XX >= x_start) & (XX <= x_end) & (YY >= y_start) & (YY <= y_end)

        # Aplicar la textura correspondiente a cada swatch
        if z == 0:
            pass  # Liso
        elif z == 1:
            pitch = 2.5
            dots = (0.5 * (np.cos(2.0 * np.pi * XX / pitch) + 1.0) *
                    0.5 * (np.cos(2.0 * np.pi * YY / pitch) + 1.0))
            legend_map[mask] = np.power(dots[mask], 3.0) * max_relief_mm
        elif z == 2:
            pitch = 2.2
            diag = (XX + YY) / np.sqrt(2.0)
            lines = np.power(0.5 * (np.cos(2.0 * np.pi * diag / pitch) + 1.0), 1.8)
            legend_map[mask] = lines[mask] * max_relief_mm
        elif z == 3:
            pitch = 2.5
            gx = 0.5 * (np.cos(2.0 * np.pi * XX / pitch) + 1.0)
            gy = 0.5 * (np.cos(2.0 * np.pi * YY / pitch) + 1.0)
            grid = np.maximum(np.power(gx, 2.5), np.power(gy, 2.5))
            legend_map[mask] = grid[mask] * max_relief_mm
        elif z == 4:
            pitch = 1.8
            wave = XX + 0.3 * np.sin(2.0 * np.pi * YY / 3.0)
            wavy = np.power(0.5 * (np.cos(2.0 * np.pi * wave / pitch) + 1.0), 1.5)
            legend_map[mask] = wavy[mask] * max_relief_mm

        # Bordillo alrededor de cada swatch
        border_mask = (
            ((np.abs(XX - x_start) < 0.4) | (np.abs(XX - x_end) < 0.4)) & (YY >= y_start) & (YY <= y_end)
        ) | (
            ((np.abs(YY - y_start) < 0.4) | (np.abs(YY - y_end) < 0.4)) & (XX >= x_start) & (XX <= x_end)
        )
        legend_map[border_mask] = 0.4

        # Puntos indicadores debajo de cada swatch (z+1 puntos táctiles para contar con el dedo)
        num_dots = z + 1
        dot_y = 5.0
        center_x = (x_start + x_end) * 0.5
        for d in range(num_dots):
            dot_x = center_x + (d - (num_dots - 1) / 2.0) * 2.2
            dist_sq = (XX - dot_x)**2 + (YY - dot_y)**2
            dot_shape = np.maximum(0.0, 1.0 - dist_sq / (0.75**2))
            legend_map += np.power(dot_shape, 1.5) * 0.6

    return heightmap_to_stl(
        legend_map,
        output_path,
        physical_size_mm=(total_w_mm, total_h_mm),
        base_thickness_mm=base_thickness_mm
    )

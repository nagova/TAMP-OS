"""
TAMP-OS-Chroma: Procedural Tactile Texture Engine & Library
------------------------------------------------------------
Implements a rich library of tactile textures designed specifically for
FDM 3D printing (nozzle 0.4 mm, layer 0.16-0.20 mm) and fingertip perception
(spatial acuity >= 1.2-1.5 mm, relief >= 0.4-0.8 mm).

Core principle:
  ALWAYS combines the macroscopic TAMP-OS elevation ramp with continuous
  texture density/saturation modulation, preserving the essence of TAMP-OS
  while adding multi-sensory haptic confirmation.
"""

from typing import Tuple, Dict, Callable
import numpy as np
from scipy.ndimage import gaussian_filter


# ---------------------------------------------------------------------------
# Funciones individuales de textura modulada en frecuencia / densidad
# ---------------------------------------------------------------------------

def texture_dots(
    X: np.ndarray,
    Y: np.ndarray,
    scalar: np.ndarray,
    min_spacing: float = 1.8,
    max_spacing: float = 4.8
) -> np.ndarray:
    """Puntos táctiles (stippling): densidad y relieve aumentan con scalar."""
    spacing = max_spacing - scalar * (max_spacing - min_spacing)
    spacing = np.maximum(spacing, 0.8)

    # 2D phase integration across grid
    mean_sp_x = np.mean(spacing, axis=0)
    omega_x = 2.0 * np.pi / mean_sp_x
    dx = (X[0, 1] - X[0, 0]) if X.shape[1] > 1 else 0.25
    phase_x = np.cumsum(omega_x) * dx
    phase_x_2d = np.tile(phase_x, (X.shape[0], 1))

    mean_sp_y = np.mean(spacing, axis=1)
    omega_y = 2.0 * np.pi / mean_sp_y
    dy = (Y[1, 0] - Y[0, 0]) if Y.shape[0] > 1 else 0.25
    phase_y = np.cumsum(omega_y) * dy
    phase_y_2d = np.tile(phase_y[:, None], (1, X.shape[1]))

    dots = 0.5 * (np.cos(phase_x_2d) + 1.0) * 0.5 * (np.cos(phase_y_2d) + 1.0)
    return np.power(dots, 2.2) * scalar


def texture_linear_x(
    X: np.ndarray,
    Y: np.ndarray,
    scalar: np.ndarray,
    min_period: float = 1.3,
    max_period: float = 4.5
) -> np.ndarray:
    """Estrías lineales verticales (surcos a lo largo de Y, compresión en X)."""
    period = max_period - scalar * (max_period - min_period)
    period = np.maximum(period, 0.6)
    omega_x = 2.0 * np.pi / np.mean(period, axis=0)
    dx = (X[0, 1] - X[0, 0]) if X.shape[1] > 1 else 0.25
    phase_x = np.tile(np.cumsum(omega_x) * dx, (X.shape[0], 1))
    wave = 0.5 * (np.cos(phase_x) + 1.0)
    return np.power(wave, 1.8) * scalar


def texture_linear_y(
    X: np.ndarray,
    Y: np.ndarray,
    scalar: np.ndarray,
    min_period: float = 1.3,
    max_period: float = 4.5
) -> np.ndarray:
    """Estrías lineales horizontales (surcos a lo largo de X, compresión en Y)."""
    period = max_period - scalar * (max_period - min_period)
    period = np.maximum(period, 0.6)
    omega_y = 2.0 * np.pi / np.mean(period, axis=1)
    dy = (Y[1, 0] - Y[0, 0]) if Y.shape[0] > 1 else 0.25
    phase_y = np.tile((np.cumsum(omega_y) * dy)[:, None], (1, X.shape[1]))
    wave = 0.5 * (np.cos(phase_y) + 1.0)
    return np.power(wave, 1.8) * scalar


def texture_diagonal_45(
    X: np.ndarray,
    Y: np.ndarray,
    scalar: np.ndarray,
    min_period: float = 1.4,
    max_period: float = 4.2
) -> np.ndarray:
    """Estrías diagonales a 45° con frecuencia variable."""
    period = max_period - scalar * (max_period - min_period)
    diag_coords = (X + Y) / np.sqrt(2.0)
    local_omega = 2.0 * np.pi / np.maximum(period, 0.6)
    # Simple direct phase mapping for diagonal
    phase = local_omega * diag_coords
    wave = 0.5 * (np.cos(phase) + 1.0)
    return np.power(wave, 1.8) * scalar


def texture_crosshatch(
    X: np.ndarray,
    Y: np.ndarray,
    scalar: np.ndarray,
    min_period: float = 1.6,
    max_period: float = 4.6
) -> np.ndarray:
    """Malla / cuadrícula ortogonal (crosshatch) con densidad progresiva."""
    p = max_period - scalar * (max_period - min_period)
    p = np.maximum(p, 0.8)
    gx = 0.5 * (np.cos(2.0 * np.pi * X / p) + 1.0)
    gy = 0.5 * (np.cos(2.0 * np.pi * Y / p) + 1.0)
    grid = np.maximum(np.power(gx, 2.0), np.power(gy, 2.0))
    return grid * scalar


def texture_waves(
    X: np.ndarray,
    Y: np.ndarray,
    scalar: np.ndarray,
    min_period: float = 1.5,
    max_period: float = 4.0
) -> np.ndarray:
    """Ondulaciones sinusoidales fluidas (waves)."""
    p = max_period - scalar * (max_period - min_period)
    p = np.maximum(p, 0.8)
    wave_phase = X + 0.6 * np.sin(2.0 * np.pi * Y / 3.5)
    wave = 0.5 * (np.cos(2.0 * np.pi * wave_phase / p) + 1.0)
    return np.power(wave, 1.6) * scalar


def texture_honeycomb(
    X: np.ndarray,
    Y: np.ndarray,
    scalar: np.ndarray,
    min_cell: float = 2.0,
    max_cell: float = 5.0
) -> np.ndarray:
    """Panal hexagonal / knurling táctil con celdas de tamaño variable."""
    s = max_cell - scalar * (max_cell - min_cell)
    s = np.maximum(s, 1.0)
    # Hexagonal coordinate waves: three planar waves at 0, 60, 120 degrees
    w1 = np.cos(2.0 * np.pi * X / s)
    w2 = np.cos(2.0 * np.pi * (0.5 * X + 0.866 * Y) / s)
    w3 = np.cos(2.0 * np.pi * (-0.5 * X + 0.866 * Y) / s)
    hex_pattern = (w1 + w2 + w3 + 1.5) / 4.5
    return np.power(np.clip(hex_pattern, 0.0, 1.0), 2.0) * scalar


def texture_scales(
    X: np.ndarray,
    Y: np.ndarray,
    scalar: np.ndarray,
    min_scale: float = 2.0,
    max_scale: float = 5.0
) -> np.ndarray:
    """Escamas semicirculares imbricadas con relieve creciente."""
    s = max_scale - scalar * (max_scale - min_scale)
    s = np.maximum(s, 1.0)
    cx = (X % s) - s * 0.5
    cy = (Y % (s * 0.8)) - s * 0.4
    r = np.sqrt(cx**2 + cy**2) / (s * 0.5)
    scale_shape = np.maximum(0.0, 1.0 - r**2)
    return np.power(scale_shape, 1.5) * scalar


# Diccionario público de la biblioteca de texturas
TEXTURE_LIBRARY: Dict[str, Tuple[str, Callable]] = {
    "dots": ("Puntos Táctiles (Stippling)", texture_dots),
    "lines_x": ("Estrías Lineales Verticales", texture_linear_x),
    "lines_y": ("Estrías Lineales Horizontales", texture_linear_y),
    "diagonal_45": ("Estrías Diagonales a 45°", texture_diagonal_45),
    "crosshatch": ("Cuadrícula / Malla Ortogonal", texture_crosshatch),
    "waves": ("Ondulaciones Sinusoidales", texture_waves),
    "honeycomb": ("Panal Hexagonal (Knurling)", texture_honeycomb),
    "scales": ("Escamas Semicirculares", texture_scales)
}


# ---------------------------------------------------------------------------
# Función unificada: Rampa TAMP-OS + Modulación de Textura
# ---------------------------------------------------------------------------

def generate_textured_ramp(
    scalar_map: np.ndarray,
    texture_name: str = "dots",
    physical_size_mm: Tuple[float, float] = (100.0, 56.25),
    ramp_height_mm: float = 1.8,
    texture_relief_mm: float = 0.6,
    invert_ramp: bool = False,
    invert_texture: bool = False
) -> np.ndarray:
    """
    Genera el relieve total Z(x, y) manteniendo la esencia de TAMP-OS:
      Z_total = Base_Rampa(x, y) + Textura_Modulada(x, y)

    Donde:
      - Base_Rampa: elevación continua proporcional a scalar_map (la rampa TAMP-OS).
      - Textura_Modulada: microtextura cuya frecuencia y amplitud se saturan con scalar_map.
    """
    rows, cols = scalar_map.shape
    size_x, size_y = physical_size_mm

    x = np.linspace(0.0, size_x, cols, dtype=np.float32)
    y = np.linspace(0.0, size_y, rows, dtype=np.float32)
    XX, YY = np.meshgrid(x, y)

    # Escalares para rampa y textura (respetando polaridad)
    s_ramp = (1.0 - scalar_map) if invert_ramp else scalar_map
    s_tex = (1.0 - scalar_map) if invert_texture else scalar_map

    # 1. Rampa macroscópica TAMP-OS
    z_ramp = s_ramp * ramp_height_mm

    # 2. Textura seleccionada de la biblioteca
    t_key = texture_name.lower()
    if t_key not in TEXTURE_LIBRARY:
        t_key = "dots"

    _, tex_func = TEXTURE_LIBRARY[t_key]
    tex_normalized = tex_func(XX, YY, s_tex)
    z_texture = tex_normalized * texture_relief_mm

    total_relief = z_ramp + z_texture
    return total_relief

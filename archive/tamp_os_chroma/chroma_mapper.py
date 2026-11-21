"""
TAMP-OS-Chroma: Colormap & Concentration Mapper
-----------------------------------------------
Converts color images (e.g. false-color operando microscopy, chemical mapping,
or colormap gradients) into normalized scalar concentration maps [0.0, 1.0].

Supports:
  - Scientific colormaps: inferno, viridis, plasma, magma, turbo
  - SVD / PCA Chromatic axis: continuous color manifold projection (ideal for 2D multi-color swatches)
  - Spectral / Hue mapping: red -> yellow -> green -> cyan -> blue -> purple
  - Luminance conversion: standard perceptual grayscale
  - Polarity inversion: invert=True/False (White/Max color = Highest vs Lowest)
"""

from typing import Tuple, Optional, Union
import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter
import matplotlib.colors as mcolors
import matplotlib as mpl


def load_image(image_input: Union[str, Image.Image]) -> np.ndarray:
    """Load an image and return an RGB float32 array in [0, 1]."""
    if isinstance(image_input, str):
        img = Image.open(image_input)
    else:
        img = image_input

    img = img.convert("RGB")
    return np.asarray(img, dtype=np.float32) / 255.0


def map_svd_chromatic(rgb_array: np.ndarray) -> np.ndarray:
    """
    Finds the first principal chromatic axis using Singular Value Decomposition (SVD).
    Extracts the dominant continuous color progression in arbitrary multi-color 2D gradients
    without branch cut discontinuities.
    """
    h, w, _ = rgb_array.shape
    flat = rgb_array.reshape(-1, 3)
    mean = np.mean(flat, axis=0)
    centered = flat - mean
    _, _, vt = np.linalg.svd(centered, full_matrices=False)
    proj = np.dot(centered, vt[0]).reshape(h, w)
    lo, hi = proj.min(), proj.max()
    if hi > lo:
        proj = (proj - lo) / (hi - lo)
    else:
        proj = np.zeros_like(proj)
    return proj.astype(np.float32)


def map_spectral_hue(rgb_array: np.ndarray) -> np.ndarray:
    """Extracts scalar values from chromatic/rainbow spectra using HSV Hue."""
    hsv = mcolors.rgb_to_hsv(rgb_array)
    hue = hsv[:, :, 0].astype(np.float32)
    sat = hsv[:, :, 1].astype(np.float32)
    val = hsv[:, :, 2].astype(np.float32)
    scalar = np.where(sat < 0.1, val, hue)
    return np.clip(scalar, 0.0, 1.0)


def project_onto_colormap(rgb_array: np.ndarray, colormap_name: str = "inferno", steps: int = 512) -> np.ndarray:
    """
    Projects each pixel's RGB value onto a known matplotlib colormap curve.
    Finds the scalar t in [0.0, 1.0] whose colormap RGB value is closest in Euclidean space.
    """
    try:
        cmap = mpl.colormaps[colormap_name]
    except Exception:
        import matplotlib.cm as cm
        cmap = cm.get_cmap(colormap_name)

    t_vals = np.linspace(0.0, 1.0, steps, dtype=np.float32)
    ref_rgb = cmap(t_vals)[:, :3].astype(np.float32)

    h, w, _ = rgb_array.shape
    flat_rgb = rgb_array.reshape(-1, 3)

    chunk_size = 50000
    closest_indices = np.zeros(flat_rgb.shape[0], dtype=np.int32)
    ref_sq = np.sum(ref_rgb**2, axis=1)

    for start in range(0, flat_rgb.shape[0], chunk_size):
        end = min(start + chunk_size, flat_rgb.shape[0])
        chunk = flat_rgb[start:end]
        chunk_sq = np.sum(chunk**2, axis=1, keepdims=True)
        dist_sq = chunk_sq - 2.0 * np.dot(chunk, ref_rgb.T) + ref_sq
        closest_indices[start:end] = np.argmin(dist_sq, axis=1)

    scalar_map = t_vals[closest_indices].reshape(h, w)
    return scalar_map


def map_luminance(rgb_array: np.ndarray, contrast_percentile: Tuple[float, float] = (1.0, 99.0)) -> np.ndarray:
    """Standard perceptual luminance conversion Y = 0.299 R + 0.587 G + 0.114 B."""
    lum = 0.299 * rgb_array[:, :, 0] + 0.587 * rgb_array[:, :, 1] + 0.114 * rgb_array[:, :, 2]
    lo = np.percentile(lum, contrast_percentile[0])
    hi = np.percentile(lum, contrast_percentile[1])
    if hi > lo:
        lum = np.clip((lum - lo) / (hi - lo), 0.0, 1.0)
    else:
        lum = np.zeros_like(lum)
    return lum


def extract_concentration_map(
    image_input: Union[str, Image.Image],
    method: str = "inferno",
    invert: bool = False,
    blur_sigma: float = 0.0,
    target_size: Optional[Tuple[int, int]] = None
) -> np.ndarray:
    """
    Main extraction pipeline:
      1. Loads image.
      2. Resizes if target_size (width, height) is specified.
      3. Maps RGB to scalar [0.0, 1.0] using specified method:
         'inferno', 'viridis', 'plasma', 'magma', 'turbo', 'svd'/'chromatic', 'spectral'/'hue', or 'luminance'.
      4. Applies Gaussian smoothing if blur_sigma > 0.
      5. Inverts polarity if invert is True (1.0 - val).
    """
    if isinstance(image_input, str):
        pil_img = Image.open(image_input).convert("RGB")
    else:
        pil_img = image_input.convert("RGB")

    if target_size is not None:
        pil_img = pil_img.resize(target_size, Image.LANCZOS)

    rgb = np.asarray(pil_img, dtype=np.float32) / 255.0
    m_lower = method.lower()

    if m_lower in ["svd", "chromatic", "pca"]:
        val_map = map_svd_chromatic(rgb)
    elif m_lower in ["spectral", "hue", "rainbow"]:
        val_map = map_spectral_hue(rgb)
    elif m_lower in ["inferno", "viridis", "plasma", "magma", "turbo", "cividis"]:
        val_map = project_onto_colormap(rgb, colormap_name=m_lower)
    elif m_lower == "luminance":
        val_map = map_luminance(rgb)
    else:
        try:
            val_map = project_onto_colormap(rgb, colormap_name=m_lower)
        except Exception:
            val_map = map_svd_chromatic(rgb)

    if blur_sigma > 0:
        val_map = gaussian_filter(val_map, sigma=blur_sigma)

    val_map = np.clip(val_map, 0.0, 1.0)

    if invert:
        val_map = 1.0 - val_map

    return val_map

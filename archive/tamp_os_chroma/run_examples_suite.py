"""
TAMP-OS-Chroma: Generador de Ejemplos con Rampa TAMP-OS + Textura Modulada
--------------------------------------------------------------------------
Procesa ambos casos de estudio:
  - Ejemplo 1: Gradiente horizontal de concentración de Li (Colormap Inferno).
  - Ejemplo 2: Mapa cromático bidimensional multicolor (Eje cromático continuo SVD).

Aplica la fórmula fundamental:
  Z_total = Espesor_Base + Rampa_TAMP-OS(x, y) + Textura_Modulada(x, y)
"""

import sys
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import LightSource
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from chroma_mapper import extract_concentration_map
from texture_engine import generate_textured_ramp, TEXTURE_LIBRARY
from stl_builder import heightmap_to_stl


def process_example(
    image_path: str,
    output_prefix: str,
    colormap_method: str,
    physical_width_mm: float = 100.0,
    base_thickness_mm: float = 1.2,
    ramp_height_mm: float = 1.8,
    texture_relief_mm: float = 0.6,
    selected_textures: list = ["dots", "lines_x", "waves", "scales"]
):
    ex_dir = Path(__file__).parent / "examples"
    ex_dir.mkdir(parents=True, exist_ok=True)

    img = Image.open(image_path).convert("RGB")
    aspect = img.height / img.width
    physical_height_mm = round(physical_width_mm * aspect, 2)
    physical_size_mm = (physical_width_mm, physical_height_mm)

    grid_cols = 400
    grid_rows = int(400 * aspect)
    grid_res = (grid_cols, grid_rows)

    print(f"\nProcesando {output_prefix}:")
    print(f"  Imagen: {image_path}")
    print(f"  Método de mapeo: {colormap_method}")
    print(f"  Tamaño físico: {physical_size_mm[0]} x {physical_size_mm[1]} mm")

    scalar_map = extract_concentration_map(
        image_path,
        method=colormap_method,
        invert=False,
        blur_sigma=1.0,
        target_size=grid_res
    )

    ls = LightSource(azdeg=315, altdeg=35)
    dx = physical_width_mm / (grid_cols - 1)
    dy = physical_height_mm / (grid_rows - 1)

    generated_stls = []
    heightmaps = {}

    for tex_id in selected_textures:
        tex_label = TEXTURE_LIBRARY.get(tex_id, (tex_id, None))[0]
        z_relief = generate_textured_ramp(
            scalar_map,
            texture_name=tex_id,
            physical_size_mm=physical_size_mm,
            ramp_height_mm=ramp_height_mm,
            texture_relief_mm=texture_relief_mm
        )
        heightmaps[tex_id] = z_relief

        stl_name = f"{output_prefix}_rampa_{tex_id}.stl"
        stl_path = ex_dir / stl_name
        heightmap_to_stl(
            z_relief,
            str(stl_path),
            physical_size_mm=physical_size_mm,
            base_thickness_mm=base_thickness_mm
        )
        generated_stls.append((stl_name, stl_path))
        print(f"  [OK] STL generado: {stl_name}")

    # Generar figura comparativa con simulación háptica
    n_plots = len(selected_textures) + 2
    fig, axes = plt.subplots(n_plots, 1, figsize=(10, 2.3 * n_plots), constrained_layout=True)

    axes[0].imshow(img)
    axes[0].set_title(f"{output_prefix.upper()} - Imagen Original en Color", fontsize=11, fontweight="bold")
    axes[0].axis("off")

    im_scal = axes[1].imshow(scalar_map, cmap="viridis", origin="upper")
    axes[1].set_title(f"Mapa Escalar Decodificado [0, 1] (Método: {colormap_method.upper()} - Rampa Base TAMP-OS)", fontsize=11, fontweight="bold")
    axes[1].axis("off")
    fig.colorbar(im_scal, ax=axes[1], orientation="vertical", fraction=0.03, pad=0.02)

    for i, tex_id in enumerate(selected_textures):
        ax = axes[i + 2]
        tex_label = TEXTURE_LIBRARY[tex_id][0]
        z_map = heightmaps[tex_id]
        shaded = ls.hillshade(z_map, vert_exag=2.0, dx=dx, dy=dy)
        ax.imshow(shaded, cmap="gray", origin="upper")
        ax.set_title(f"Rampa TAMP-OS ({ramp_height_mm}mm) + Textura Modulada ({texture_relief_mm}mm): {tex_label} (`{tex_id}`)", fontsize=11, fontweight="bold")
        ax.axis("off")

    preview_path = ex_dir / f"preview_{output_prefix}.png"
    plt.savefig(preview_path, dpi=200)
    plt.close()
    print(f"  [OK] Preview guardado: {preview_path.name}")
    return preview_path


if __name__ == "__main__":
    base = Path(__file__).parent / "examples"

    # Ejemplo 1: Gradiente de Li (Inferno)
    img1 = str(base / "input_li_gradient.png")
    process_example(
        img1,
        output_prefix="ejemplo1_li_inferno",
        colormap_method="inferno",
        physical_width_mm=100.0,
        ramp_height_mm=1.8,
        texture_relief_mm=0.6,
        selected_textures=["dots", "lines_x", "waves", "crosshatch"]
    )

    # Ejemplo 2: Mapa cromático 2D (Eje cromático continuo SVD)
    img2 = str(base / "input_2d_spectrum.png")
    process_example(
        img2,
        output_prefix="ejemplo2_espectro_2d",
        colormap_method="svd",
        physical_width_mm=100.0,
        ramp_height_mm=1.8,
        texture_relief_mm=0.6,
        selected_textures=["dots", "lines_x", "scales", "honeycomb"]
    )

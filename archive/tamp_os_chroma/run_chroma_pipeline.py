"""
TAMP-OS-Chroma: Pipeline Maestro y Generador de Ejemplos
--------------------------------------------------------
Ejecuta los 3 intentos de traducción de gradiente de color/Li a relieve táctil:
  - Intento 1A: Modulación continua de densidad de puntos (Idea original del usuario)
  - Intento 1B: Modulación continua de frecuencia de estrías
  - Intento 2:  Zonas categóricas discretas (5 bandas con texturas BANA + leyenda)
  - Intento 3:  Rampa continua híbrida (elevación + rugosidad + curvas de nivel)

Genera los archivos .STL imprimibles y visualizaciones comparativas 2D con
sombreado rasante (simulación háptica de relieve).
"""

import os
import sys
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import LightSource
from PIL import Image

# Importar módulos locales de TAMP-OS-Chroma
sys.path.insert(0, str(Path(__file__).parent))
from chroma_mapper import extract_concentration_map
from texture_engine import (
    generate_density_dots,
    generate_frequency_grooves,
    generate_discrete_categorical_zones,
    generate_hybrid_ramp_roughness
)
from stl_builder import heightmap_to_stl, generate_tactile_legend_stl


def render_hillshade(
    heightmap: np.ndarray,
    dx: float,
    dy: float,
    azdeg: float = 315.0,
    altdeg: float = 35.0
) -> np.ndarray:
    """
    Simula iluminación rasante (grazing light / hillshading) sobre el mapa de altura
    para visualizar cómo se perciben las sombras y el relieve táctil al tocar la pieza.
    """
    ls = LightSource(azdeg=azdeg, altdeg=altdeg)
    shaded = ls.hillshade(heightmap, vert_exag=2.0, dx=dx, dy=dy)
    return shaded


def run_pipeline(
    image_path: str,
    output_dir: str,
    physical_size_mm: tuple = (100.0, 56.25),
    base_thickness_mm: float = 1.2,
    grid_resolution: tuple = (400, 225)  # Buena resolución de muestreo (dx ~0.25 mm)
):
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("TAMP-OS-Chroma: Ejecutando generación de intentos táctiles")
    print(f"Imagen de entrada: {image_path}")
    print(f"Dimensiones físicas: {physical_size_mm[0]} mm x {physical_size_mm[1]} mm")
    print(f"Resolución de malla: {grid_resolution[0]} x {grid_resolution[1]} puntos")
    print("=" * 60)

    # 1. Extraer mapa de concentración escalar [0.0, 1.0]
    print("\n[Paso 1] Decodificando gradiente de color (Colormap Inferno / % Li)...")
    conc_map = extract_concentration_map(
        image_path,
        method="inferno",
        invert=False,
        blur_sigma=1.0,
        target_size=grid_resolution
    )
    print(f"  Rango de concentración detectado: min={conc_map.min():.3f}, max={conc_map.max():.3f}")

    # Variante invertida para probar la polaridad
    conc_map_inv = 1.0 - conc_map

    dx = physical_size_mm[0] / (grid_resolution[0] - 1)
    dy = physical_size_mm[1] / (grid_resolution[1] - 1)

    # 2. Generar Intento 1A: Modulación continua de densidad de puntos (Normal e Invertido)
    print("\n[Paso 2] Generando Intento 1A: Modulación continua de densidad de puntos...")
    hm_dots = generate_density_dots(
        conc_map,
        physical_size_mm=physical_size_mm,
        min_spacing_mm=1.8,
        max_spacing_mm=4.8,
        max_dot_relief_mm=0.8
    )
    stl_dots = out_path / "intento1_density_dots.stl"
    heightmap_to_stl(hm_dots, str(stl_dots), physical_size_mm, base_thickness_mm)
    print(f"  [OK] Guardado STL: {stl_dots.name}")

    hm_dots_inv = generate_density_dots(
        conc_map_inv,
        physical_size_mm=physical_size_mm,
        min_spacing_mm=1.8,
        max_spacing_mm=4.8,
        max_dot_relief_mm=0.8
    )
    stl_dots_inv = out_path / "intento1_density_dots_inverted.stl"
    heightmap_to_stl(hm_dots_inv, str(stl_dots_inv), physical_size_mm, base_thickness_mm)
    print(f"  [OK] Guardado STL invertido: {stl_dots_inv.name}")

    # 3. Generar Intento 1B: Modulación continua de frecuencia de estrías
    print("\n[Paso 3] Generando Intento 1B: Modulación continua de frecuencia de estrías...")
    hm_lines = generate_frequency_grooves(
        conc_map,
        physical_size_mm=physical_size_mm,
        min_period_mm=1.3,
        max_period_mm=4.2,
        max_relief_mm=0.8
    )
    stl_lines = out_path / "intento1_density_lines.stl"
    heightmap_to_stl(hm_lines, str(stl_lines), physical_size_mm, base_thickness_mm)
    print(f"  [OK] Guardado STL: {stl_lines.name}")

    # 4. Generar Intento 2: Zonas discretas con texturas diferenciadas + Leyenda
    print("\n[Paso 4] Generando Intento 2: Zonas categóricas (5 bandas) + Leyenda táctil...")
    hm_zones, zone_indices = generate_discrete_categorical_zones(
        conc_map,
        physical_size_mm=physical_size_mm,
        num_zones=5,
        max_relief_mm=0.8,
        add_step_elevation=False,
        boundary_relief_mm=0.5
    )
    stl_zones = out_path / "intento2_zones_textures.stl"
    heightmap_to_stl(hm_zones, str(stl_zones), physical_size_mm, base_thickness_mm)
    print(f"  [OK] Guardado STL: {stl_zones.name}")

    # Tarjeta de leyenda complementaria
    stl_legend = out_path / "intento2_tactile_legend.stl"
    generate_tactile_legend_stl(
        str(stl_legend),
        num_zones=5,
        swatch_size_mm=(14.0, 18.0),
        base_thickness_mm=base_thickness_mm,
        max_relief_mm=0.8
    )
    print(f"  [OK] Guardada Leyenda STL: {stl_legend.name}")

    # 5. Generar Intento 3: Rampa híbrida (elevación macro + rugosidad modulada + curvas de nivel)
    print("\n[Paso 5] Generando Intento 3: Rampa continua híbrida con rugosidad modulada...")
    hm_hybrid = generate_hybrid_ramp_roughness(
        conc_map,
        physical_size_mm=physical_size_mm,
        ramp_relief_mm=1.8,
        texture_relief_mm=0.6,
        num_contour_lines=5
    )
    stl_hybrid = out_path / "intento3_hybrid_ramp.stl"
    heightmap_to_stl(hm_hybrid, str(stl_hybrid), physical_size_mm, base_thickness_mm)
    print(f"  [OK] Guardado STL: {stl_hybrid.name}")

    # 6. Generar Gráficas Comparativas de Sombreado Rasante (Simulación Táctil)
    print("\n[Paso 6] Generando figuras de visualización comparativa...")
    fig, axes = plt.subplots(5, 1, figsize=(10, 12), constrained_layout=True)

    input_img = Image.open(image_path).convert("RGB")
    axes[0].imshow(input_img)
    axes[0].set_title("Original: Muestra con Gradiente de Color (% de Litio)", fontsize=11, fontweight="bold")
    axes[0].axis("off")

    shade_dots = render_hillshade(hm_dots, dx, dy)
    axes[1].imshow(shade_dots, cmap="gray", origin="upper")
    axes[1].set_title("Intento 1A: Modulación de Densidad de Puntos (Idea Original)", fontsize=11, fontweight="bold")
    axes[1].axis("off")

    shade_lines = render_hillshade(hm_lines, dx, dy)
    axes[2].imshow(shade_lines, cmap="gray", origin="upper")
    axes[2].set_title("Intento 1B: Modulación de Frecuencia de Estrías Lineales", fontsize=11, fontweight="bold")
    axes[2].axis("off")

    shade_zones = render_hillshade(hm_zones, dx, dy)
    axes[3].imshow(shade_zones, cmap="gray", origin="upper")
    axes[3].set_title("Intento 2: 5 Zonas Categóricas con Texturas Diferenciadas (BANA)", fontsize=11, fontweight="bold")
    axes[3].axis("off")

    shade_hybrid = render_hillshade(hm_hybrid, dx, dy)
    axes[4].imshow(shade_hybrid, cmap="gray", origin="upper")
    axes[4].set_title("Intento 3: Rampa Continua Híbrida + Rugosidad Modulada + Curvas de Nivel", fontsize=11, fontweight="bold")
    axes[4].axis("off")

    preview_img_path = out_path / "preview_comparativa.png"
    plt.savefig(preview_img_path, dpi=200)
    plt.close()
    print(f"  [OK] Guardada figura de sombreado: {preview_img_path.name}")

    # 7. Gráfica de Perfiles Transversales de Elevación (Z vs X en mm)
    fig, ax = plt.subplots(figsize=(10, 4.5), constrained_layout=True)
    x_mm = np.linspace(0, physical_size_mm[0], grid_resolution[0])
    mid_row = grid_resolution[1] // 2

    ax.plot(x_mm, base_thickness_mm + hm_dots[mid_row, :], label="Intento 1A: Puntos (Densidad)", color="#1f77b4", lw=1.5)
    ax.plot(x_mm, base_thickness_mm + hm_lines[mid_row, :], label="Intento 1B: Estrías (Frecuencia)", color="#ff7f0e", lw=1.2, alpha=0.8)
    ax.plot(x_mm, base_thickness_mm + hm_zones[mid_row, :], label="Intento 2: Zonas Categóricas", color="#2ca02c", lw=1.5)
    ax.plot(x_mm, base_thickness_mm + hm_hybrid[mid_row, :], label="Intento 3: Rampa Híbrida", color="#d62728", lw=1.5)

    ax.axhline(base_thickness_mm, color="gray", linestyle="--", label=f"Base sólida ({base_thickness_mm} mm)")
    ax.set_xlabel("Posición X a lo largo de la muestra (mm)", fontsize=10, fontweight="bold")
    ax.set_ylabel("Altura total Z (mm)", fontsize=10, fontweight="bold")
    ax.set_title("Perfiles Transversales de Altura Z (Corte por el Centro de la Muestra)", fontsize=11, fontweight="bold")
    ax.grid(True, linestyle=":", alpha=0.6)
    ax.legend(loc="upper left", frameon=True)

    profile_img_path = out_path / "preview_profiles.png"
    plt.savefig(profile_img_path, dpi=200)
    plt.close()
    print(f"  [OK] Guardada figura de perfiles: {profile_img_path.name}")

    print("\n" + "=" * 60)
    print("¡Generación completada con éxito!")
    print(f"Todos los archivos listos en: {out_path.resolve()}")
    print("=" * 60)


if __name__ == "__main__":
    base_dir = Path(__file__).parent
    input_sample = base_dir / "examples" / "input_li_gradient.png"
    examples_dir = base_dir / "examples"
    run_pipeline(str(input_sample), str(examples_dir))

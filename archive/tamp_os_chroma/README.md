# TAMP-OS-Chroma: Chromatic Tactile Texture Mapping for TAMP-OS

**TAMP-OS-Chroma** es una extensión y módulo spin-off de **TAMP-OS** diseñado para convertir imágenes donde **el color representa una propiedad física o química** (por ejemplo, concentración de litio % Li en electrodos de $\text{Li}_x\text{Mn}_2\text{O}_4$ medidos por microscopía óptica operando, mapeos químicos EDS/SIMS, espectroscopía Raman o mapas de calor con colormaps científicos) en **litografías táctiles 3D perceptibles al tacto**.

---

## 🔬 La Esencia de TAMP-OS: Rampa Continua + Textura Modulada

En lugar de crear zonas discretas artificiales que generan saltos abruptos, **TAMP-OS-Chroma preserva la rampa continua de TAMP-OS** y le superpone una **textura táctil elegida por el usuario** cuya densidad espacial se modula con el valor:

$$\large Z_{\text{total}}(x, y) = \text{Espesor}_{\text{base}} + Z_{\text{rampa}}(x, y) + Z_{\text{textura}}(x, y)$$

1. **Retroalimentación Cinestésica (Macro-relieve):** La rampa suave $Z_{\text{rampa}}(x, y)$ permite a la mano sentir la inclinación general y la dirección del gradiente.
2. **Retroalimentación Cutánea (Micro-textura):** La textura $Z_{\text{textura}}(x, y)$ se satura (puntos más juntos, estrías más apretadas) a medida que aumenta la concentración, confirmando con exactitud el nivel local al pasar el pulpejo del dedo.
3. **Polaridad invertible:** Permite configurar si mayor valor = más textura o más liso (análogo a blanco = highest o lowest en TAMP-OS).

---

## 📚 Biblioteca de Texturas Táctiles Disponibles

El módulo incluye **8 patrones táctiles procedurales** diseñados para boquillas FDM de 0.4 mm y el umbral de discriminación del pulpejo del dedo ($\ge 1.2 - 1.5\text{ mm}$):

| Identificador | Nombre | Descripción Háptica |
|---|---|---|
| `dots` | Puntos Táctiles (Stippling) | Cúpulas suaves que pasan de muy dispersas ($\sim 4.8\text{ mm}$) a densas y prominentes ($\sim 1.8\text{ mm}$). |
| `lines_x` | Estrías Lineales Verticales | Ranuras que se comprimen en frecuencia espacial hacia la zona saturada. |
| `lines_y` | Estrías Lineales Horizontales | Estrías a lo largo de X con compresión de frecuencia en Y. |
| `diagonal_45` | Estrías Diagonales a 45° | Crestas inclinadas para exploración táctil angular. |
| `crosshatch` | Cuadrícula / Malla Ortogonal | Rejilla cruzada que pasa de celdas amplias a una matriz fina y compacta. |
| `waves` | Ondulaciones Sinusoidales | Ondas fluidas con longitud de onda continuamente decreciente. |
| `honeycomb` | Panal Hexagonal (Knurling) | Celdas hexagonales tipo moleteado mecánico. |
| `scales` | Escamas Semicirculares | Patrón semicircular imbricado que gana profundidad y relieve. |

*(Consulta el catálogo visual generado en `examples/texture_library_catalog.png`)*.

---

## 📁 Archivos y Modelos STL Generados

En la subcarpeta [`examples/`](examples/):

### Ejemplo 1: Gradiente de Litio (% Li en LMO / Colormap Inferno)
- [`input_li_gradient.png`](examples/input_li_gradient.png): Muestra del paper de microscopía operando.
- [`ejemplo1_li_inferno_rampa_dots.stl`](examples/ejemplo1_li_inferno_rampa_dots.stl): Rampa TAMP-OS + Puntos táctiles.
- [`ejemplo1_li_inferno_rampa_lines_x.stl`](examples/ejemplo1_li_inferno_rampa_lines_x.stl): Rampa TAMP-OS + Estrías lineales.
- [`ejemplo1_li_inferno_rampa_waves.stl`](examples/ejemplo1_li_inferno_rampa_waves.stl): Rampa TAMP-OS + Ondas sinusoidales.
- [`ejemplo1_li_inferno_rampa_crosshatch.stl`](examples/ejemplo1_li_inferno_rampa_crosshatch.stl): Rampa TAMP-OS + Cuadrícula.

### Ejemplo 2: Mapa Cromático Bidimensional Multicolor
- [`input_2d_spectrum.png`](examples/input_2d_spectrum.png): Muestra 2D con gradiente espectral continuo (Rojo $\rightarrow$ Amarillo $\rightarrow$ Verde $\rightarrow$ Azul $\rightarrow$ Púrpura).
- [`ejemplo2_espectro_2d_rampa_dots.stl`](examples/ejemplo2_espectro_2d_rampa_dots.stl): Rampa 2D SVD + Puntos táctiles.
- [`ejemplo2_espectro_2d_rampa_lines_x.stl`](examples/ejemplo2_espectro_2d_rampa_lines_x.stl): Rampa 2D SVD + Estrías lineales.
- [`ejemplo2_espectro_2d_rampa_scales.stl`](examples/ejemplo2_espectro_2d_rampa_scales.stl): Rampa 2D SVD + Escamas.
- [`ejemplo2_espectro_2d_rampa_honeycomb.stl`](examples/ejemplo2_espectro_2d_rampa_honeycomb.stl): Rampa 2D SVD + Panal hexagonal.

---

## 🚀 Uso Rápido en Python / Notebook

### En el Cuaderno Interactivo:
Abre `tamp_os_chroma_notebook.ipynb` en Jupyter Lab o VS Code, selecciona la imagen, la textura deseada y exporta tu STL.

### Por Script de Consola:
```python
from tamp_os_chroma.run_examples_suite import process_example

process_example(
    image_path="ruta/a/tu_imagen.png",
    output_prefix="mi_muestra",
    colormap_method="inferno",    # 'inferno', 'viridis', 'svd', 'turbo', 'luminance'
    physical_width_mm=100.0,
    ramp_height_mm=1.8,
    texture_relief_mm=0.6,
    selected_textures=["dots", "lines_x", "waves"]
)
```

---

## 🖨️ Parámetros Recomendados de Impresión 3D FDM

- **Boquilla (Nozzle):** 0.4 mm.
- **Altura de capa:** 0.16 mm o 0.20 mm.
- **Relleno (Infill):** 15% – 20% Giroide o Cuadrícula.
- **Capas superiores sólidas:** Al menos 4 o 5 capas sólidas para garantizar que las texturas queden suaves y selladas sin agujeros.
- **Material:** PLA estándar o PETG.

"""
TAMP-OS-Chroma: Native Desktop GUI
----------------------------------
Interactive desktop interface for TAMP-OS-Chroma built with Tkinter,
matching the native architecture and usability of TAMP-OS batch GUI.

Features:
  - Image loading & color decoding (Inferno, Viridis, SVD Chromatic, Turbo, Luminance)
  - Polarity invert toggle (White/Max color = Highest vs Lowest)
  - TAMP-OS macroscopic ramp height slider
  - Visual Texture Library selector (Dots, Lines, Diagonal, Crosshatch, Waves, Honeycomb, Scales)
  - Texture relief slider
  - Live 2D simulated tactile relief preview (Hillshading with grazing light)
  - One-click watertight STL generation and export
"""

import sys
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import numpy as np
from PIL import Image, ImageTk
from matplotlib.colors import LightSource

# Importar motores locales
sys.path.insert(0, str(Path(__file__).parent))
from chroma_mapper import extract_concentration_map
from texture_engine import TEXTURE_LIBRARY, generate_textured_ramp
from stl_builder import heightmap_to_stl


class TampChromaGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("TAMP-OS Chroma — Tactile Colormap & Texture Lithograph Maker")
        self.root.geometry("1020x760")
        self.root.minsize(900, 680)

        # Variables de estado
        default_img = Path(__file__).parent / "examples" / "input_li_gradient.png"
        self.image_path_var = tk.StringVar(value=str(default_img) if default_img.exists() else "")
        self.colormap_var = tk.StringVar(value="inferno")
        self.invert_var = tk.BooleanVar(value=False)
        self.texture_var = tk.StringVar(value="dots")
        self.print_width_var = tk.DoubleVar(value=100.0)
        self.base_thickness_var = tk.DoubleVar(value=1.2)
        self.ramp_height_var = tk.DoubleVar(value=1.8)
        self.texture_relief_var = tk.DoubleVar(value=0.6)
        self.output_dir_var = tk.StringVar(value=str(Path(__file__).parent / "examples"))

        self.current_scalar_map = None
        self.current_heightmap = None
        self.preview_tk_img = None

        self._build_ui()
        self._load_and_update()

    def _build_ui(self):
        # Contenedor principal con panel izquierdo (controles) y derecho (preview)
        main_paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Panel izquierdo: Controles (con scroll)
        left_frame = ttk.Frame(main_paned, width=420)
        main_paned.add(left_frame, weight=1)

        # Panel derecho: Live Preview y Exportación
        right_frame = ttk.Frame(main_paned, width=560)
        main_paned.add(right_frame, weight=2)

        # ===================================================================
        # PANEL IZQUIERDO: CONTROLES
        # ===================================================================
        row = 0
        title_lbl = tk.Label(left_frame, text="TAMP-OS Chroma", font=("Helvetica", 16, "bold"), fg="#b83b1d")
        title_lbl.grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 2))
        row += 1
        sub_lbl = tk.Label(left_frame, text="Rampa Continua + Texturas Táctiles Moduladas", font=("Helvetica", 9), fg="gray")
        sub_lbl.grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 10))
        row += 1

        # 1. Cargar Imagen
        img_box = ttk.LabelFrame(left_frame, text=" 1. Imagen de Entrada ", padding=8)
        img_box.grid(row=row, column=0, columnspan=2, sticky="ew", pady=5)
        row += 1

        img_path_entry = ttk.Entry(img_box, textvariable=self.image_path_var, width=32)
        img_path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        browse_btn = ttk.Button(img_box, text="Examinar...", command=self._browse_image)
        browse_btn.pack(side=tk.RIGHT)

        # 2. Decodificación de Color
        color_box = ttk.LabelFrame(left_frame, text=" 2. Decodificación de Color (% Propiedad) ", padding=8)
        color_box.grid(row=row, column=0, columnspan=2, sticky="ew", pady=5)
        row += 1

        ttk.Label(color_box, text="Método de Mapeo:").grid(row=0, column=0, sticky="w", pady=2)
        cmaps = ["inferno", "viridis", "svd", "turbo", "luminance"]
        cmap_menu = ttk.OptionMenu(color_box, self.colormap_var, self.colormap_var.get(), *cmaps, command=lambda _: self._load_and_update())
        cmap_menu.grid(row=0, column=1, sticky="ew", pady=2)

        inv_check = ttk.Checkbutton(
            color_box,
            text="Invertir polaridad (Color máx = zona más lisa)",
            variable=self.invert_var,
            command=self._load_and_update
        )
        inv_check.grid(row=1, column=0, columnspan=2, sticky="w", pady=4)

        # 3. Rampa TAMP-OS (Macro-Relieve)
        ramp_box = ttk.LabelFrame(left_frame, text=" 3. Rampa TAMP-OS (Macro-Relieve) ", padding=8)
        ramp_box.grid(row=row, column=0, columnspan=2, sticky="ew", pady=5)
        row += 1

        ttk.Label(ramp_box, text="Altura de Rampa:").grid(row=0, column=0, sticky="w")
        self.ramp_val_lbl = ttk.Label(ramp_box, text=f"{self.ramp_height_var.get():.1f} mm")
        self.ramp_val_lbl.grid(row=0, column=2, sticky="e")
        ramp_scale = ttk.Scale(
            ramp_box, from_=0.5, to=4.0, variable=self.ramp_height_var,
            command=lambda v: self._on_ramp_slider(v)
        )
        ramp_scale.grid(row=0, column=1, sticky="ew", padx=6, pady=4)

        ttk.Label(ramp_box, text="Espesor de Base:").grid(row=1, column=0, sticky="w")
        base_spin = ttk.Spinbox(ramp_box, from_=0.8, to=3.0, increment=0.2, textvariable=self.base_thickness_var, width=6)
        base_spin.grid(row=1, column=1, sticky="w", padx=6, pady=2)
        ttk.Label(ramp_box, text="mm").grid(row=1, column=2, sticky="w")

        # 4. Biblioteca de Texturas Táctiles (Micro-Relieve)
        tex_box = ttk.LabelFrame(left_frame, text=" 4. Biblioteca de Texturas Táctiles ", padding=8)
        tex_box.grid(row=row, column=0, columnspan=2, sticky="ew", pady=5)
        row += 1

        ttk.Label(tex_box, text="Textura:").grid(row=0, column=0, sticky="w", pady=2)
        tex_keys = list(TEXTURE_LIBRARY.keys())
        tex_menu = ttk.OptionMenu(tex_box, self.texture_var, self.texture_var.get(), *tex_keys, command=lambda _: self._update_preview())
        tex_menu.grid(row=0, column=1, sticky="ew", pady=2)

        ttk.Label(tex_box, text="Relieve Textura:").grid(row=1, column=0, sticky="w")
        self.tex_val_lbl = ttk.Label(tex_box, text=f"{self.texture_relief_var.get():.1f} mm")
        self.tex_val_lbl.grid(row=1, column=2, sticky="e")
        tex_scale = ttk.Scale(
            tex_box, from_=0.2, to=1.5, variable=self.texture_relief_var,
            command=lambda v: self._on_tex_slider(v)
        )
        tex_scale.grid(row=1, column=1, sticky="ew", padx=6, pady=4)

        # 5. Exportar STL
        exp_box = ttk.LabelFrame(left_frame, text=" 5. Exportación 3D ", padding=8)
        exp_box.grid(row=row, column=0, columnspan=2, sticky="ew", pady=5)
        row += 1

        ttk.Label(exp_box, text="Carpeta de Salida:").pack(anchor="w")
        out_f = ttk.Frame(exp_box)
        out_f.pack(fill=tk.X, pady=2)
        ttk.Entry(out_f, textvariable=self.output_dir_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        ttk.Button(out_f, text="...", width=3, command=self._browse_output).pack(side=tk.RIGHT)

        export_btn = tk.Button(
            left_frame,
            text="✨ Generar Litografía Táctil (STL)",
            font=("Helvetica", 11, "bold"),
            bg="#b83b1d",
            fg="white",
            activebackground="#962e15",
            activeforeground="white",
            relief=tk.RAISED,
            pady=8,
            command=self._generate_stl
        )
        export_btn.grid(row=row, column=0, columnspan=2, sticky="ew", pady=12)

        # ===================================================================
        # PANEL DERECHO: LIVE PREVIEWS
        # ===================================================================
        preview_frame = ttk.LabelFrame(right_frame, text=" Simulación Háptica en Vivo (Luz Rasante) ", padding=10)
        preview_frame.pack(fill=tk.BOTH, expand=True)

        self.preview_canvas = tk.Label(preview_frame, bg="#202020", text="Cargando vista previa...")
        self.preview_canvas.pack(fill=tk.BOTH, expand=True)

        self.status_lbl = ttk.Label(right_frame, text="Listo.", foreground="gray")
        self.status_lbl.pack(anchor="w", pady=(4, 0))

    def _on_ramp_slider(self, val):
        self.ramp_val_lbl.config(text=f"{float(val):.1f} mm")
        self._update_preview()

    def _on_tex_slider(self, val):
        self.tex_val_lbl.config(text=f"{float(val):.1f} mm")
        self._update_preview()

    def _browse_image(self):
        f = filedialog.askopenfilename(
            title="Seleccionar Imagen Científica",
            filetypes=[("Imágenes", "*.png *.jpg *.jpeg *.tif *.tiff *.bmp"), ("Todos los archivos", "*.*")]
        )
        if f:
            self.image_path_var.set(f)
            self._load_and_update()

    def _browse_output(self):
        d = filedialog.askdirectory(title="Seleccionar Carpeta de Destino")
        if d:
            self.output_dir_var.set(d)

    def _load_and_update(self):
        img_path = self.image_path_var.get()
        if not img_path or not Path(img_path).exists():
            return

        try:
            self.status_lbl.config(text="Decodificando mapa de color...")
            self.root.update_idletasks()
            # Muestreo para preview rápido (240x135)
            self.current_scalar_map = extract_concentration_map(
                img_path,
                method=self.colormap_var.get(),
                invert=self.invert_var.get(),
                blur_sigma=1.0,
                target_size=(260, 150)
            )
            self._update_preview()
            self.status_lbl.config(text="Mapa decodificado. Vista previa actualizada.")
        except Exception as e:
            messagebox.showerror("Error", f"Error cargando imagen:\n{e}")
            self.status_lbl.config(text="Error.")

    def _update_preview(self):
        if self.current_scalar_map is None:
            return

        scalar = self.current_scalar_map
        tex_name = self.texture_var.get()
        ramp_h = self.ramp_height_var.get()
        tex_h = self.texture_relief_var.get()

        # Generar rampa combinada
        z_map = generate_textured_ramp(
            scalar,
            texture_name=tex_name,
            physical_size_mm=(100.0, 57.7),
            ramp_height_mm=ramp_h,
            texture_relief_mm=tex_h
        )
        self.current_heightmap = z_map

        # Simular sombreado con luz rasante
        ls = LightSource(azdeg=315, altdeg=35)
        shaded = ls.hillshade(z_map, vert_exag=2.5, dx=0.38, dy=0.38)
        shaded_uint8 = (shaded * 255).astype(np.uint8)

        # Redimensionar al tamaño del canvas
        pil_shaded = Image.fromarray(shaded_uint8)
        # Mostrar a buen tamaño
        pil_shaded = pil_shaded.resize((500, 290), Image.BILINEAR)

        self.preview_tk_img = ImageTk.PhotoImage(pil_shaded)
        self.preview_canvas.config(image=self.preview_tk_img, text="")

    def _generate_stl(self):
        img_path = self.image_path_var.get()
        if not img_path or not Path(img_path).exists():
            messagebox.showwarning("Aviso", "Por favor selecciona una imagen válida.")
            return

        out_dir = Path(self.output_dir_var.get())
        out_dir.mkdir(parents=True, exist_ok=True)

        img_stem = Path(img_path).stem
        tex_name = self.texture_var.get()
        out_stl = out_dir / f"{img_stem}_rampa_{tex_name}.stl"

        try:
            self.status_lbl.config(text="Generando malla STL de alta resolución...")
            self.root.update_idletasks()

            # Malla completa de producción (400 columnas)
            pil_img = Image.open(img_path)
            aspect = pil_img.height / pil_img.width
            w_mm = self.print_width_var.get()
            h_mm = round(w_mm * aspect, 2)
            grid_res = (400, int(400 * aspect))

            hires_scalar = extract_concentration_map(
                img_path,
                method=self.colormap_var.get(),
                invert=self.invert_var.get(),
                blur_sigma=1.0,
                target_size=grid_res
            )
            hires_z = generate_textured_ramp(
                hires_scalar,
                texture_name=tex_name,
                physical_size_mm=(w_mm, h_mm),
                ramp_height_mm=self.ramp_height_var.get(),
                texture_relief_mm=self.texture_relief_var.get()
            )
            heightmap_to_stl(
                hires_z,
                str(out_stl),
                physical_size_mm=(w_mm, h_mm),
                base_thickness_mm=self.base_thickness_var.get()
            )

            self.status_lbl.config(text=f"¡STL generado con éxito: {out_stl.name}!")
            messagebox.showinfo("Éxito", f"Litografía táctil generada correctamente:\n\n{out_stl.resolve()}\n\nDimensiones: {w_mm} x {h_mm} mm\nLista para abrir en tu slicer.")
        except Exception as e:
            messagebox.showerror("Error", f"Fallo al generar el archivo STL:\n{e}")
            self.status_lbl.config(text="Error generando STL.")


def main():
    root = tk.Tk()
    app = TampChromaGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()

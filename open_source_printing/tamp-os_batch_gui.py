#!/usr/bin/env python3
"""
TAMP-OS Batch GUI
=================
Select multiple microscopy images at once and convert them all
to STL lithographs with a single click.

Usage:
    python tamp_batch_gui.py

Dependencies (same as tamp_litho.py):
    pip install numpy pillow scipy numpy-stl
"""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path
import threading
import sys
import os

# Import pipeline functions from tamp_litho.py in the same folder
sys.path.insert(0, str(Path(__file__).parent))
from tamp_litho import image_to_heightmap, heightmap_to_stl


# ─────────────────────────────────────────────
#  Main App
# ─────────────────────────────────────────────

class TAMPBatchGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("TAMP-OS Batch Lithograph Maker")
        self.root.resizable(False, False)

        self.image_paths = []
        self.running = False

        self._build_ui()

    def _build_ui(self):
        pad = dict(padx=10, pady=5)

        # ── Title ────────────────────────────────────────────────────────────
        title = tk.Label(self.root, text="TAMP-OS Batch Lithograph Maker",
                         font=("Helvetica", 14, "bold"))
        title.grid(row=0, column=0, columnspan=3, pady=(14, 2))

        subtitle = tk.Label(self.root,
                            text="Select microscopy images and convert them all to STL in one go.",
                            font=("Helvetica", 9), fg="gray")
        subtitle.grid(row=1, column=0, columnspan=3, pady=(0, 10))

        # ── Image selection ──────────────────────────────────────────────────
        tk.Label(self.root, text="Images:", font=("Helvetica", 10, "bold")).grid(
            row=2, column=0, sticky="nw", **pad)

        frame_list = tk.Frame(self.root)
        frame_list.grid(row=2, column=1, columnspan=2, **pad)

        scrollbar = tk.Scrollbar(frame_list, orient=tk.VERTICAL)
        self.listbox = tk.Listbox(frame_list, width=50, height=6,
                                  yscrollcommand=scrollbar.set, selectmode=tk.EXTENDED)
        scrollbar.config(command=self.listbox.yview)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        btn_frame = tk.Frame(self.root)
        btn_frame.grid(row=3, column=1, columnspan=2, sticky="w", padx=10)
        tk.Button(btn_frame, text="+ Add Images", command=self._add_images, width=14).pack(side=tk.LEFT, padx=(0,5))
        tk.Button(btn_frame, text="− Remove Selected", command=self._remove_selected, width=14).pack(side=tk.LEFT)

        # ── Output folder ────────────────────────────────────────────────────
        tk.Label(self.root, text="Output folder:", font=("Helvetica", 10, "bold")).grid(
            row=4, column=0, sticky="w", **pad)

        self.output_var = tk.StringVar(value=str(Path.home() / "TAMP_output"))
        tk.Entry(self.root, textvariable=self.output_var, width=38).grid(
            row=4, column=1, sticky="w", **pad)
        tk.Button(self.root, text="Browse", command=self._browse_output).grid(
            row=4, column=2, sticky="w", padx=(0,10))

        # ── Parameters ───────────────────────────────────────────────────────
        sep = ttk.Separator(self.root, orient="horizontal")
        sep.grid(row=5, column=0, columnspan=3, sticky="ew", padx=10, pady=6)

        tk.Label(self.root, text="Parameters", font=("Helvetica", 11, "bold")).grid(
            row=6, column=0, columnspan=3, pady=(0,4))

        params = [
            ("Print width (mm)",     "size_x",        "100"),
            ("Print height (mm)",    "size_y",        "75",
             "⚠  Match your image aspect ratio, e.g. 75 for a 4:3 image"),
            ("Relief height (mm)",   "relief_height", "3.0",
             "Max tactile height difference. Try 3.0 for a first print."),
            ("Base thickness (mm)",  "base_thickness","1.0"),
            ("Blur (sigma)",         "blur",          "1.2",
             "Gaussian smoothing. Increase for noisy images."),
            ("Resolution (px)",      "resolution",    "512",
             "Height map resolution. 256 = smaller file, 512 = more detail."),
        ]

        self.param_vars = {}
        for i, item in enumerate(params):
            label, key, default = item[0], item[1], item[2]
            hint = item[3] if len(item) > 3 else None

            tk.Label(self.root, text=label + ":").grid(
                row=7+i, column=0, sticky="w", padx=10, pady=2)
            var = tk.StringVar(value=default)
            self.param_vars[key] = var
            tk.Entry(self.root, textvariable=var, width=10).grid(
                row=7+i, column=1, sticky="w", padx=10, pady=2)
            if hint:
                tk.Label(self.root, text=hint, fg="gray", font=("Helvetica", 8)).grid(
                    row=7+i, column=2, sticky="w", padx=(0,10), pady=2)

        # Checkboxes
        chk_row = 7 + len(params)
        self.invert_var = tk.BooleanVar(value=False)
        self.flip_var   = tk.BooleanVar(value=True)

        tk.Checkbutton(self.root, text="Invert relief (dark areas raised)",
                       variable=self.invert_var).grid(
            row=chk_row, column=0, columnspan=2, sticky="w", padx=10, pady=2)
        tk.Checkbutton(self.root, text="Flip vertically (recommended — matches image orientation)",
                       variable=self.flip_var).grid(
            row=chk_row+1, column=0, columnspan=3, sticky="w", padx=10, pady=2)

        # ── Progress ─────────────────────────────────────────────────────────
        sep2 = ttk.Separator(self.root, orient="horizontal")
        sep2.grid(row=chk_row+2, column=0, columnspan=3, sticky="ew", padx=10, pady=6)

        self.progress = ttk.Progressbar(self.root, orient=tk.HORIZONTAL,
                                        length=420, mode="determinate")
        self.progress.grid(row=chk_row+3, column=0, columnspan=3, padx=10, pady=4)

        self.status_var = tk.StringVar(value="Ready.")
        tk.Label(self.root, textvariable=self.status_var, fg="gray",
                 font=("Helvetica", 9)).grid(
            row=chk_row+4, column=0, columnspan=3, pady=(0,4))

        # ── Run button ───────────────────────────────────────────────────────
        self.run_btn = tk.Button(self.root, text="▶  Generate STLs",
                                 font=("Helvetica", 11, "bold"),
                                 bg="#2a7ae2", fg="white",
                                 activebackground="#1a5fbf", activeforeground="white",
                                 command=self._run, width=20, height=2)
        self.run_btn.grid(row=chk_row+5, column=0, columnspan=3, pady=(4, 14))

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _add_images(self):
        files = filedialog.askopenfilenames(
            title="Select microscopy images",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.tif *.tiff *.bmp"),
                       ("All files", "*.*")]
        )
        for f in files:
            if f not in self.image_paths:
                self.image_paths.append(f)
                self.listbox.insert(tk.END, Path(f).name)

    def _remove_selected(self):
        selected = list(self.listbox.curselection())
        for i in reversed(selected):
            self.listbox.delete(i)
            self.image_paths.pop(i)

    def _browse_output(self):
        folder = filedialog.askdirectory(title="Select output folder")
        if folder:
            self.output_var.set(folder)

    def _get_params(self):
        try:
            return {
                "size_x":         float(self.param_vars["size_x"].get()),
                "size_y":         float(self.param_vars["size_y"].get()),
                "relief_height":  float(self.param_vars["relief_height"].get()),
                "base_thickness": float(self.param_vars["base_thickness"].get()),
                "blur":           float(self.param_vars["blur"].get()),
                "resolution":     int(self.param_vars["resolution"].get()),
                "invert":         self.invert_var.get(),
                "flip":           self.flip_var.get(),
            }
        except ValueError as e:
            messagebox.showerror("Invalid parameters", f"Please check your parameter values:\n{e}")
            return None

    # ── Pipeline ─────────────────────────────────────────────────────────────

    def _run(self):
        if not self.image_paths:
            messagebox.showwarning("No images", "Please add at least one image.")
            return
        params = self._get_params()
        if params is None:
            return
        if self.running:
            return

        self.running = True
        self.run_btn.config(state=tk.DISABLED)
        thread = threading.Thread(target=self._process_all, args=(params,), daemon=True)
        thread.start()

    def _process_all(self, params):
        output_dir = Path(self.output_var.get())
        output_dir.mkdir(parents=True, exist_ok=True)

        total = len(self.image_paths)
        errors = []

        for i, img_path in enumerate(self.image_paths):
            name = Path(img_path).stem
            self._set_status(f"Processing {i+1}/{total}: {name}...")
            self.progress["value"] = (i / total) * 100
            self.root.update_idletasks()

            try:
                hm = image_to_heightmap(
                    img_path,
                    output_size=(params["resolution"], params["resolution"]),
                    invert=params["invert"],
                    blur_sigma=params["blur"],
                    preserve_aspect=True,
                    flip=params["flip"],
                )
                out_stl = output_dir / f"{name}_lithograph.stl"
                heightmap_to_stl(
                    hm, out_stl,
                    base_thickness_mm=params["base_thickness"],
                    max_relief_mm=params["relief_height"],
                    physical_size_mm=(params["size_x"], params["size_y"]),
                )
            except Exception as e:
                errors.append(f"{name}: {e}")

        self.progress["value"] = 100

        if errors:
            self._set_status(f"Done with {len(errors)} error(s).")
            messagebox.showerror("Errors", "Some files failed:\n\n" + "\n".join(errors))
        else:
            self._set_status(f"Done! {total} STL(s) saved to {output_dir}")
            messagebox.showinfo("Done!",
                                f"Successfully generated {total} STL file(s).\n\nSaved to:\n{output_dir}")

        self.running = False
        self.run_btn.config(state=tk.NORMAL)

    def _set_status(self, msg):
        self.status_var.set(msg)
        self.root.update_idletasks()


# ─────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────

if __name__ == "__main__":
    root = tk.Tk()
    app = TAMPBatchGUI(root)
    root.mainloop()

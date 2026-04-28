# TAMP-OS

**TAMP-OS** is an open-source extension of the [TAMP](https://github.com/Aschulz94/TAMP) (Tactile Accessible Microscopy Printing) workflow. It converts microscopy images into 3D-printed tactile lithographs — making scientific imagery accessible to blind and visually impaired people.

This repo replaces the proprietary Bambu Lab dependency with a fully open-source, scriptable pipeline that works with any FDM printer.

Robert Faulkner, Natalia Gonzalez-Vazquez, Victoria Gamez, Karly E. Cohen, Gunther Richter, Abigale Stangl, Andrew K. Schulz

[![Science paper](https://img.shields.io/badge/Science-Paper-B31B1B.svg)](https://www.science.org/doi/10.1126/science.adx8981)
[![Original TAMP repo](https://img.shields.io/badge/GitHub-TAMP-181717.svg)](https://github.com/Aschulz94/TAMP)

---

## What does it do?

You give it a microscopy image. It gives you a 3D-printable file where the brightness of each pixel becomes the height of the surface — so bright areas are raised and dark areas are recessed. The result is a tactile lithograph that someone can feel with their hands.

```
Microscopy Image → Height Map → STL → G-code → 3D Printer → Tactile Lithograph
```

---

## Who is this for?

This repo is designed to be **accessible to everyone** — including researchers with no programming experience. If you have never used Python or a terminal before, start with the [Getting Started from Zero](#getting-started-from-zero) guide below.

---

## Getting Started from Zero

Follow these steps if you have never used Python before.

### 1. Install Python

Download and install Python 3.10 or newer from the official website:
→ **https://www.python.org/downloads/**

> ⚠️ During installation on Windows, make sure to check **"Add Python to PATH"** before clicking Install.

To verify Python installed correctly, open a terminal (Command Prompt on Windows, Terminal on Mac/Linux) and type:
```
python --version
```
You should see something like `Python 3.11.2`.

---

### 2. Download this repository

Click the green **Code** button at the top of this page → **Download ZIP** → unzip the folder somewhere on your computer (e.g. your Desktop).

Or if you have Git installed:
```bash
git clone https://github.com/nagova/TAMP-OS.git
```

---

### 3. Install dependencies

Open a terminal, navigate into the repo folder, and run:
```bash
cd open_source_printing
pip install -r requirements.txt
```

This installs all the Python libraries needed (numpy, pillow, scipy, numpy-stl). You only need to do this once.

---

### 4. Run the batch GUI

```bash
python tamp_batch_gui.py
```

A window will open. From there you can select your images, set your parameters, and click **▶ Generate STLs** — no more command-line needed.

> 💡 **Prefer Jupyter notebooks?** Open `tamp_litho.ipynb` or `tamp_batch_gui.ipynb` in Jupyter Lab instead.

---

## Open-Source Printing Pipeline

See [`open_source_printing/`](open_source_printing/) for the full workflow guide, parameter descriptions, and printer recommendations.

**Quick example (command line):**
```bash
pip install -r open_source_printing/requirements.txt

python open_source_printing/tamp_litho.py your_image.png \
  --size-x 100 --size-y 75 \
  --relief-height 3.0
```

---

## Repository Structure

```
TAMP-OS/
├── README.md                              ← you are here
└── open_source_printing/
    ├── README.md                          ← full workflow guide
    ├── tamp_litho.py                      ← command-line pipeline script
    ├── tamp_litho.ipynb                   ← Jupyter notebook version
    ├── tamp_batch_gui.py                  ← batch GUI (multiple images at once)
    ├── tamp_batch_gui.ipynb               ← Jupyter notebook version of GUI
    ├── requirements.txt                   ← Python dependencies
    └── examples/
        └── fept_spheres/
            ├── SEM_5um_raw.png            ← example SEM input
            └── sem5um_preview.png         ← height map preview
```

---

## License

GPL-3.0 — same as the original TAMP repository.

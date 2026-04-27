# TAMP-OS

**TAMP-OS** is an open-source extension of the [TAMP](https://github.com/Aschulz94/TAMP) (Tactile Accessible Microscopy Printing) workflow, replacing the Bambu Lab dependency with a fully open-source, scriptable pipeline.

Robert Faulkner, Natalia Gonzalez-Vazquez, Victoria Gamez, Karly E. Cohen, Gunther Richter, Abigale Stangl, Andrew K. Schulz

[![Science paper](https://img.shields.io/badge/Science-Paper-B31B1B.svg)](https://www.science.org/doi/10.1126/science.adx8981)
[![Original TAMP repo](https://img.shields.io/badge/GitHub-TAMP-181717.svg)](https://github.com/Aschulz94/TAMP)

---

## What is TAMP?

TAMP converts microscopy images (SEM, TEM, stereo microscopy) into tactile 3D prints, making scientific imagery accessible to blind and visually impaired people. See the original repo and *Science* paper for full details.

## What is TAMP-OS?

TAMP-OS replaces the proprietary Bambu Lab slicer with an open-source pipeline:

```
Microscopy Image → Height Map → STL → G-code (PrusaSlicer) → Any open-source printer
```

This gives researchers:
- **Full scripting control** — automate the entire workflow in Python
- **No hardware lock-in** — works with any FDM printer (Prusa, Voron, etc.)
- **Direct printer integration** — send prints via Klipper/Moonraker API

---

## Open-Source Printing Pipeline

See [`open_source_printing/`](open_source_printing/) for installation, usage, and printer recommendations.

**Quick start:**
```bash
pip install -r open_source_printing/requirements.txt

python open_source_printing/tamp_litho.py your_image.png \
  --size-x 100 --size-y 75 \
  --relief-height 3.0 \
  --skip-slice
```

---

## Repository Structure

```
TAMP-OS/
├── README.md                        ← this file
└── open_source_printing/
    ├── README.md                    ← full workflow guide
    ├── tamp_litho.py                ← main pipeline script
    ├── requirements.txt
    └── examples/
        └── fept_spheres/
            ├── SEM_5um_raw.png      ← example SEM input
            └── sem5um_preview.png   ← height map preview
```

---

## License

GPL-3.0 — same as the original TAMP repository.

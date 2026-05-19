# TAMP-OS

**TAMP-OS** is an open-source extension of the [TAMP](https://github.com/Aschulz94/TAMP) (Tactile Accessible Microscopy Printing) workflow previously used to generate lithographs of microscopy images. 
Robert Faulkner, Natalia Gonzalez-Vazquez, Victoria Gamez, Karly E. Cohen, Gunther Richter, Abigale Stangl, Andrew K. Schulz

[![Science paper](https://img.shields.io/badge/Science-Paper-B31B1B.svg)](https://www.science.org/doi/10.1126/science.adx8981)
[![Original TAMP repo](https://img.shields.io/badge/GitHub-TAMP-181717.svg)](https://github.com/Aschulz94/TAMP)

---

## What is this+

TAMP converts microscopy images into 3D-printed tactile lithographs  making scientific imagery accessible to blind and visually impaired people. The original workflow used Bambu Lab hardware.

**TAMP-OS replaces the proprietary Bambu Lab dependency with a fully open-source pipeline** that works with any FDM printer, gives full scripting control, and requires no hardware lock-in.

```
Microscopy Image  Height Map  STL  G-code  Any open-source printer  Tactile Lithograph
```

---

## Goals

- Make tactile science communication accessible to any lab, regardless of budget or hardware
- Provide a fully scriptable, automatable pipeline
- Be approachable for researchers with no programming experience
- Support multiple output formats (STL, 3MF, GLB) and printers

---

## Get started

Everything you need is in [`open_source_printing/`](open_source_printing/)  full instructions, parameter descriptions, printer recommendations, and troubleshooting.

---

## License

GPL-3.0  same as the original TAMP repository.

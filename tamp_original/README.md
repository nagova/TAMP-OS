
 <h1 align="center">TAMP: Tactile Accessible Microscopy Printing Workflow</h1>

<p align="center">
Robert Faulkner, Natalia Gonzalez-Vazquez, Victoria Gamez, Karly E. Cohen, Gunther Richter, Abigale Stangl, Andrew K. Schulz
</p>

<p align="center">
  <a href="https://www.science.org/doi/10.1126/science.adx8981">
    <img src="https://img.shields.io/badge/Science-Paper-B31B1B.svg" alt="Science paper">
	  <a href="https://doi.org/10.17617/3.ROQPWZ">
    <img src="https://img.shields.io/badge/Data%20Repository-Edmond-005BBB.svg" alt="Edmond Repository">
  </a>
</p>
 
 <p align="center">

  <img src="Figure1_SICB2026.png" alt="Image of the workflow for the TAMP design. The workflow begins with the microscopy technique box showing a stereo microscopy, SEM, and TEM. An arrow connects the microscopy technique box with an image acquisition toolbox which includes screen captures of scanning electron and transmission electron microscopy images showing monochrome and multichrome images from SHG and histology. An arrow connects the image acqusition box to an image processing box showing the steps of grayscale converstion, and adding filters. This box connects to the 3D file creation box which is done in Bambu Lab with customizing the layer height and length scale of the image. The 3D file creation box is connected with two boxes on teh right including the workflow of adding these lithographs as 3D data files in repositories as well as a 3D printable lithograph for various means." width="100%">
</p>

## General Information

This repository contains the workflow for creating cheap, open-source, and small-size 3D printable lithographs described in the paper: **"A low-data, low-cost, and open-source workflow for 3D printing lithographs for digital accessibility of microscopy images"** (presented at SICB 2026). For related data (e.g., 3D files used in this project), please refer to the <a href="https://doi.org/10.17617/3.ROQPWZ">Edmond data repository</a> (repository will be available upon paper acceptance).

This workflow converts microscopy images — including scanning electron microscopy (SEM), transmission electron microscopy (TEM), second-harmonic generation (SHG) microscopy, and brightfield light microscopy — into 3D-printable `.STL` lithograph files using only freely available desktop software. Lithographs can be printed on a ~$300–$350 FDM 3D printer from files under 100 MB, for a total cost of approximately **$0.75 per print**.

💡 Tip: You can switch between [Light and Dark mode](https://github.com/settings/appearance) in your GitHub profile settings for better readability. This repo is designed to be viewed in Light mode.

Please read through this repository in its entirety and if there are any issues or comments, please send a pull request. This repository:
- Sets up the dependencies for the TAMP workflow.
- Shows example files going from microscopy image to 3D texture map.
- Shows example 3D prints produced on three printers: Stratasys J835, Carbon M2, and Bambu Labs X1E.

This is the first version of this repository and we will continue to augment and update this workflow for better digital accessibility and more realistic (both tactilely and visually) 3D representation of microscopy images. This repository is linked to the [Tactile Media Alliance](https://www.tactilemediaalliance.org) and [See3D](https://see3d.org) and will be continuously updated.

---

## Features

1. Convert microscopy images (SEM, TEM, SHG, light microscopy) to 3D-printable `.STL` lithographs
2. Grayscale and filter-based image preprocessing in ImageJ/Fiji
3. STL generation with customizable layer height and length scale via Bambu Maker Lab
4. Support for both external and internal (inverse LUT) texture maps
5. Workflow tested and validated across FDM, SLA, and MJP printer technologies
6. Compatible with single images and multi-panel figures

---

## Getting Started

### Dependencies

| Dependency | Version | Purpose | Link |
|------------|---------|---------|------|
| ImageJ / Fiji | Latest | Image preprocessing (grayscale conversion, Gaussian blur, filters) | [fiji.sc](https://fiji.sc) |
| Bambu Maker Lab | Latest | STL file generation from processed images | [makerworld.bambulab.com](https://makerworld.bambulab.com) |
| Bambu Studio (or equivalent slicer) | Latest | Slicing and print preparation | [bambulab.com/en/download/studio](https://bambulab.com/en/download/studio) |

### Workflow Steps

1. **Import image into ImageJ/Fiji**
   - Convert to grayscale
   - For images with very fine detail (1–2 pixel precision), apply a Gaussian blur filter (radius = 1.0 pixel)
   - Export as `.PNG` or `.JPG`

2. **Upload to Bambu Maker Lab**
   - Generate an **external** or **internal** (inverse LUT filter) `.STL` file
   - Iterate on brightness or shading filters to reduce file size (e.g., ~150 MB → ~75 MB)

3. **Slice and print**
   - Load `.STL` into your slicer of choice
   - Recommended FDM settings: 0.12 mm layer height, 0.4 mm nozzle

---

## Microscopy Images Used

All example images were drawn from open-source, previously published datasets:

| Sample | Modality | Reference |
|--------|---------|-----------|
| Pacific Spiny Lumpsucker armor | SEM | Woodruff et al. 2022; Hoover et al. 2023 |
| α-FeSi₂ gold nanowhiskers | TEM | Huang et al. 2019 |
| Elephant whiskers | SEM | Schulz et al. 2026 |
| Rodent teeth enamel | TEM/SEM | Srot et al. 2024 |
| Elephant trunk skin collagen | SHG | Schulz et al. 2025 |

---

## Printer Comparison

Lithographs were validated across three printer technologies for a 10 × 10 cm print:

| Printer | Type | Layer Height | Material | Print Time | Approx. Cost |
|---------|------|-------------|---------|------------|--------------|
| Bambu Labs X1E | FDM | 0.12 mm (0.4 mm nozzle) | PLA (~37 g) | ~2 hours | **~$0.75** |
| Carbon M2 | SLA | 0.1 mm | Loctite 3843 resin (~45 mL) | ~3.5 hours | ~$11 |
| Stratasys J835 | MJP (PolyJet) | 0.027 mm | Vero Black resin (~82 g) | ~52 min | ~$16 |

For most laboratories, classrooms, and public-facing institutions, the **Bambu Labs FDM printer** offers the lowest barrier to entry with the best price-to-performance ratio.

---

## Future Work

- [ ] User evaluation of lithographs with blind and low-vision participants
- [ ] Comparative testing across SEM, TEM, SHG, and light microscopy modalities
- [ ] Optimization of image-to-height conversion for dense, high-contrast images
- [ ] Design guidelines for scale, contrast, simplification, and surface detail
- [ ] Exploration of sustainable filament alternatives (biodegradable, recycled)
- [ ] Improved accessibility of the workflow itself for disabled makers and researchers
- [ ] Expanded documentation, templates, and discipline-specific guides

---

## Support

Please note that this repository doesn't come with direct support, but feel free to contact us. Our names and contact information are listed at the bottom of this page.

## Contributing

Please feel free to contribute improvements or report issues.

## Note

If you encounter any problems or questions about specific parts of the repository, don't hesitate to raise an issue. Always provide as much context as possible.

---
```bibtex
@misc{faulkner_tamp_2026,
  title        = {A low-data, low-cost, and open-source workflow for 3D printing lithographs
                  for digital accessibility of microscopy images},
  author       = {Faulkner, Robert and Gonzalez-Vazquez, Natalia and Gamez, Victoria and
                  Cohen, Karly E. and Richter, Gunther and Stangl, Abigale and Schulz, Andrew K.},
  howpublished = {Presented at SICB 2026},
  year         = {2026},
}
```

---

## License

This project is licensed under the GNU GPL version 3 — see the [LICENSE](LICENSE) file for details.

## Copyright

© 2026, Max Planck Society

---

## Acknowledgements

The authors are grateful for the support of the **Tactile Media Alliance**. A.K.S. acknowledges support from the **Alexander von Humboldt Foundation**. G.R. and A.K.S. acknowledge support from the **Max Planck Society**.

---

## Contact

This repository is maintained by [Andrew Schulz](https://github.com/Aschulz94) and collaborators.

Give a ⭐ if you like this work.

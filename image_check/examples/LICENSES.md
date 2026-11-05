# Example images for `tamp_image_check.ipynb`: sources and licences

These images are **not** covered by the repository's GPL-3.0 licence (that covers the code).
Each one is public domain, CC0, or has no known copyright restrictions, as stated by its source.
All except the two synthetic/derived files were taken from the sample data bundled with
[scikit-image](https://scikit-image.org/docs/stable/api/skimage.data.html) (`skimage.data`), which documents their provenance.

| File | Content | Source | Licence |
|---|---|---|---|
| `retina_fundus_cc0.jpg` | Fundus photograph of a normal left eye | Mikael Häggström, [Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Fundus_photograph_of_normal_left_eye.jpg); `skimage.data.retina` | CC0 1.0 |
| `retina_detail_102px_cc0.png` | Retina detail with microaneurysms (green channel), 102 × 102 px | High-Resolution Fundus (HRF) Image Database, image 07_dr (Budai et al. 2013, doi:10.1155/2013/154860); `skimage.data.microaneurysms` | CC0 (given by owner, A. Maier) |
| `ihc_colon_no_known_restrictions.png` | Colonic glands, IHC (DAB, FHL2) with hematoxylin counterstain | Center for Microscopy And Molecular Imaging (CMMI); `skimage.data.immunohistochemistry` | No known copyright restrictions |
| `hubble_xdf_public_domain.jpg` | Hubble eXtreme Deep Field | NASA / HubbleSite (2012, release 37); `skimage.data.hubble_deep_field` | Public domain (NASA) |
| `synthetic_colour_only.png` | Red disks on a blue-grey background with (almost) equal brightness, plus noise | Generated for this repository | Same as the repository |
| `sem_crop_simulated_noise.png` | Crop of `examples/fept_spheres/SEM_5um_raw.png` with simulated noise added (σ = 70 grey levels) to mimic a fast-scan SEM image | Derived from this repository's example | Same as the repository |

To add an image to the gallery, use a source whose licence explicitly allows reuse, add a row here, and add an entry to `GALLERY` in the notebook.

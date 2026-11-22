# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files

datas = []
# Collect customtkinter themes, assets, and fonts
datas += collect_data_files('customtkinter')

# Include lightweight example images for immediate out-of-the-box testing
datas += [
    ('examples/SEM_5um_raw.png', 'examples'),
    ('examples/crab_spider.jpg', 'examples'),
    ('examples/input_li_gradient.png', 'examples'),
]

hiddenimports = [
    'scipy.spatial',
    'scipy.spatial.ckdtree',
    'scipy.ndimage',
    'matplotlib.backends.backend_tkagg',
    'stl',
    'stl.mesh',
    'PIL',
    'PIL.Image',
    'PIL.ImageTk',
]

excludes = [
    'IPython',
    'jupyter',
    'jupyterlab',
    'notebook',
    'nbformat',
    'nbconvert',
    'pytest',
    'torch',
    'tensorflow',
    'sphinx',
]

a = Analysis(
    ['tamp_os_gui.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='TAMP-OS',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='TAMP-OS',
)

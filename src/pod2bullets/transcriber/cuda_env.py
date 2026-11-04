"""Automatic discovery and preloading of NVIDIA CUDA 12 & cuDNN 9 shared libraries in WSL/Linux."""

import ctypes
import logging
import os
import site
import sys
from pathlib import Path

logger = logging.getLogger("pod2bullets.transcriber")

_CUDA_LIBS_PRELOADED = False


def get_nvidia_lib_dirs() -> list[str]:
    """Return all existing NVIDIA CUDA/cuDNN library directories in the active environment."""
    candidate_roots: list[Path] = []

    # Check virtualenv / site-packages locations
    for sp in site.getsitepackages() + [site.getusersitepackages()]:
        if sp:
            nv_root = Path(sp) / "nvidia"
            if nv_root.is_dir():
                candidate_roots.append(nv_root)

    # Also check relative to sys.prefix
    venv_nv = (
        Path(sys.prefix)
        / "lib"
        / f"python{sys.version_info.major}.{sys.version_info.minor}"
        / "site-packages"
        / "nvidia"
    )
    if venv_nv.is_dir() and venv_nv not in candidate_roots:
        candidate_roots.append(venv_nv)

    # Prefer CUDA 12 subdirectories first (cublas, cuda_runtime, cudnn, cuda_nvrtc) before cu13
    priority_subdirs = [
        "cuda_runtime",
        "cublas",
        "cudnn",
        "cuda_nvrtc",
        "cufft",
        "curand",
        "cusolver",
        "cusparse",
    ]
    lib_dirs: list[str] = []

    for nv_root in candidate_roots:
        for sub in priority_subdirs:
            lib_dir = nv_root / sub / "lib"
            if lib_dir.is_dir():
                s_dir = str(lib_dir.resolve())
                if s_dir not in lib_dirs:
                    lib_dirs.append(s_dir)
        for child in sorted(nv_root.glob("*/lib")):
            if child.is_dir():
                s_dir = str(child.resolve())
                if s_dir not in lib_dirs:
                    lib_dirs.append(s_dir)

    # Include WSL host driver library path if present
    wsl_lib = Path("/usr/lib/wsl/lib")
    if wsl_lib.is_dir():
        s_wsl = str(wsl_lib)
        if s_wsl not in lib_dirs:
            lib_dirs.append(s_wsl)

    return lib_dirs


def ensure_cuda_libraries_loaded() -> list[str]:
    """Preload CUDA 12 & cuDNN 9 .so files with RTLD_GLOBAL and update LD_LIBRARY_PATH."""
    global _CUDA_LIBS_PRELOADED
    lib_dirs = get_nvidia_lib_dirs()
    if not lib_dirs:
        return []

    # Update LD_LIBRARY_PATH in environment
    current_ld = os.environ.get("LD_LIBRARY_PATH", "")
    current_parts = [p for p in current_ld.split(":") if p]
    missing = [d for d in lib_dirs if d not in current_parts]
    if missing:
        os.environ["LD_LIBRARY_PATH"] = ":".join(lib_dirs + current_parts)

    if _CUDA_LIBS_PRELOADED:
        return lib_dirs

    # Order matters: runtime -> cublasLt -> cublas -> cudnn base -> cudnn sub-engines
    preload_order = [
        "libcudart.so.12",
        "libnvrtc.so.12",
        "libcublasLt.so.12",
        "libcublas.so.12",
        "libcudnn.so.9",
        "libcudnn_ops.so.9",
        "libcudnn_cnn.so.9",
        "libcudnn_adv.so.9",
        "libcudnn_graph.so.9",
        "libcudnn_heuristic.so.9",
        "libcudnn_engines_precompiled.so.9",
        "libcudnn_engines_runtime_compiled.so.9",
    ]

    rtld_global = getattr(ctypes, "RTLD_GLOBAL", 0)
    loaded_names: list[str] = []

    for lib_name in preload_order:
        for d in lib_dirs:
            candidate = Path(d) / lib_name
            if candidate.exists():
                try:
                    ctypes.CDLL(str(candidate), mode=rtld_global)
                    loaded_names.append(lib_name)
                    break
                except OSError as exc:
                    logger.debug(f"[CUDA] Não foi possível pré-carregar {candidate}: {exc}")

    _CUDA_LIBS_PRELOADED = True
    if loaded_names:
        logger.info(
            f"[CUDA] Bibliotecas GPU CUDA 12 carregadas na memória ({', '.join(loaded_names[:5])})!"
        )
    return lib_dirs

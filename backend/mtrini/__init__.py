"""Mtrini Workspace backend."""

__version__ = "0.9.3"
PRODUCT = "Mtrini Workspace"
VENDOR = "Compiwer AI"
TAGLINE = "Your AI. Your code. Your workspace."


def _hide_broken_zstandard() -> bool:
    """Keep a half-packaged `zstandard` from breaking every model request.

    httpx offers servers zstd compression whenever `import zstandard` works. A packaged build can
    carry the module's folder without its code, so the import succeeds but there is no
    ZstdDecompressor, and decoding the reply fails with "module 'zstandard' has no attribute
    'ZstdDecompressor'". When the module can't decompress, hide it: httpx then asks for gzip.
    Runs before anything imports httpx, because this package is imported first.
    """
    import sys

    try:
        import zstandard
    except Exception:  # noqa: BLE001  (not installed, or its native part failed to load: httpx copes with that)
        return False
    if hasattr(zstandard, "ZstdDecompressor"):
        return False
    for name in [n for n in sys.modules if n == "zstandard" or n.startswith("zstandard.")]:
        del sys.modules[name]
    sys.modules["zstandard"] = None  # makes `import zstandard` raise ImportError from here on
    return True


_hide_broken_zstandard()

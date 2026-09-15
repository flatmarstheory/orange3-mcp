"""Manage Orange3 add-ons (PyPI packages that plug into Orange Canvas) via pip."""
from __future__ import annotations

import subprocess
import sys
from importlib import metadata

# Known Orange3 add-ons (PyPI distribution names). Orange discovers add-ons
# via the "orange3.addon" / "orange.widgets" entry points; by convention
# their distribution names start with "Orange3-".
KNOWN_ADDONS: dict[str, str] = {
    "Orange3-Text": "Text mining: corpus import, preprocessing, topic modelling, NLP widgets.",
    "Orange3-ImageAnalytics": "Image embedding, import and analysis widgets.",
    "Orange3-Timeseries": "Time series modelling, forecasting and visualization widgets.",
    "Orange3-Bioinformatics": "Gene expression and bioinformatics widgets.",
    "Orange3-Associate": "Association rule mining and frequent itemsets.",
    "Orange3-Network": "Network / graph analysis and visualization widgets.",
    "Orange3-Geo": "Geographic map visualizations.",
    "Orange3-Educational": "Interactive widgets for teaching data mining concepts.",
    "Orange3-Explain": "Model explanation widgets (e.g. SHAP-based explanations).",
    "Orange3-Prototypes": "Experimental / incubating widgets.",
    "Orange3-DataFusion": "Data fusion / matrix completion widgets.",
    "Orange3-SingleCell": "Single-cell data analysis widgets.",
    "Orange3-Spectroscopy": "Spectroscopy and hyperspectral data widgets.",
}


_NOT_AN_ADDON = {"orange3-mcp"}


def list_installed_addons() -> list[dict]:
    installed = []
    for dist in metadata.distributions():
        name = dist.metadata.get("Name") or ""
        lowered = name.lower()
        if lowered in _NOT_AN_ADDON:
            continue
        if lowered.startswith("orange3-") or lowered == "orange3":
            installed.append({"name": name, "version": dist.version})
    installed.sort(key=lambda d: d["name"].lower())
    return installed


def search_addons(query: str = "") -> list[dict]:
    """Search the curated list of known Orange3 add-ons by substring.

    This does not hit PyPI's search API (PyPI no longer offers one); it's a
    curated shortlist of well-known community add-ons. install_addon() can
    still be used with any exact PyPI package name, known or not.
    """
    query = (query or "").strip().lower()
    installed_names = {a["name"].lower() for a in list_installed_addons()}
    results = []
    for name, description in KNOWN_ADDONS.items():
        if query and query not in name.lower() and query not in description.lower():
            continue
        results.append({
            "name": name,
            "description": description,
            "installed": name.lower() in installed_names,
        })
    return results


def _run_pip(args: list[str]) -> dict:
    proc = subprocess.run(
        [sys.executable, "-m", "pip", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": proc.stdout[-4000:],
        "stderr": proc.stderr[-4000:],
    }


def install_addon(name: str, version: str | None = None) -> dict:
    spec = f"{name}=={version}" if version else name
    return _run_pip(["install", "--upgrade", spec])


def uninstall_addon(name: str) -> dict:
    return _run_pip(["uninstall", "-y", name])

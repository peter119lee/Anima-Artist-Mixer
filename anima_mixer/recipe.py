"""Recipe serialization: share a full mixer setup as a single JSON string."""

import json

from .constants import (
    COMBINE_CHOICES,
    COMBINE_OUTPUT_AVG,
    FUSION_CHOICES,
    FUSION_INTERPOLATE,
    RECIPE_FORMAT,
    RECIPE_VERSION,
)
from .options import base_advanced_options
from .parsing import clamp_float


def serialize_recipe(artist_chain, combine_mode, fusion_mode, strength,
                     advanced_options=None, notes=""):
    """Pack a mixer configuration into a stable, shareable JSON string."""
    adv = base_advanced_options()
    if isinstance(advanced_options, dict):
        for key in adv:
            if key in advanced_options:
                adv[key] = advanced_options[key]
    payload = {
        "format": RECIPE_FORMAT,
        "version": RECIPE_VERSION,
        "artist_chain": str(artist_chain or ""),
        "combine_mode": combine_mode if combine_mode in COMBINE_CHOICES else COMBINE_OUTPUT_AVG,
        "fusion_mode": fusion_mode if fusion_mode in FUSION_CHOICES else FUSION_INTERPOLATE,
        "strength": clamp_float(strength, 0.0, 4.0),
        "advanced_options": adv,
        "notes": str(notes or ""),
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def deserialize_recipe(recipe_json):
    """Parse a recipe JSON string. Returns (payload, warnings).

    Unknown keys are ignored; missing keys fall back to defaults so older
    recipes keep loading after the schema grows.
    """
    warnings = []
    try:
        data = json.loads(str(recipe_json or ""))
    except (TypeError, ValueError) as e:
        raise ValueError(f"[AnimaArtistRecipe] invalid recipe JSON: {e}")
    if not isinstance(data, dict):
        raise ValueError("[AnimaArtistRecipe] recipe JSON must be an object")

    fmt = data.get("format")
    if fmt != RECIPE_FORMAT:
        warnings.append(f"unexpected format marker {fmt!r}; trying to load anyway")
    version = data.get("version")
    if isinstance(version, int) and version > RECIPE_VERSION:
        warnings.append(
            f"recipe version {version} is newer than supported {RECIPE_VERSION}; "
            "some settings may be ignored"
        )

    combine_mode = data.get("combine_mode", COMBINE_OUTPUT_AVG)
    if combine_mode not in COMBINE_CHOICES:
        warnings.append(f"unknown combine_mode {combine_mode!r}; using {COMBINE_OUTPUT_AVG}")
        combine_mode = COMBINE_OUTPUT_AVG
    fusion_mode = data.get("fusion_mode", FUSION_INTERPOLATE)
    if fusion_mode not in FUSION_CHOICES:
        warnings.append(f"unknown fusion_mode {fusion_mode!r}; using {FUSION_INTERPOLATE}")
        fusion_mode = FUSION_INTERPOLATE

    try:
        strength = clamp_float(data.get("strength", 1.0), 0.0, 4.0)
    except (TypeError, ValueError):
        warnings.append("invalid strength; using 1.0")
        strength = 1.0

    adv = base_advanced_options()
    raw_adv = data.get("advanced_options")
    if isinstance(raw_adv, dict):
        # Coerce each value to the default's type so a malformed recipe
        # degrades to a warning here instead of a raw crash at patch time.
        for key, default_value in adv.items():
            if key not in raw_adv:
                continue
            value = raw_adv[key]
            try:
                if isinstance(default_value, bool):
                    adv[key] = bool(value)
                elif isinstance(default_value, int):
                    adv[key] = int(value)
                elif isinstance(default_value, float):
                    adv[key] = float(value)
                elif isinstance(default_value, str):
                    adv[key] = str(value)
                else:
                    adv[key] = value
            except (TypeError, ValueError):
                warnings.append(
                    f"invalid value for advanced option {key!r}: {value!r}; "
                    "using the default"
                )
        unknown = set(raw_adv) - set(adv)
        if unknown:
            warnings.append(f"ignored unknown advanced options: {sorted(unknown)}")

    payload = {
        "artist_chain": str(data.get("artist_chain", "") or ""),
        "combine_mode": combine_mode,
        "fusion_mode": fusion_mode,
        "strength": strength,
        "advanced_options": adv,
        "notes": str(data.get("notes", "") or ""),
    }
    return payload, warnings

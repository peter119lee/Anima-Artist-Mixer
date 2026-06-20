"""Live ComfyUI comparison against the original Anima Artist Mixer node.

This is a manual integration harness for PR evidence. It needs a running
ComfyUI server with exactly one Anima Artist Mixer implementation enabled:

    # current implementation
    python tests/live_original_compare.py --variant current --include-prompt

    # original implementation
    python tests/live_original_compare.py --variant original

    # combine both result JSON files into one sheet and metric report
    python tests/live_original_compare.py --combine current.json original.json

The default prompt/settings mirror the PR #4 attached workflow as closely as
this local ComfyUI install allows. The workflow's UNET file name is mapped to
the locally available Anima base model; the model mapping is recorded in JSON.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import statistics
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw


SERVER = os.environ.get("ANIMA_COMPARE_SERVER", "http://127.0.0.1:8190")
OUTPUT_DIR = Path(os.environ.get("ANIMA_COMFY_OUTPUT", r"I:\ComfyUI-aki-v1.6\ComfyUI\output"))
RESULT_DIR = Path(os.environ.get("ANIMA_COMPARE_RESULT_DIR", r"I:\ComfyUI-aki-v1.6\ComfyUI\output"))

# The PR workflow references anima-base-v1.0.safetensors. This local install has
# the same Anima base family under ComfyUI's diffusion_models folder.
UNET = os.environ.get("ANIMA_COMPARE_UNET", r"Anima\anime\anima_baseV10.safetensors")
CLIP = os.environ.get("ANIMA_COMPARE_CLIP", "qwen_3_06b_base.safetensors")
VAE = os.environ.get("ANIMA_COMPARE_VAE", "qwen_image_vae.safetensors")

WIDTH = int(os.environ.get("ANIMA_COMPARE_WIDTH", "1024"))
HEIGHT = int(os.environ.get("ANIMA_COMPARE_HEIGHT", "1024"))
STEPS = int(os.environ.get("ANIMA_COMPARE_STEPS", "16"))
CFG = float(os.environ.get("ANIMA_COMPARE_CFG", "5.0"))
SAMPLER = os.environ.get("ANIMA_COMPARE_SAMPLER", "er_sde")
SCHEDULER = os.environ.get("ANIMA_COMPARE_SCHEDULER", "beta")
SEED = int(os.environ.get("ANIMA_COMPARE_SEED", "1098716302142360"))

BASE_PROMPT = (
    "recent,\n\n"
    "And image of asuna yuuki and kirigaya suguha, together singing and dancing "
    "on stage as idols, dynamic pose.\n\n"
    "Asuna is wearing a red and white frilly idol dress. Long hair. White thighhigs. "
    "Panty peek. Hair ornament. Holding microphone.\n\n"
    "Suguha is wearing a blue and white frilly idol dress. Short hair. White thighhigs. "
    "Face, hair, breasts. Panty peek. Hair ornament. Holding microphone.\n\n"
    "Red and blue sparkling in the background."
)

NEG_PROMPT = (
    "deviantart, score_1, score_2, score_3, low resolution, worst quality, "
    "low quality, lowres, bad anatomy, bad hand, extra toes, jpeg, bad composition, "
    "chromatic aberration, censorship"
)

CASES = [
    ("workflow_single_yuchi", r"@yuchi \(salmon-1000\)"),
    ("workflow_double_yuchi_momisan", r"@yuchi \(salmon-1000\), @momisan"),
    (
        "workflow_multi_yuchi_momisan_tonee_umanosuke",
        r"@yuchi \(salmon-1000\), @momisan, @tonee, @umanosuke",
    ),
]


def _request_json(path: str, payload: dict | None = None, timeout: int = 30) -> dict:
    if payload is None:
        return json.load(urllib.request.urlopen(SERVER + path, timeout=timeout))
    req = urllib.request.Request(
        SERVER + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def _safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("_")[:90]


def _base_nodes(prefix: str) -> dict:
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": UNET, "weight_dtype": "default"}},
        "2": {
            "class_type": "CLIPLoader",
            "inputs": {"clip_name": CLIP, "type": "stable_diffusion", "device": "default"},
        },
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": NEG_PROMPT, "clip": ["2", 0]}},
        "8": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": WIDTH, "height": HEIGHT, "batch_size": 1},
        },
        "10": {"class_type": "VAEDecode", "inputs": {"samples": ["9", 0], "vae": ["3", 0]}},
        "11": {"class_type": "SaveImage", "inputs": {"images": ["10", 0], "filename_prefix": prefix}},
    }


def _sampler(model_ref, positive_ref, seed: int = SEED) -> dict:
    return {
        "class_type": "KSampler",
        "inputs": {
            "model": model_ref,
            "positive": positive_ref,
            "negative": ["7", 0],
            "latent_image": ["8", 0],
            "seed": seed,
            "steps": STEPS,
            "cfg": CFG,
            "sampler_name": SAMPLER,
            "scheduler": SCHEDULER,
            "denoise": 1.0,
        },
    }


def graph_prompt(case_label: str, artists: str) -> dict:
    prefix = f"anima_original_compare_{_safe_name(case_label)}_prompt"
    graph = _base_nodes(prefix)
    graph["4"] = {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": f"{artists}\n\n{BASE_PROMPT}", "clip": ["2", 0]},
    }
    graph["9"] = _sampler(["1", 0], ["4", 0])
    return graph


def _current_options_nodes(graph: dict) -> tuple[list, list]:
    graph["5"] = {
        "class_type": "AnimaArtistPreset",
        "inputs": {
            "preset": "balanced",
            "intensity": 1.0,
            "normalize_weights": True,
            "layer_mode": "auto",
            "custom_layer_filter": "",
        },
    }
    return ["5", 1], ["5", 0]


def _original_options_nodes(graph: dict) -> tuple[list, None]:
    graph["5"] = {
        "class_type": "AnimaArtistOptions",
        "inputs": {
            "start_block": 0,
            "end_block": -1,
            "start_percent": 0.0,
            "end_percent": 1.0,
            "normalize_weights": True,
            "artist_ema_alpha": 0.0,
            "lowrank_k": 1,
            "artist_static_capture": False,
            "static_capture_k": 6,
            "artist_anchor_q": False,
            "anchor_seeds_count": 1,
            "anchor_user_blend": 0.0,
            "anchor_deep_layer_threshold": -1,
            "layer_filter": "",
        },
    }
    return ["5", 0], None


def graph_mixer(case_label: str, artists: str, variant: str) -> dict:
    prefix = f"anima_original_compare_{_safe_name(case_label)}_{variant}"
    graph = _base_nodes(prefix)
    graph["4"] = {
        "class_type": "AnimaArtistPack",
        "inputs": {
            "clip": ["2", 0],
            "artist_chain": artists,
            "base_prompt": BASE_PROMPT,
        },
    }
    if variant == "current":
        advanced_ref, preset_ref = _current_options_nodes(graph)
    elif variant == "original":
        advanced_ref, preset_ref = _original_options_nodes(graph)
    else:
        raise ValueError(f"unknown variant: {variant}")

    inputs = {
        "model": ["1", 0],
        "artist_pack": ["4", 0],
        "combine_mode": "output_avg",
        "fusion_mode": "interpolate",
        "strength": 1.0,
        "enabled": True,
        "apply_to_uncond": False,
        "advanced_options": advanced_ref,
    }
    if preset_ref is not None:
        inputs["preset"] = preset_ref
    graph["6"] = {"class_type": "AnimaArtistCrossAttn", "inputs": inputs}
    graph["9"] = _sampler(["6", 0], ["6", 1])
    return graph


def graph_mixer_no_preset(case_label: str, artists: str, variant: str) -> dict:
    prefix = f"anima_original_compare_{_safe_name(case_label)}_{variant}_no_preset"
    graph = _base_nodes(prefix)
    graph["4"] = {
        "class_type": "AnimaArtistPack",
        "inputs": {
            "clip": ["2", 0],
            "artist_chain": artists,
            "base_prompt": BASE_PROMPT,
        },
    }
    graph["6"] = {
        "class_type": "AnimaArtistCrossAttn",
        "inputs": {
            "model": ["1", 0],
            "artist_pack": ["4", 0],
            "combine_mode": "output_avg",
            "fusion_mode": "interpolate",
            "strength": 1.0,
            "enabled": True,
            "apply_to_uncond": False,
        },
    }
    graph["9"] = _sampler(["6", 0], ["6", 1])
    return graph


def submit_and_wait(label: str, graph: dict, timeout: int = 1200) -> dict:
    t0 = time.perf_counter()
    resp = _request_json("/prompt", {"prompt": graph})
    if resp.get("node_errors"):
        raise RuntimeError(f"{label} node_errors: {resp['node_errors']}")
    prompt_id = resp["prompt_id"]
    while time.perf_counter() - t0 < timeout:
        hist = _request_json(f"/history/{prompt_id}")
        if prompt_id in hist:
            entry = hist[prompt_id]
            if entry.get("status", {}).get("status_str") == "error":
                raise RuntimeError(f"{label} execution error: {entry.get('status')}")
            images = []
            for out in entry.get("outputs", {}).values():
                images.extend(out.get("images") or [])
            if not images:
                raise RuntimeError(f"{label} produced no image")
            return {
                "label": label,
                "prompt_id": prompt_id,
                "seconds": time.perf_counter() - t0,
                "image": images[0],
            }
        time.sleep(1)
    raise TimeoutError(f"{label} timed out")


def image_path(image: dict) -> Path:
    return OUTPUT_DIR / image.get("subfolder", "") / image["filename"]


def load_image(image_or_path: dict | str) -> Image.Image:
    if isinstance(image_or_path, str):
        return Image.open(image_or_path).convert("RGB")
    path = image_path(image_or_path)
    if path.exists():
        return Image.open(path).convert("RGB")
    params = urllib.parse.urlencode({
        "filename": image_or_path["filename"],
        "subfolder": image_or_path.get("subfolder", ""),
        "type": image_or_path.get("type", "output"),
    })
    return Image.open(urllib.request.urlopen(SERVER + "/view?" + params, timeout=30)).convert("RGB")


def descriptor(img: Image.Image, size: int = 32) -> list[float]:
    small = img.resize((size, size), Image.Resampling.BILINEAR)
    get_pixels = getattr(small, "get_flattened_data", small.getdata)
    pixels = [(r / 255.0, g / 255.0, b / 255.0) for r, g, b in get_pixels()]
    channels = list(zip(*pixels))
    gray = [0.299 * r + 0.587 * g + 0.114 * b for r, g, b in pixels]
    features: list[float] = []
    for values in (*channels, gray):
        mean = sum(values) / len(values)
        std = math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))
        features.extend([mean, std])
    for values in (*channels, gray):
        hist = [0.0] * 4
        for value in values:
            idx = min(3, int(value * 4))
            hist[idx] += 1.0 / len(values)
        features.extend(hist)
    return features


def descriptor_distance(left: Image.Image, right: Image.Image) -> float:
    a = descriptor(left)
    b = descriptor(right)
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def image_mae(left: Image.Image, right: Image.Image) -> float:
    diff = ImageChops.difference(left, right).convert("L")
    get_pixels = getattr(diff, "get_flattened_data", diff.getdata)
    values = list(get_pixels())
    return sum(values) / (len(values) * 255.0)


def object_info_summary(variant: str) -> dict:
    wanted = ["AnimaArtistPack", "AnimaArtistCrossAttn", "AnimaArtistOptions"]
    if variant == "current":
        wanted.extend(["AnimaArtistPreset", "AnimaArtistSimpleOptions", "AnimaArtistBasic"])
    summary = {}
    for class_type in wanted:
        try:
            info = _request_json(f"/object_info/{class_type}")[class_type]
        except Exception as exc:
            summary[class_type] = {"error": str(exc)}
            continue
        inputs = info.get("input") or {}
        summary[class_type] = {
            "required": list((inputs.get("required") or {}).keys()),
            "optional": list((inputs.get("optional") or {}).keys()),
        }
    return summary


def contact_sheet(entries: list[dict], path: Path, title: str) -> None:
    thumb_w, thumb_h = 320, 320
    label_h = 58
    cols = min(3, max(1, len(entries)))
    rows = math.ceil(len(entries) / cols)
    sheet = Image.new("RGB", (cols * thumb_w, rows * (thumb_h + label_h) + 34), "white")
    draw = ImageDraw.Draw(sheet)
    draw.text((8, 8), title, fill=(0, 0, 0))
    for idx, entry in enumerate(entries):
        img = load_image(entry["image_path"]).resize((thumb_w, thumb_h), Image.Resampling.LANCZOS)
        x = (idx % cols) * thumb_w
        y = (idx // cols) * (thumb_h + label_h) + 34
        sheet.paste(img, (x, y + label_h))
        label = f"{entry['case']}\n{entry['kind']} {entry['variant']} {entry['seconds']:.1f}s"
        draw.multiline_text((x + 6, y + 6), label[:120], fill=(0, 0, 0), spacing=2)
    sheet.save(path)


def _selected_cases(case_filter: str | None) -> list[tuple[str, str]]:
    if not case_filter:
        return CASES
    names = {item.strip() for item in case_filter.split(",") if item.strip()}
    return [case for case in CASES if case[0] in names]


def run_variant(args: argparse.Namespace) -> int:
    variant = args.variant
    if variant not in {"current", "original"}:
        raise ValueError("--variant must be current or original")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    entries: list[dict] = []
    result = {
        "variant": variant,
        "server": SERVER,
        "settings": {
            "width": WIDTH,
            "height": HEIGHT,
            "steps": STEPS,
            "cfg": CFG,
            "sampler": SAMPLER,
            "scheduler": SCHEDULER,
            "seed": SEED,
            "unet": UNET,
            "clip": CLIP,
            "vae": VAE,
            "base_prompt": BASE_PROMPT,
            "negative_prompt": NEG_PROMPT,
            "no_preset": bool(args.no_preset),
        },
        "object_info": object_info_summary(variant),
        "runs": [],
    }
    cases = _selected_cases(args.cases)
    for case_label, artists in cases:
        if args.include_prompt:
            label = f"{case_label}_prompt"
            print(f"run {label}")
            entry = submit_and_wait(label, graph_prompt(case_label, artists))
            run = {
                **entry,
                "case": case_label,
                "artists": artists,
                "variant": "prompt",
                "kind": "prompt",
                "image_path": str(image_path(entry["image"])),
            }
            result["runs"].append(run)
            entries.append(run)
        label = f"{case_label}_{variant}"
        print(f"run {label}")
        builder = graph_mixer_no_preset if args.no_preset else graph_mixer
        entry = submit_and_wait(label, builder(case_label, artists, variant))
        run = {
            **entry,
            "case": case_label,
            "artists": artists,
            "variant": variant,
            "kind": "mixer",
            "image_path": str(image_path(entry["image"])),
        }
        result["runs"].append(run)
        entries.append(run)

    sheet_path = RESULT_DIR / f"anima_original_compare_{variant}_{stamp}.png"
    json_path = RESULT_DIR / f"anima_original_compare_{variant}_{stamp}.json"
    contact_sheet(entries, sheet_path, f"Anima original compare - {variant}")
    result["contact_sheet"] = str(sheet_path)
    json_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"json": str(json_path), "contact_sheet": str(sheet_path)}, indent=2))
    return 0


def _entry_by_case_kind(payloads: list[dict]) -> dict[str, dict[str, dict]]:
    matrix: dict[str, dict[str, dict]] = {}
    for payload in payloads:
        for run in payload.get("runs") or []:
            case = run["case"]
            variant = run["variant"]
            kind = run["kind"]
            key = "prompt" if kind == "prompt" else variant
            matrix.setdefault(case, {})[key] = run
    return matrix


def combine_results(paths: list[str]) -> int:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    payloads = [json.loads(Path(p).read_text(encoding="utf-8")) for p in paths]
    settings = payloads[0].get("settings", {})
    matrix = _entry_by_case_kind(payloads)
    sheet_entries = []
    comparisons = {}
    prompt_consistency = []
    for case, by_variant in matrix.items():
        ordered = [by_variant.get("prompt"), by_variant.get("original"), by_variant.get("current")]
        sheet_entries.extend([entry for entry in ordered if entry is not None])
        prompt_entry = by_variant.get("prompt")
        if not prompt_entry:
            continue
        prompt_img = load_image(prompt_entry["image_path"])
        case_metrics = {}
        for variant in ("original", "current"):
            entry = by_variant.get(variant)
            if not entry:
                continue
            img = load_image(entry["image_path"])
            case_metrics[f"{variant}_vs_prompt_descriptor_distance"] = descriptor_distance(img, prompt_img)
            case_metrics[f"{variant}_vs_prompt_mae"] = image_mae(img, prompt_img)
            case_metrics[f"{variant}_seconds"] = entry["seconds"]
        comparisons[case] = case_metrics

        prompt_entries = [
            run for payload in payloads for run in payload.get("runs", [])
            if run.get("case") == case and run.get("kind") == "prompt"
        ]
        if len(prompt_entries) >= 2:
            base = load_image(prompt_entries[0]["image_path"])
            for other in prompt_entries[1:]:
                prompt_consistency.append({
                    "case": case,
                    "left": prompt_entries[0]["image_path"],
                    "right": other["image_path"],
                    "mae": image_mae(base, load_image(other["image_path"])),
                })

    all_seconds = [
        run["seconds"]
        for payload in payloads
        for run in payload.get("runs", [])
        if isinstance(run.get("seconds"), (int, float))
    ]
    summary = {
        "settings": settings,
        "inputs": paths,
        "comparisons": comparisons,
        "prompt_consistency": prompt_consistency,
        "avg_seconds": statistics.mean(all_seconds) if all_seconds else None,
    }
    sheet_path = RESULT_DIR / f"anima_original_compare_combined_{stamp}.png"
    json_path = RESULT_DIR / f"anima_original_compare_combined_{stamp}.json"
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    contact_sheet(sheet_entries, sheet_path, "Anima original/current/prompt compare")
    summary["contact_sheet"] = str(sheet_path)
    json_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"json": str(json_path), "contact_sheet": str(sheet_path), **summary}, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", choices=["current", "original"])
    parser.add_argument("--include-prompt", action="store_true")
    parser.add_argument("--cases", help="Comma-separated case labels to run.")
    parser.add_argument("--no-preset", action="store_true",
                        help="Use only CrossAttn required inputs, matching the compatibility workflow.")
    parser.add_argument("--combine", nargs="+", help="Combine existing result JSON files.")
    args = parser.parse_args()
    if args.combine:
        return combine_results(args.combine)
    if not args.variant:
        parser.error("--variant is required unless --combine is used")
    return run_variant(args)


if __name__ == "__main__":
    raise SystemExit(main())

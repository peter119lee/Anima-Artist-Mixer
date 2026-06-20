"""Live PR value matrix for Anima-Artist-Mixer.

Runs a small, reproducible ComfyUI matrix that is useful for PR discussion:

* prompt/no-mixer vs default balanced mixer for single, double, and multi artist chains
* optional drift_auto comparison to show it is no longer the default path
* deterministic same-seed repeat check
* small cross-seed variance check for balanced vs stable_seed
* a few feature smoke cases

This is a manual integration harness. It needs a running ComfyUI server,
the Anima model files, and Pillow:

    $env:ANIMA_PR_SERVER="http://127.0.0.1:8190"
    python tests/live_pr_value_matrix.py
"""

from __future__ import annotations

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


SERVER = os.environ.get("ANIMA_PR_SERVER", "http://127.0.0.1:8190")
OUTPUT_DIR = Path(os.environ.get("ANIMA_COMFY_OUTPUT", r"I:\ComfyUI-aki-v1.6\ComfyUI\output"))
RESULT_DIR = Path(os.environ.get("ANIMA_PR_RESULT_DIR", r"I:\ComfyUI-aki-v1.6\ComfyUI\output"))

UNET = "Anima\\anime\\anima_baseV10.safetensors"
CLIP = "qwen_3_06b_base.safetensors"
VAE = "qwen_image_vae.safetensors"

WIDTH = int(os.environ.get("ANIMA_PR_WIDTH", "512"))
HEIGHT = int(os.environ.get("ANIMA_PR_HEIGHT", "512"))
STEPS = int(os.environ.get("ANIMA_PR_STEPS", "8"))
CFG = float(os.environ.get("ANIMA_PR_CFG", "5.0"))
SAMPLER = os.environ.get("ANIMA_PR_SAMPLER", "er_sde")
SCHEDULER = os.environ.get("ANIMA_PR_SCHEDULER", "beta")
SEED = int(os.environ.get("ANIMA_PR_SEED", "42424242"))
SEED_VARIANCE = [int(s) for s in os.environ.get("ANIMA_PR_VARIANCE_SEEDS", "101,202,303").split(",")]

BASE_PROMPT = (
    "1girl, solo, upper body portrait, face visible, white blouse, navy jacket, "
    "looking at viewer, simple background, clean linework, detailed eyes"
)
NEG_PROMPT = (
    "nsfw, nude, naked, bare chest, cleavage, nipples, cropped head, "
    "head out of frame, lowres, worst quality, bad anatomy"
)

CASES = [
    ("single_yuchi", "@yuchi \\(salmon-1000\\)"),
    ("double_yuchi_uof", "@yuchi \\(salmon-1000\\), @uof"),
    ("multi_yuchi_uof_kieed_ciloranko", "@yuchi \\(salmon-1000\\), @uof, @kieed, @ciloranko"),
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
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("_")[:80]


def _base_nodes(prefix: str) -> dict:
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": UNET, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": CLIP, "type": "stable_diffusion", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": NEG_PROMPT, "clip": ["2", 0]}},
        "8": {"class_type": "EmptyLatentImage", "inputs": {"width": WIDTH, "height": HEIGHT, "batch_size": 1}},
        "10": {"class_type": "VAEDecode", "inputs": {"samples": ["9", 0], "vae": ["3", 0]}},
        "11": {"class_type": "SaveImage", "inputs": {"images": ["10", 0], "filename_prefix": prefix}},
    }


def _sampler(model_ref, positive_ref, seed: int) -> dict:
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


def graph_prompt_no_mixer(label: str, artists: str, seed: int) -> dict:
    prefix = f"anima_pr_{_safe_name(label)}_prompt"
    graph = _base_nodes(prefix)
    graph["4"] = {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": f"{artists}, {BASE_PROMPT}", "clip": ["2", 0]},
    }
    graph["9"] = _sampler(["1", 0], ["4", 0], seed)
    return graph


def graph_basic(label: str, artists: str, seed: int, preset: str) -> dict:
    prefix = f"anima_pr_{_safe_name(label)}_{preset}"
    graph = _base_nodes(prefix)
    graph["4"] = {
        "class_type": "AnimaArtistBasic",
        "inputs": {
            "model": ["1", 0],
            "clip": ["2", 0],
            "artist_chain": artists,
            "base_prompt": BASE_PROMPT,
            "preset": preset,
            "intensity": 1.0,
            "enabled": True,
        },
    }
    graph["9"] = _sampler(["4", 0], ["4", 1], seed)
    return graph


def graph_simple_options(label: str, artists: str, seed: int) -> dict:
    prefix = f"anima_pr_{_safe_name(label)}_simple_options"
    graph = _base_nodes(prefix)
    graph["4"] = {
        "class_type": "AnimaArtistPack",
        "inputs": {"clip": ["2", 0], "artist_chain": artists, "base_prompt": BASE_PROMPT},
    }
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
    graph["6"] = {
        "class_type": "AnimaArtistSimpleOptions",
        "inputs": {
            "normalize_weights": True,
            "layer_mode": "style_core",
            "start_percent": 0.05,
            "end_percent": 0.90,
            "custom_layer_filter": "",
            "compatibility_mode": False,
        },
    }
    graph["12"] = {
        "class_type": "AnimaArtistCrossAttn",
        "inputs": {
            "model": ["1", 0],
            "artist_pack": ["4", 0],
            "combine_mode": "output_avg",
            "fusion_mode": "interpolate",
            "strength": 1.0,
            "enabled": True,
            "apply_to_uncond": False,
            "preset": ["5", 0],
            "advanced_options": ["6", 0],
        },
    }
    graph["9"] = _sampler(["12", 0], ["12", 1], seed)
    return graph


def graph_negative_weight(label: str, seed: int) -> dict:
    return graph_basic(label, "::@uof::1.0, ::@kieed::-0.5", seed, "balanced")


def graph_timing(label: str, seed: int) -> dict:
    return graph_basic(label, "@uof%0.0-0.5~0.1, @kieed%0.4-1.0~0.1", seed, "balanced")


def submit_and_wait(label: str, graph: dict, timeout: int = 300) -> dict:
    t0 = time.perf_counter()
    resp = _request_json("/prompt", {"prompt": graph})
    if resp.get("node_errors"):
        raise RuntimeError(f"{label} node_errors: {resp['node_errors']}")
    pid = resp["prompt_id"]
    while time.perf_counter() - t0 < timeout:
        hist = _request_json(f"/history/{pid}")
        if pid in hist:
            entry = hist[pid]
            if entry.get("status", {}).get("status_str") == "error":
                raise RuntimeError(f"{label} execution error: {entry.get('status')}")
            images = []
            for out in entry.get("outputs", {}).values():
                images.extend(out.get("images") or [])
            if not images:
                raise RuntimeError(f"{label} produced no image")
            return {
                "label": label,
                "prompt_id": pid,
                "seconds": time.perf_counter() - t0,
                "image": images[0],
            }
        time.sleep(1)
    raise TimeoutError(f"{label} timed out")


def image_path(image: dict) -> Path:
    return OUTPUT_DIR / image.get("subfolder", "") / image["filename"]


def load_image(image: dict) -> Image.Image:
    path = image_path(image)
    if path.exists():
        return Image.open(path).convert("RGB")
    params = urllib.parse.urlencode({
        "filename": image["filename"],
        "subfolder": image.get("subfolder", ""),
        "type": image.get("type", "output"),
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
        for bins in (4,):
            hist = [0.0] * bins
            for value in values:
                idx = min(bins - 1, int(value * bins))
                hist[idx] += 1.0 / len(values)
            features.extend(hist)
    return features


def descriptor_distance(a: Image.Image, b: Image.Image) -> float:
    da = descriptor(a)
    db = descriptor(b)
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(da, db)))


def image_mae(a: Image.Image, b: Image.Image) -> float:
    diff = ImageChops.difference(a, b)
    gray = diff.convert("L")
    get_pixels = getattr(gray, "get_flattened_data", gray.getdata)
    values = list(get_pixels())
    return sum(values) / (len(values) * 255.0)


def pairwise_descriptor_distance(images: list[Image.Image]) -> float:
    distances = []
    for i, left in enumerate(images):
        for right in images[i + 1:]:
            distances.append(descriptor_distance(left, right))
    return statistics.mean(distances) if distances else 0.0


def contact_sheet(entries: list[dict], path: Path) -> None:
    thumb_w, thumb_h = 256, 256
    label_h = 36
    cols = 3
    rows = math.ceil(len(entries) / cols)
    sheet = Image.new("RGB", (cols * thumb_w, rows * (thumb_h + label_h)), "white")
    draw = ImageDraw.Draw(sheet)
    for idx, entry in enumerate(entries):
        img = load_image(entry["image"]).resize((thumb_w, thumb_h), Image.Resampling.LANCZOS)
        x = (idx % cols) * thumb_w
        y = (idx // cols) * (thumb_h + label_h)
        sheet.paste(img, (x, y + label_h))
        draw.text((x + 6, y + 8), entry["label"][:34], fill=(0, 0, 0))
    sheet.save(path)


def object_info_summary() -> dict:
    basic = _request_json("/object_info/AnimaArtistBasic")["AnimaArtistBasic"]
    simple = _request_json("/object_info/AnimaArtistSimpleOptions")["AnimaArtistSimpleOptions"]
    expert = _request_json("/object_info/AnimaArtistOptions")["AnimaArtistOptions"]
    return {
        "basic_required": list(basic["input"]["required"].keys()),
        "basic_preset_default": basic["input"]["required"]["preset"][1]["default"],
        "simple_required": list(simple["input"]["required"].keys()),
        "simple_required_count": len(simple["input"]["required"]),
        "expert_required_count": len(expert["input"]["required"]),
        "expert_optional_count": len(expert["input"].get("optional", {})),
    }


def main() -> int:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    results: dict = {
        "server": SERVER,
        "settings": {
            "width": WIDTH,
            "height": HEIGHT,
            "steps": STEPS,
            "cfg": CFG,
            "sampler": SAMPLER,
            "scheduler": SCHEDULER,
            "seed": SEED,
        },
        "object_info": object_info_summary(),
        "runs": [],
    }

    print("warmup prompt/no-mixer")
    submit_and_wait("warmup_prompt", graph_prompt_no_mixer("warmup", CASES[0][1], SEED - 1))

    main_entries = []
    by_label = {}
    for case_label, artists in CASES:
        for variant, builder in (
            ("prompt", graph_prompt_no_mixer),
            ("balanced", lambda label, chain, seed: graph_basic(label, chain, seed, "balanced")),
            ("drift_auto", lambda label, chain, seed: graph_basic(label, chain, seed, "drift_auto")),
        ):
            label = f"{case_label}_{variant}"
            print(f"run {label}")
            entry = submit_and_wait(label, builder(label, artists, SEED))
            by_label[label] = entry
            main_entries.append(entry)
            results["runs"].append(entry)

    comparisons = {}
    for case_label, _ in CASES:
        prompt_img = load_image(by_label[f"{case_label}_prompt"]["image"])
        balanced_img = load_image(by_label[f"{case_label}_balanced"]["image"])
        drift_auto_img = load_image(by_label[f"{case_label}_drift_auto"]["image"])
        comparisons[case_label] = {
            "balanced_vs_prompt_descriptor_distance": descriptor_distance(balanced_img, prompt_img),
            "drift_auto_vs_prompt_descriptor_distance": descriptor_distance(drift_auto_img, prompt_img),
            "balanced_seconds": by_label[f"{case_label}_balanced"]["seconds"],
            "prompt_seconds": by_label[f"{case_label}_prompt"]["seconds"],
            "drift_auto_seconds": by_label[f"{case_label}_drift_auto"]["seconds"],
        }
    results["comparisons"] = comparisons

    print("run deterministic repeat")
    repeat_a = by_label["multi_yuchi_uof_kieed_ciloranko_balanced"]
    repeat_b = submit_and_wait(
        "multi_yuchi_uof_kieed_ciloranko_balanced_repeat",
        graph_basic("multi_yuchi_uof_kieed_ciloranko_balanced_repeat", CASES[-1][1], SEED, "balanced"),
    )
    results["determinism"] = {
        "same_seed_balanced_multi_mae": image_mae(load_image(repeat_a["image"]), load_image(repeat_b["image"])),
        "repeat_seconds": repeat_b["seconds"],
        "repeat_image": repeat_b["image"],
    }
    results["runs"].append(repeat_b)

    variance = {}
    for preset in ("balanced", "stable_seed"):
        print(f"run variance {preset}")
        imgs = []
        entries = []
        for seed in SEED_VARIANCE:
            entry = submit_and_wait(
                f"variance_multi_{preset}_{seed}",
                graph_basic(f"variance_multi_{preset}_{seed}", CASES[-1][1], seed, preset),
            )
            entries.append(entry)
            imgs.append(load_image(entry["image"]))
            results["runs"].append(entry)
        variance[preset] = {
            "seeds": SEED_VARIANCE,
            "pairwise_descriptor_distance": pairwise_descriptor_distance(imgs),
            "avg_seconds": statistics.mean(e["seconds"] for e in entries),
            "images": [e["image"] for e in entries],
        }
    results["variance"] = variance

    feature_entries = []
    for label, graph in (
        ("feature_simple_options", graph_simple_options("feature_simple_options", CASES[-1][1], SEED)),
        ("feature_negative_weight", graph_negative_weight("feature_negative_weight", SEED)),
        ("feature_timing_routes", graph_timing("feature_timing_routes", SEED)),
    ):
        print(f"run {label}")
        entry = submit_and_wait(label, graph)
        feature_entries.append(entry)
        results["runs"].append(entry)
    results["feature_smoke"] = {
        entry["label"]: {"seconds": entry["seconds"], "image": entry["image"]}
        for entry in feature_entries
    }

    sheet_path = RESULT_DIR / f"anima_pr_value_matrix_{stamp}.png"
    json_path = RESULT_DIR / f"anima_pr_value_matrix_{stamp}.json"
    contact_sheet(main_entries, sheet_path)
    results["contact_sheet"] = str(sheet_path)
    for run in results["runs"]:
        run["image_path"] = str(image_path(run["image"]))
    json_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({
        "json": str(json_path),
        "contact_sheet": str(sheet_path),
        "comparisons": comparisons,
        "determinism": results["determinism"],
        "variance": variance,
        "object_info": results["object_info"],
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

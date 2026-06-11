"""Model validation, artist preprocessing, and patch bookkeeping helpers."""

import logging

import torch

logger = logging.getLogger(__name__)


def extract_conditioning(conditioning):
    """Pull (raw_embedding, t5xxl_ids, t5xxl_weights) out of a CONDITIONING."""
    if conditioning is None:
        return None, None, None
    if not isinstance(conditioning, (list, tuple)) or len(conditioning) == 0:
        return None, None, None
    first = conditioning[0]
    if not isinstance(first, (list, tuple)) or len(first) == 0:
        return None, None, None
    raw = first[0] if torch.is_tensor(first[0]) else None
    extra = first[1] if len(first) > 1 and isinstance(first[1], dict) else {}
    return raw, extra.get("t5xxl_ids"), extra.get("t5xxl_weights")


def unwrap_cross_attn(ca):
    # Imported lazily to avoid a circular import at module load time.
    from .wrapper import CrossAttnWrapper
    while isinstance(ca, CrossAttnWrapper):
        ca = ca.original
    return ca


def validate_model(diffusion_model):
    if not hasattr(diffusion_model, "blocks"):
        return False, 0, 0, f"{type(diffusion_model).__name__} has no .blocks"
    blocks = diffusion_model.blocks
    if len(blocks) == 0:
        return False, 0, 0, ".blocks is empty"
    b0 = blocks[0]
    if not hasattr(b0, "cross_attn"):
        return False, 0, 0, "blocks[0] has no cross_attn"
    ca = unwrap_cross_attn(b0.cross_attn)
    if not hasattr(ca, "context_dim"):
        return False, 0, 0, "cross_attn has no context_dim"
    return True, len(blocks), int(ca.context_dim), "ok"


def cleanup_residual_wrappers(dm):
    if not hasattr(dm, "blocks"):
        return 0
    cleaned = 0
    for i in range(len(dm.blocks)):
        blk = dm.blocks[i]
        if not hasattr(blk, "cross_attn"):
            continue
        original = unwrap_cross_attn(blk.cross_attn)
        if blk.cross_attn is not original:
            blk.cross_attn = original
            cleaned += 1
    return cleaned


def describe_external_cross_attn_patches(dm, target_blocks):
    from .wrapper import CrossAttnWrapper
    hints = []
    if not hasattr(dm, "blocks"):
        return hints
    for idx in target_blocks or []:
        if idx < 0 or idx >= len(dm.blocks):
            continue
        blk = dm.blocks[idx]
        if not hasattr(blk, "cross_attn"):
            continue
        ca = blk.cross_attn
        if isinstance(ca, CrossAttnWrapper):
            continue
        original = getattr(ca, "original", None)
        if original is None:
            continue
        hints.append(
            f"L{idx}: {type(ca).__name__} wraps {type(original).__name__}"
        )
    return hints


def preprocess_one(dm, raw, ids, weights, target_device, target_dtype):
    """Run one artist's raw embedding through Anima's LLMAdapter."""
    if ids is None:
        artist = raw.to(device=target_device, dtype=target_dtype)
        if artist.dim() == 2:
            artist = artist.unsqueeze(0)
        return artist
    raw_b = raw if raw.dim() == 3 else raw.unsqueeze(0)
    ids_b = ids if ids.dim() >= 2 else ids.unsqueeze(0)
    weights_b = None
    if weights is not None:
        if weights.dim() == 1:
            weights_b = weights.unsqueeze(0).unsqueeze(-1)
        elif weights.dim() == 2:
            weights_b = weights.unsqueeze(-1)
        else:
            weights_b = weights
    raw_b = raw_b.to(device=target_device, dtype=target_dtype)
    ids_b = ids_b.to(device=target_device)
    if weights_b is not None:
        weights_b = weights_b.to(device=target_device, dtype=target_dtype)
    with torch.inference_mode():
        return dm.preprocess_text_embeds(raw_b, ids_b, t5xxl_weights=weights_b)


def build_artists(state, ref_context):
    """Lazily preprocess every artist conditioning on first forward."""
    if state.get("individuals") is not None:
        return state["individuals"], state["real_lens"]
    dm = state["dm_ref"]
    individuals, real_lens = [], []
    for raw, ids, w_t in zip(state["raws"], state["ids_list"], state["w_list"]):
        artist = preprocess_one(dm, raw, ids, w_t, ref_context.device, ref_context.dtype)
        individuals.append(artist)
        real_lens.append(int(ids.shape[-1]) if ids is not None else artist.shape[1])
    state["individuals"] = individuals
    state["real_lens"] = real_lens
    return individuals, real_lens


def broadcast_batch(t, batch_size):
    if t.shape[0] == batch_size:
        return t
    if t.shape[0] == 1:
        return t.expand(batch_size, -1, -1)
    if batch_size % t.shape[0] == 0:
        return t.repeat(batch_size // t.shape[0], 1, 1)
    return t[:1].expand(batch_size, -1, -1)


def resolve_mask(cou, batch_size, apply_to_uncond, state):
    """Build a per-row injection mask from ComfyUI's cond_or_uncond marker.

    ComfyUI may batch several latents per cond entry, in which case
    ``len(cond_or_uncond) < batch_size`` and rows are grouped in contiguous
    chunks (all rows of cond entry 0 first, then entry 1, ...). Expanding the
    markers over those chunks keeps CFG intact instead of falling back to
    injecting into every row (which would also style the uncond pass).
    """
    if apply_to_uncond:
        return [True] * batch_size
    if cou is not None and len(cou) > 0:
        if len(cou) == batch_size:
            return [c == 0 for c in cou]
        if batch_size % len(cou) == 0:
            chunk = batch_size // len(cou)
            mask = []
            for c in cou:
                mask.extend([c == 0] * chunk)
            return mask
    if not state.get("_warned", False):
        logger.warning(
            "[AnimaCrossAttn] cond_or_uncond markers unusable (got=%s, batch=%d); "
            "falling back to injecting into every row. CFG guidance may weaken — "
            "check for conflicting model patches.", cou, batch_size,
        )
        state["_warned"] = True
    return [True] * batch_size


def in_sigma_range(state):
    rng = state.get("sigma_range")
    if rng is None:
        return True
    cur = state.get("current_sigma")
    if cur is None:
        return True
    lo, hi = rng
    return lo <= cur <= hi

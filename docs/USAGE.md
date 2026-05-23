# Anima-Artist-Mixer

## Introduction

This is a ComfyUI custom node that provides **multi-artist mixing** for the Anima model. It hooks into the cross-attention layers and combines multiple artist conditionings with controllable strategies, sidestepping the interference that LLM-based text encoders suffer from when multiple artist tags coexist in a single prompt.

The companion `AnimaArtistPack` node provides a one-shot experience: write your artist list in one text box (comma or newline separated) and your main prompt in another. The node automatically splits, encodes, and packages everything for downstream use.

## What problem it solves

Anima uses an LLM as its text encoder (unlike SDXL's CLIP). LLM encoders are heavily **contextualized** — every token's embedding fuses semantics from surrounding tokens. This has a direct consequence:

- Single artist tag: the LLM produces a conditioning that captures that artist's style accurately. Works well.
- Multiple artist tags together: the artist tags' embeddings interfere with each other, and the resulting conditioning ends up looking like neither A nor B but a "squeezed-together" middle ground.

This node encodes each artist as a **separate** conditioning, bypassing the interference at the encoding stage, then mixes them inside the model at the cross-attention level using selectable strategies. Mixing happens in an already-stabilized feature space, where it's far more controllable than mixing at the prompt level.

## How it works

### Anima's structure

Anima = MiniTrainDIT backbone + LLMAdapter text adapter. Text flows like this:

```
Prompt
  → LLM encoder (Qwen, etc.)
  → raw embedding (1, T, 1024)
  → LLMAdapter (6-layer transformer, adapts LLM output to DiT's expected distribution)
  → processed (1, 512, 1024), padded to fixed length 512
  → consumed as K/V by every DiT block's cross-attention
```

The DiT backbone has 28 blocks total, each with its own independent cross-attention layer. The same text conditioning is consumed 28 times across these layers.

### Injection mechanism

The node replaces `diffusion_model.blocks[i].cross_attn` with a wrapper using ComfyUI's `add_object_patch` API. This is clone-safe — it doesn't pollute the original model and is automatically undone when the workflow disconnects.

Each artist conditioning is lazily run through the LLMAdapter on its first forward call (when the model is already on GPU), producing a `(1, 512, 1024)` processed embedding that's cached for reuse across sampling steps.

Each layer's injection is wrapped in exception isolation: if a single layer's injection fails, only that layer falls back to the original cross-attention; other layers continue working normally.

### CFG compatibility

ComfyUI batches cond and uncond into a single `batch=2` forward, with `transformer_options["cond_or_uncond"]` marking each row. This node injects only into the cond rows by default; uncond rows keep their original base context, so CFG guidance is preserved naturally. `apply_to_uncond` defaults to False and is not recommended to enable.

## Mathematical limits of artist mixing

Up front: **this node cannot achieve the near-lossless artist mixing that SDXL does.**

SDXL's CLIP encoder produces approximately linearly composable per-token features. Anima's LLM + LLMAdapter output is **strongly non-linear** — any mixing strategy introduces distortion. What this node does is make distortion as controllable as possible and avoid the worst failure modes, not eliminate it.

In practice:
- Style-similar artists tend to mix well
- Style-divergent artists may "regress to the mean", landing in a compromise that resembles neither A nor B. This is more pronounced with weight normalization on (the default), since features get averaged after being normalized to relative proportions
- Extreme weight ratios (e.g. `"1.0, 0.05"`) typically collapse back to the dominant artist's pure style

## Requirements

- **Anima model only**. Depends on Anima's built-in `LLMAdapter` (`preprocess_text_embeds`); plain MiniTrainDIT or other DiTs won't work
- Must use the **CLIP loader compatible with Anima's text-encoding workflow** (i.e. one whose tokens carry `t5xxl_ids`). `AnimaArtistPack` calls `clip.encode_from_tokens_scheduled` internally
- Inference path only, no training support

## Installation

Clone or download into your ComfyUI `custom_nodes` directory:

```
ComfyUI/custom_nodes/<this-plugin-folder>/
```

Restart ComfyUI. No extra dependencies.

## Quick start

![workflow](docs/images/workflow.png)

```
                          ┌──► artist_pack ──► AnimaArtistCrossAttn ──► MODEL ──► KSampler
[Load CLIP] ─► CLIP ──────┤                              │                          │
                          │                              └──► base_prompt ──► (positive)
                          │
                          └──► CLIPTextEncode (Negative) ──► (negative)

[Load Anima Model] ──► MODEL ──► AnimaArtistCrossAttn

(optional) AnimaArtistOptions ──► advanced_options ──► AnimaArtistCrossAttn
```

Key points:
- Write your artist chain in `AnimaArtistPack`'s top text box (comma or newline separated)
- Write your main prompt in the bottom text box
- Connect `AnimaArtistCrossAttn`'s `base_prompt` output directly to KSampler's positive input
- Encode the negative prompt independently with `CLIPTextEncode`; it does not go through this plugin
- Advanced controls (layer range, sampling-step range, normalization toggle) come via the optional `AnimaArtistOptions` node

## Parameters

### AnimaArtistPack (artist chain split + encode)

| Parameter | Type | Description |
|---|---|---|
| `clip` | CLIP | Anima-compatible CLIP |
| `artist_chain` | STRING (multiline) | Artist chain. Comma or newline separated. Supports CLIP weighting syntax like `(wlop:1.2)` |
| `base_prompt` | STRING (multiline, optional) | Main prompt. Leave empty to encode artists alone |

Outputs `ANIMA_PACK`, an internal struct holding each artist's separately-encoded conditioning, the artist label list, and a separately-encoded conditioning for the bare base prompt.

How it works internally: the node splits `artist_chain` into N artist names and encodes each as `<artist_name>\n<base_prompt>` (Anima's recommended format: artist first, newline, then main prompt). It also encodes a clean copy of `base_prompt` alone for use as KSampler's positive conditioning.

### AnimaArtistCrossAttn (main node)

| Parameter | Type | Description |
|---|---|---|
| `model` | MODEL | Anima model |
| `artist_pack` | ANIMA_PACK | Output from `AnimaArtistPack` |
| `combine_mode` | enum | How multiple artists are merged: `output_avg` (recommended) / `concat` |
| `fusion_mode` | enum | How merged artists act on the main prompt: `interpolate` (recommended) / `concat_with_base` |
| `strength` | FLOAT 0~1 | Overall artist contribution strength |
| `enabled` | BOOLEAN | Master switch |
| `apply_to_uncond` | BOOLEAN | Default False, **not recommended** (breaks CFG) |
| `advanced_options` | ANIMA_OPTS | Optional advanced controls |

Outputs:
- `model`: model with artist mixing patched in. Connect to KSampler's `model` input
- `base_prompt`: the bare base-prompt conditioning from `artist_pack`. Connect to KSampler's positive input

### AnimaArtistOptions (advanced)

Not connecting this node = default behavior. Connecting it makes its settings take effect.

| Parameter | Description |
|---|---|
| `start_block` / `end_block` | Inject only on DiT blocks in `[start, end]`. `end_block = -1` means up to the last block |
| `start_percent` / `end_percent` | Inject only during sampling progress in `[start, end]`. `0.0` = sampling start, `1.0` = end |
| `normalize_weights` | True: weights are normalized to relative proportions. False: weights act as independent strength multipliers (see below) |
| `layer_filter` | Advanced layer-selection string (overrides start_block/end_block). Example: `"0,3,5-10,-1"` = blocks 0, 3, 5 through 10, and the last block |

## Core concepts

### combine_mode: how multiple artists are merged

#### `output_avg` (recommended default)

Each artist runs through cross-attention **independently**, producing N outputs that are then weighted-averaged:

```
out = sum_i (w_i * cross_attn(x, K_i, V_i))
```

Each softmax is computed independently over its own K, V — artists don't compete for attention budget. Mathematically the cleanest mixing strategy. Cost: cross-attention forwards = number of artists.

#### `concat`

Concatenates artist conditionings along the token dimension:

```
K/V = [artist 1's 512 tokens, artist 2's 512 tokens, ...]
out = cross_attn(x, K_concat, V_concat)
```

Single cross-attention call, but all artists compete in the same softmax. The padding zero-vectors at the tail of LLMAdapter outputs are naturally suppressed by attention (no manual masking needed).

Pros: single forward, fast. Cons: attention is shared across artists, typically less expressive than output_avg.

> Earlier versions had `mean` and `weighted_sum` modes (per-position weighted average over LLMAdapter outputs). They were removed: position-i in different artists carries different semantics, so element-wise averaging causes K/V semantic misalignment and inevitably produces broken images. A `replace` mode was also removed: it discards the main prompt's role in cross-attention entirely, severely degrading prompt adherence.

### fusion_mode: how the merged artist acts on the main prompt

#### `interpolate` (recommended with output_avg)

Base and artist each run cross-attention once, then outputs are linearly interpolated by `strength`:

```
out = base_out * (1 - strength) + artist_out * strength
```

Strength is strictly controllable (`strength=0` = pure base, `strength=1` = pure artist). Smooth transitions, minimal style drift. Cost: one extra base forward per layer.

#### `concat_with_base`

Cross-attention's K/V becomes `[base_tokens, artist_tokens]`, letting attention see both base and artist:

```
K = [K_base, K_artist]
V = [V_base, V_artist]
out = cross_attn(x, K, V)
```

The softmax decides per-pixel-position whether to attend to base or artist. With `strength < 1`, the result is mixed once more with a pure-base output.

Pros: base prompt stays in the attention computation, so prompt adherence is best preserved. Artist still dominates style, but with the lightest drift.

## Recommended combination

For day-to-day use:

```
combine_mode = output_avg
fusion_mode  = interpolate
strength     = 0.6 ~ 0.8
```

To control individual artist strength within the chain, use CLIP weighting syntax inside `artist_chain`:

```
wlop, (sakimichan:1.2), (krenz:0.7)
```


## Performance notes

### Computational cost

In `output_avg` mode, each layer runs `N + 1` cross-attention forwards (N artists + base). This is mathematical necessity:

```
sum_i (w_i * softmax(Q @ K_i^T / √d) @ V_i)
```

Each softmax must be computed independently over its own K, V. Merging into a single large attention would degrade the semantics to `concat` mode.

### Approximate timing (30 steps, varies by GPU)

| Artist count | Relative time |
|---|---|
| 1 | 1.0x (baseline) |
| 4 | ~1.4x |
| 8 | ~1.7x |

**More artists means more time** — there's no way to eliminate this fundamental cost.

### Strongly recommended: use layer range and step range to reduce cost

After connecting `AnimaArtistOptions`, you can **dramatically cut generation time** with usually minimal quality loss:

- **Layer range** (`start_block / end_block` or `layer_filter`): inject only on specific DiT blocks. `0..13` (front half) cuts time roughly in half. Artist style is mostly determined by early blocks, so the loss is usually acceptable
- **Sampling-step range** (`start_percent / end_percent`): inject only during a portion of sampling. `0.0..0.5` (first half) similarly cuts time, since artist style is mostly absorbed during early sampling

Both can be **combined**: "front-half layers + front-half sampling" can bring 8-artist scenarios back to near-single-artist timing. This is the most effective optimization for multi-artist setups.

## How to write the artist chain

### Recommended format: artist on top, main prompt separate

The two text boxes of `AnimaArtistPack` have distinct roles:

```
artist_chain (top box):
  wlop
  (sakimichan:1.2)
  krenz

base_prompt (bottom box):
  masterpiece, 1girl, standing, in a forest, ...
```

Internally the node concatenates each as `<artist_name>\n<base_prompt>` before encoding — Anima's empirically most stable format. You don't need to repeat artist names in the main prompt.

Weight controls:
- Inside `artist_chain`, use CLIP weighting `(name:weight)` to adjust individual artist strength
- Overall artist contribution is controlled by `AnimaArtistCrossAttn`'s `strength`
- Whether multi-artist weights are normalized is controlled by `AnimaArtistOptions.normalize_weights`

## Advanced options in detail

After connecting `AnimaArtistOptions`:

### Layer range (`start_block` / `end_block`)

DiT blocks at different depths correspond to different semantic levels: early blocks affect overall composition and style, later blocks affect detail and texture. For example:

- `0..13` (front half): artist dominates composition; details are filled in by the model
- `14..27` (back half): only inject into detail layers; composition follows the main prompt

### `layer_filter` (more flexible layer selection)

A string with **higher priority than `start_block / end_block`** (overrides them when set). Syntax:

- Comma-separated indices: `"0,3,7"`
- Ranges with hyphen: `"5-10"`
- Negative indices (counted from end): `"-1"` = last block
- Mix: `"0,3,5-10,-1"`

Useful for non-contiguous patterns like "early + last only" or interval injection experiments.

### Sampling-step range (`start_percent` / `end_percent`)

Different sampling stages determine different image content (high sigma = composition, low sigma = texture refinement). For example:

- `0.0..0.5`: inject only in the first half; artist sets the overall layout, then the model is free to refine details
- `0.3..1.0`: skip the very early steps to avoid the artist pushing composition too hard

Implementation detail: the node uses `set_model_unet_function_wrapper` to capture the current sigma at each `apply_model` call, then maps user-set percent ranges to sigma ranges via `model_sampling.percent_to_sigma()`.

### Important note when `normalize_weights = False`

Default `normalize_weights = True`: in `output_avg`, N artists' weights are normalized to `1/N` each, so **total contribution always equals 1**.

With normalization off: each artist contributes at its raw weight. **Total contribution = N**, which exceeds the model's training distribution and produces pure noise.

The node intercepts dangerous configurations:

| Artist count + normalize=False | Behavior |
|---|---|
| 1 artist | Normal (equivalent to normalized) |
| 2~3 artists | Warning, but allowed (may overexpose) |
| 4+ artists | **Hard error**, with three suggested fixes |

If you actually want "one artist weakened", the **recommended approach is to keep normalize_weights=True** and use CLIP weighting in `artist_chain` to lower a specific artist:

```
wlop, (krenz:0.3)
```

This keeps wlop dominant with a krenz accent, without breaking total-contribution stability.

## Two layers of weighting

There are **two independent** weighting points in practice:

1. **CLIP weighting** (`(name:1.2)` syntax inside `artist_chain`): scales token embeddings before they pass through the LLMAdapter (a non-linear 6-layer transformer). Outcome isn't strictly predictable but stays close to the LLM's natural output distribution
2. **Node `strength`**: scales the overall artist contribution relative to base in cross-attention output space, with strict proportionality

Different mechanisms: CLIP weighting adjusts "relative strength within the artist chain"; `strength` adjusts "overall artist vs main prompt ratio". Use them independently or together.

## Known issues

### `model_function_wrapper` chain conflicts

When sampling-step range is enabled (`start_percent > 0` or `end_percent < 1`), this node uses `set_model_unet_function_wrapper` to capture per-step sigma. The implementation is chain-safe — it preserves and forwards calls to any pre-existing wrapper.

However, if another custom node connected **after** this one sets a wrapper without chain-safety (overwriting blindly), the sigma capture is lost, and step-range control silently degrades to "always inject".

Diagnosis: reset both percent values to 0.0 / 1.0 to recover normal behavior.

## Future optimization directions

In rough priority order, for future contributors. Technical sketches in `OPTIMIZATION_NOTES.md`.

1. **Promote existing `start_percent / end_percent` usage**: zero-cost lazy injection — currently the highest-value optimization in the architecture
2. **Re-enable batched parallel forward**: combine N artist forwards into a single batch=N call, restoring previously-removed optimization (needs stability validation)
3. **Attention-output deferred cache** (medium complexity): accumulate artist injection contribution during early sampling, reuse as a static bias later. Expected ~1.5-2x speedup
4. **K/V projection cross-step cache** (medium complexity, low payoff): ~1.1x speedup
5. **Adaptive injection schedule** (research level)

Issues / PRs welcome.

## Acknowledgements

Special thanks to **汐浮尘** for co-development, testing, and design contributions during the development of this node. The `AnimaArtistPack` split-and-encode design comes from their improvement.

## License

MIT License. See [LICENSE](LICENSE) for the full text.

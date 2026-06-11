"""Shared constants for the Anima Artist Mixer node pack."""

FUSION_INTERPOLATE = "interpolate"
FUSION_CONCAT_WITH_BASE = "concat_with_base"
FUSION_BASE_PRESERVE = "base_preserve"

FUSION_CHOICES = [
    FUSION_INTERPOLATE,
    FUSION_CONCAT_WITH_BASE,
    FUSION_BASE_PRESERVE,
]

COMBINE_CONCAT = "concat"
COMBINE_OUTPUT_AVG = "output_avg"
COMBINE_LOWRANK_AVG = "lowrank_avg"
COMBINE_EMBED_AVG = "embed_avg"

COMBINE_CHOICES = [
    COMBINE_CONCAT,
    COMBINE_OUTPUT_AVG,
    COMBINE_LOWRANK_AVG,
    COMBINE_EMBED_AVG,
]

MAX_ARTISTS = 32

# Linear injection weight range (supports negative weights for style subtraction).
WEIGHT_MIN = -4.0
WEIGHT_MAX = 4.0

STATIC_CAPTURE_K_DEFAULT = 6   # default step count for the H' temporal average
STATIC_CAPTURE_K_MAX = 12      # UI upper bound

ANCHOR_SEED = 42                          # default single-anchor seed
ANCHOR_SEEDS_POOL = [42, 100, 200, 300]   # seeds used when averaging multiple anchors
ANCHOR_SEEDS_MAX = 4                      # UI upper bound = len(ANCHOR_SEEDS_POOL)
ANCHOR_LAYER_THRESHOLD_DISABLED = -1      # -1 means every layer uses the anchor Q

PRESET_BALANCED = "balanced"
PRESET_STRONG_STYLE = "strong_style"
PRESET_STABLE_SEED = "stable_seed"
PRESET_FAST_PREVIEW = "fast_preview"
PRESET_IDENTITY_GUARD = "identity_guard"
PRESET_COMPATIBILITY_SAFE = "compatibility_safe"

PRESET_CHOICES = [
    PRESET_BALANCED,
    PRESET_STRONG_STYLE,
    PRESET_STABLE_SEED,
    PRESET_FAST_PREVIEW,
    PRESET_IDENTITY_GUARD,
    PRESET_COMPATIBILITY_SAFE,
]

LAYER_MODE_AUTO = "auto"
LAYER_MODE_ALL = "all_layers"
LAYER_MODE_STYLE_CORE = "style_core"
LAYER_MODE_DETAIL = "detail_layers"
LAYER_MODE_CUSTOM = "custom"

LAYER_MODE_CHOICES = [
    LAYER_MODE_AUTO,
    LAYER_MODE_ALL,
    LAYER_MODE_STYLE_CORE,
    LAYER_MODE_DETAIL,
    LAYER_MODE_CUSTOM,
]

CHAIN_LAYOUT_MANUAL = "manual"
CHAIN_LAYOUT_EVEN_LAYERS = "even_layers"
CHAIN_LAYOUT_LAYER_SCHEDULED = "layer_scheduled"

CHAIN_LAYOUT_CHOICES = [
    CHAIN_LAYOUT_MANUAL,
    CHAIN_LAYOUT_EVEN_LAYERS,
    CHAIN_LAYOUT_LAYER_SCHEDULED,
]

DEFAULT_NUM_BLOCKS = 28  # Anima/MiniTrainDIT default DiT block count

RECIPE_FORMAT = "anima-artist-recipe"
RECIPE_VERSION = 1

# Bug Analysis: Multiple Sampler Error

## Issue Report
**Source**: https://github.com/An1X3R/Anima-Artist-Mixer/pull/4#issuecomment-4751557113  
**User**: Euphoric  
**Error**: `AttributeError: 'Attention' object has no attribute 'original'`

## Root Cause Analysis

### User's Workflow Structure
```
UNETLoader (Node 8)
    ├─ Link 212 → AnimaArtistCrossAttn (Node 87) → KSampler (Node 18) [with mixer]
    └─ Link 270 → KSampler (Node 115)              [bypass mixer]
```

### The Problem

**What happens**:
1. UNETLoader creates a model object
2. This model is sent to TWO destinations:
   - Path A: Through AnimaArtistCrossAttn (patches applied)
   - Path B: Direct to KSampler (no patches)

**Why it fails**:

The patching code in `nodes_core.py` line 691-696:
```python
for i in target_blocks:
    inner = unwrap_cross_attn_forward(unwrap_cross_attn(dm.blocks[i].cross_attn))
    wrapper = CrossAttnWrapper(inner, state, i)
    m.add_object_patch(
        f"diffusion_model.blocks.{i}.cross_attn.forward",
        make_cross_attn_forward_patch(wrapper),
    )
```

**The issue**: 
- `m.clone()` in ComfyUI performs a **shallow clone** of the diffusion_model
- `dm.blocks[i].cross_attn` is the **SAME object** in both the original and cloned model
- When we patch `cross_attn.forward` via `add_object_patch()`:
  - It patches the forward method on the shared object
  - Both the patched model AND the original model see the patch
- KSampler 115 (bypass path) receives a model with patched cross_attn
- On re-execution or second sampler run, the patch logic fails

**Error mechanism**:
```python
# patching.py line 54-56
def unwrap_cross_attn_forward(ca):
    forward = getattr(ca, "forward", None)
    while isinstance(forward, CrossAttnForwardPatch):
        forward = forward.original_forward  # ← This line fails
    return forward
```

If `forward` is a `CrossAttnForwardPatch` but `original_forward` is missing or corrupted, we get:
```
AttributeError: 'Attention' object has no attribute 'original'
```

## Recommended Fix

```python
# nodes_core.py line 690-696
for i in target_blocks:
    ca = dm.blocks[i].cross_attn
    current_forward = getattr(ca, 'forward', None)
    
    # Check if already patched by this code
    if hasattr(current_forward, '_anima_artist_mixer_forward_patch'):
        # Already patched - unwrap to get the true original
        inner = unwrap_cross_attn_forward(ca)
    else:
        # Not yet patched - proceed normally
        inner = unwrap_cross_attn_forward(unwrap_cross_attn(ca))
    
    wrapper = CrossAttnWrapper(inner, state, i)
    m.add_object_patch(
        f"diffusion_model.blocks.{i}.cross_attn.forward",
        make_cross_attn_forward_patch(wrapper),
    )
```

## Testing Required

**Test with**: `I:\ComfyUI-aki-v1.6\ComfyUI`

1. Load `user_workflow_issue.json`
2. Reproduce the error
3. Apply fix
4. Verify both samplers work correctly

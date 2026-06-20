# Test Plan for PR #4 Bug Report

## Issue Summary
User "Euphoric" reported two problems with PR #4:
1. `AttributeError: 'Attention' object has no attribute 'original'` when using multiple samplers
2. Artist `@yuchi \(salmon-1000\)` produces results that don't look like the artist

Source: https://github.com/An1X3R/Anima-Artist-Mixer/pull/4#issuecomment-4751557113

---

## Problem 1: Multiple Sampler Error

### Root Cause Analysis
The user's workflow structure:
```
UNETLoader (Node 8)
    ├─ Link 212 → AnimaArtistCrossAttn (Node 87) → KSampler (Node 18)
    └─ Link 270 → KSampler (Node 115)
```

**Issue**: Same model object is referenced by both samplers
- When `AnimaArtistCrossAttn` patches the model, it modifies the shared object
- The second sampler receives an already-patched model
- On re-execution, the patching logic fails because it expects unpatch state

### Code to Review

File: `anima_mixer/patching.py`

Check the `make_cross_attn_forward_patch` function and verify:
1. Does it check if attention is already patched before patching?
2. Does it properly store `original` attribute?
3. Does it handle re-patching gracefully?

### Test Case 1.1: Reproduce the Error

**Setup**:
1. Load Anima model with UNETLoader
2. Split model connection:
   - Path A: Model → AnimaArtistCrossAttn → KSampler A
   - Path B: Model → KSampler B (bypass mixer)
3. Run workflow

**Expected Error** (if bug exists):
```
AttributeError: 'Attention' object has no attribute 'original'
```

**Where to test**: I:\ComfyUI-aki-v1.6\ComfyUI

### Test Case 1.2: Verify Fix

After fixing the code, the workflow should:
- ✅ Run without errors
- ✅ KSampler A produces images with artist style
- ✅ KSampler B produces images without artist style
- ✅ Both samplers execute successfully

---

## Problem 2: Artist Style Not Applied

### User's Claim
> "when I try artist `@yuchi \(salmon-1000\)` and run it through both with and without the Mixer, the mixer one looks nothing like neither the artist nor the non-mixer version"

### Possible Causes
1. **Escaping issue**: `@yuchi \(salmon-1000\)` might not be parsed correctly
2. **Artist name not found**: The artist might not exist in the model's training data
3. **Weight/preset issue**: Wrong preset or weight configuration
4. **Patching issue**: Cross-attention patch not actually applying

### Test Case 2.1: Artist Name Parsing

**Test the parsing**:
```python
from anima_mixer.parsing import split_artist_chain

# Test with escaped parentheses
chain1 = "@yuchi \\(salmon-1000\\)"
chain2 = "yuchi (salmon-1000)"
chain3 = "@yuchi (salmon-1000)"

for chain in [chain1, chain2, chain3]:
    artists = split_artist_chain(chain)
    print(f"Input: {chain}")
    print(f"Parsed: {artists}")
```

**Expected**: Should correctly parse artist name

### Test Case 2.2: Baseline Comparison

**Setup**:
1. Create 3 workflows:
   - A: No artist at all (pure base model)
   - B: Artist in prompt directly: "yuchi (salmon-1000), [base prompt]"
   - C: Artist via mixer: `@yuchi (salmon-1000)` in AnimaArtistPack

**Test**:
- Same seed, same prompt, same settings
- Generate images from all 3 workflows
- Compare visually

**Expected**:
- A: No artist style
- B: Artist style (LLM-encoded, may interfere with prompt)
- C: Artist style (cross-attention mixed, should be cleaner)

**If C looks like A**: Mixer is not applying the artist
**If C looks different from both A and B**: Unexpected behavior

### Test Case 2.3: Inspector Check

**Use AnimaArtistInspector**:
```
AnimaArtistPack → AnimaArtistInspector
```

Check the inspector output:
- ✅ Is `yuchi (salmon-1000)` parsed correctly?
- ✅ What is the effective weight?
- ✅ Are there any warnings?
- ✅ What preset is being used?

### Test Case 2.4: Probe Analysis

**Use AnimaArtistProbe** (if artist style seems weak):
```
Model → AnimaArtistProbe → KSampler
        → AnimaArtistProbeReport
```

Check:
- Which layers show artist influence?
- Is the influence too weak (all values near 0)?
- What layer routing is recommended?

---

## Test Environment

**Required**:
- ComfyUI: I:\ComfyUI-aki-v1.6\ComfyUI
- Anima model: (confirm model path)
- This PR's code: L:\Antigravitiy code\comfyui\Anima-Artist-Mixer

**Test System**:
- OS: Windows
- GPU: (specify)
- Python version: (specify)
- ComfyUI version: (specify)

---

## Test Execution Checklist

### Pre-test
- [ ] Backup current workflows
- [ ] Confirm Anima model is loaded correctly
- [ ] Verify this PR's code is active in ComfyUI

### Test 1: Multiple Sampler Error
- [ ] Download user's workflow: `user_workflow_issue.json`
- [ ] Load into ComfyUI
- [ ] Attempt to run
- [ ] Document error message (screenshot + text)
- [ ] Check console logs for full traceback

### Test 2: Fix Verification
- [ ] Review `anima_mixer/patching.py`
- [ ] Implement fix (if needed)
- [ ] Re-run user's workflow
- [ ] Verify both samplers work
- [ ] Compare outputs visually

### Test 3: Artist Style Investigation
- [ ] Test artist name parsing (run Python script)
- [ ] Create baseline comparison workflows (A/B/C)
- [ ] Generate images with same seed
- [ ] Visual comparison
- [ ] Use Inspector to check parsing
- [ ] Use Probe to check layer influence

### Documentation
- [ ] Take screenshots of all test results
- [ ] Save generated images with clear labels
- [ ] Document any errors with full tracebacks
- [ ] Note which tests pass/fail

---

## Expected Deliverables

1. **Test Results Document**:
   - Screenshots of error (if reproduced)
   - Screenshots of fixed behavior
   - Generated images for visual comparison
   - Inspector outputs
   - Probe reports

2. **Code Fix** (if needed):
   - Modified `patching.py` or other files
   - Explanation of the fix
   - Test case demonstrating the fix works

3. **Response to User**:
   - Clear explanation of the issue
   - Fix implemented or workaround provided
   - Request for user to re-test

---

## Notes

- Do NOT trust old evidence in `pr_evidence/` folder (outdated)
- All claims must be verified with actual testing
- If we cannot reproduce the issue, ask user for more details:
  - Exact model version
  - ComfyUI version
  - Full console log
  - Screenshots

---

## Testing Priority

1. **HIGH**: Fix the multiple sampler error (blocking issue)
2. **HIGH**: Verify artist style is actually applied
3. **MEDIUM**: Optimize for edge cases
4. **LOW**: Performance testing

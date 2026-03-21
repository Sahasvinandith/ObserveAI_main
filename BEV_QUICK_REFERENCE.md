# BEV Fixes: Quick Reference

## TL;DR

**Problem:** Persons appearing at camera position instead of actual location  
**Cause:** Using bbox center (head) instead of bbox bottom (feet) for ground projection  
**Fix:** Change one line in HomographyProjector.py  
**Result:** Persons should now appear at correct map locations

---

## What Was Changed

**File:** `components/HomographyProjector.py` Line 172  

```python
# OLD (WRONG):
cy_bottom = cy_frame  # Using center of bbox

# NEW (CORRECT):
cy_bottom = bbox[1] + bbox[3]  # Using bottom of bbox (feet on ground)
```

---

## Why It Matters

- **Homography** projects 2D frame coords → ground plane (Z=0)
- **Must use feet position** (bottom of bbox), not head (center)
- Head is 1.8m above ground, feet are on ground
- Off by 1-2 meters if using center instead of bottom

---

## Test It

### Quick Test (1 minute)
```bash
python -m py_compile components/HomographyProjector.py && echo "✓ OK"
```

### Debug Test (5 minutes)
```bash
python debug_bev_projection.py | tail -30
# Look for: Frame projections should NOT all be at camera position
```

### Visual Test (10 minutes)
```bash
python main.py
# Load Modifide.json → Open BEV → Enable debug → Stand in front of camera
# Should see: Person dots MOVE with you, not stuck at camera
```

---

## Expected Results

### BEFORE FIX ❌
```
Person stands at (140, 110)
  Camera projects: (243.5, 56.0)  ← AT CAMERA - WRONG!
```

### AFTER FIX ✅
```
Person stands at (140, 110)
  Cheap camera projects: (142, 112)  ✓
  HD camera projects:    (138, 108)  ✓
  Stereo global:         (140, 110)  ✓ MATCHES!
```

---

## Files Modified
- ✅ `components/HomographyProjector.py` (1 line changed)

## Documentation Created
- `BEV_AUDIT_REPORT.md` - Full analysis
- `BEV_FIXES_SUMMARY.md` - What was fixed
- `BEV_BEFORE_AFTER_ANALYSIS.md` - Detailed comparison
- `debug_bev_projection.py` - Test script
- `debug_homography_detailed.py` - Debug script

---

## If It Still Doesn't Work

**Check (in order):**
1. Camera calibration: Are position/rotation values correct?
2. Face detection: Is bbox accurate?
3. Both cameras: Are both detecting the person?
4. Stereo triangulation: Check GlobalPersonTracker algorithm

---

## Questions?

See `BEV_AUDIT_REPORT.md` for complete technical analysis.


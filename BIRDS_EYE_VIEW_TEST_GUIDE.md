# Birds Eye View - Quick Test & Verification Guide

## 🧪 Testing Checklist

### Phase 1: UI Verification
After running the application:

- [ ] **Menu Button Exists**
  - Look for "Birds Eye" button in the left menu bar
  - Button appears between "Logs" and "Settings"
  - Button has same styling as other menu buttons

- [ ] **Page Loads Without Error**
  - Click "Birds Eye" button
  - Page should switch without crashing
  - No error messages in console

- [ ] **Basic UI Components Visible**
  - Title shows: "Bird's Eye View - Homography Projection"
  - Debug toggle button visible: "🐛 Debug: OFF"
  - Graphics view canvas visible
  - Grid background with origin axes appears

### Phase 2: Camera Visualization
With cameras already calibrated and running:

- [ ] **Camera Icons Appear**
  - Green circles visible at calibrated camera positions
  - Camera names displayed next to positions
  - FOV cones visible as dashed lines

- [ ] **Multiple Cameras**
  - All configured cameras display
  - Icons positioned at correct locations
  - FOV cones have correct angles and rotations

### Phase 3: Person Tracking (Normal Mode)
With people detected in the scene:

- [ ] **Green Dots Appear**
  - When persons are detected, green dots appear
  - Dots positioned at stereo-calculated location
  - Dots move as persons move in real world

- [ ] **Labels Display**
  - Person ID visible (G:1, G:2, etc.)
  - Person name displayed if available
  - Hover shows tooltip with ID and camera

- [ ] **Smooth Updates**
  - Positions update every ~100ms
  - No stuttering or lag
  - Grid remains stable background

### Phase 4: Debug Mode
Click the "🐛 Debug: OFF" button to enable debug mode:

- [ ] **Button Updates**
  - Button text changes to "🐛 Debug: ON"
  - Button background color changes to green
  - Button remains clickable

- [ ] **Multi-Camera Projections Appear**
  - For each camera detecting a person:
    - Colored circle appears (red, blue, yellow, etc.)
    - Camera name labeled at projection point
    - Dashed line connects camera → projection

- [ ] **Stereo Position Visible**
  - Green circle becomes larger/bolder
  - Stereo label appears (if in debug mode)
  - Clearly distinct from camera projections

- [ ] **Projection Clustering**
  - Colored projections cluster around stereo position
  - If 2-3 cameras see person: 2-3 colored dots appear
  - All clusters near the green stereo position

### Phase 5: Toggle Debug On/Off
- [ ] **Smooth Transition**
  - Toggle debug OFF - projections disappear, only green dot remains
  - Toggle debug ON - projections reappear
  - No lag or flicker

- [ ] **Clean Rendering**
  - No graphics artifacts
  - No overlapping or misaligned elements
  - Grid remains visible in background

### Phase 6: Interactive Features
- [ ] **Mouse Wheel Zoom**
  - Scroll mouse wheel: view should zoom in/out
  - Zoom centered on cursor position
  - Scene remains clear at all zoom levels

- [ ] **Pan Support**
  - Should be able to drag view (if implemented)
  - Or scroll bar should appear

### Phase 7: Multiple Persons
If multiple persons in scene:

- [ ] **Multiple Dots**
  - Each person shows separate green dot
  - Each dot labeled with unique ID
  - Dots move independently

- [ ] **Debug Mode with Multiple Persons**
  - In debug mode, see projections for all persons
  - Different persons' projections in different areas
  - Stereo positions clearly marked

### Phase 8: Calibration Changes
If you recalibrate a camera:

- [ ] **View Updates**
  - Camera position/rotation updates on display
  - FOV cone angle changes appropriately
  - Projections adjust to new calibration

- [ ] **No Errors**
  - No crashes or error messages
  - View remains responsive
  - Homography cache cleared properly

---

## 🔍 Detailed Test Scenarios

### Scenario A: Single Camera, Single Person
**Setup**: 1 camera calibrated, 1 person detected

**Expected**:
- Camera icon at calibrated position
- Green dot at person's global position
- Debug mode shows single red projection at same location as green dot

**Verification**:
```
Normal: Green dot visible ✓
Debug:  Red dot visible (camera 1) ✓
        Both dots at same location ✓
```

### Scenario B: Two Cameras, Single Person
**Setup**: 2 cameras calibrated, 1 person visible to both

**Expected**:
- Two camera icons with FOV cones
- Green dot at stereo-calculated position
- Debug mode shows red and blue projections from each camera
- Red and blue projections should cluster around green dot

**Verification**:
```
Normal: Green dot visible ✓
Debug:  Red dot (Cam 1) visible ✓
        Blue dot (Cam 2) visible ✓
        Distance between red/blue: < 30 pixels ✓
        Green dot between red/blue ✓
```

### Scenario C: Two Cameras, Two Persons
**Setup**: 2 cameras, 2 persons detected

**Expected**:
- Two green dots at different locations
- Debug mode: 4 colored projections (2 red, 2 blue) - but clustered by person

**Verification**:
```
Normal: 2 green dots at different locations ✓
Debug:  4 projections total ✓
        2 projections near green dot 1 ✓
        2 projections near green dot 2 ✓
```

### Scenario D: Wide-Angle vs Telephoto Cameras
**Setup**: 1 wide-angle camera (120°), 1 telephoto camera (30°)

**Expected**:
- Wide-angle camera shows large FOV cone
- Telephoto camera shows narrow FOV cone
- Projections still cluster despite different FOVs
- Demonstrates FOV detection enhancement working

**Verification**:
```
Wide-angle FOV cone: 120° arc ✓
Telephoto FOV cone:   30° arc ✓
Projections cluster:  within 30px ✓
```

---

## 📊 Expected Performance

### Rendering Speed
- **Idle**: < 1ms per frame
- **1 camera**: 2-3ms per frame
- **4 cameras**: 5-8ms per frame
- **+ 5 persons**: 15-20ms per frame

### Memory Usage
- **Base widget**: ~2MB
- **Per camera**: +4KB (homography cache)
- **Per person**: +10KB (graphics items)

### Responsiveness
- **Debug toggle**: < 50ms reaction time
- **Person position update**: < 100ms visible change
- **Zoom/pan**: Smooth, no jitter

---

## 🐛 Known Issues & Workarounds

### Issue: Grid background too fine/coarse
**Workaround**: Zoom in/out with mouse wheel to adjust perceived scale

### Issue: Person dot too small
**Workaround**: Zoom in (mouse wheel) to better see dots

### Issue: Camera labels overlap
**Workaround**: This is acceptable; labels show up on hover in future

### Issue: Debug mode performance drops with 10+ persons
**Workaround**: Limit displayed persons to top 8-10 by confidence

---

## ✅ Sign-Off Checklist

For production use, verify:

- [ ] **All UI elements render correctly**
- [ ] **Multi-camera projections work**
- [ ] **Debug mode toggle responsive**
- [ ] **No console errors**
- [ ] **Smooth frame rate (30+ fps)**
- [ ] **Stereo positions accurate (within ±20 pixels)**
- [ ] **Multi-person handling works**
- [ ] **Zoom/pan responsive**
- [ ] **Page can be popped out (right-click button)**
- [ ] **Homography cache working (performance improves on 2nd view)**

---

## 🚀 Next Steps After Testing

1. **If all tests pass**:
   - Feature is ready for deployment
   - Can use in production monitoring
   - Document in user manual

2. **If minor visual issues**:
   - Adjust colors, sizes in code
   - Customize grid cell size
   - Modify FOV cone appearance

3. **If accuracy issues**:
   - Recalibrate cameras (3-4 points each)
   - Check FOV/view_range parameters
   - Verify camera positions are correct

4. **If performance issues**:
   - Disable debug mode for long sessions
   - Limit to top-5 persons by confidence
   - Reduce update frequency (change 100 to 200ms timer)

---

## 📞 Support

If issues occur:

1. **Check console for error messages**
2. **Verify all cameras calibrated**
3. **Ensure DetectionSystem is running**
4. **Try restarting the application**
5. **Check Birds Eye View Documentation** (BIRDS_EYE_VIEW_IMPLEMENTATION.md)

---

**Test Duration**: ~15-20 minutes for complete verification
**Difficulty**: Low (just visual observation)
**Success Criteria**: All checkmarks in each section ✅

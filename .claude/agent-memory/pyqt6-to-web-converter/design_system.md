---
name: Design System and Color Tokens
description: Dark theme color palette and CSS design decisions for ObserveAI web UI
type: project
---

# ObserveAI Web Design System

## Base Palette (matching original purple/dark surveillance aesthetic)
- Background base: #0f0a14 (deeper than original rgb(39,7,40))
- Surface: #1a0f1f (cards, panels)
- Surface elevated: #261530 (modals, dropdowns)
- Border: #4a1d5e (subtle)
- Border active: #7a3a8a (original brand color from PyQt6 styles)
- Accent primary: #7a3a8a (purple, matches original dialog styles)
- Accent hover: #9a50aa
- Text primary: #ffffff
- Text secondary: #cccccc
- Text muted: #888888
- Success/connected: #00ff88 (green, used in action log)
- Warning: #ffaa00
- Error/alert: #ff4444
- Camera tile bg: #000000

## Typography
- Font: system-ui, -apple-system, sans-serif (no external font dependency)
- Mono: 'Courier New', monospace (logs, timestamps)

## Spacing
- Base unit: 4px
- Camera tile gap: 8px
- Panel padding: 16px
- Modal padding: 24px

## Component Decisions
- Camera tiles: dark border, camera name in title bar with status dot
- Status dots: green=connected, red=disconnected, yellow=reconnecting
- Toast notifications: top-right, matches original _show_notification() style (dark bg, green text, purple border)
- Sidebar: fixed left, 200px wide, icon+label nav items
- Settings sliders: custom-styled range inputs matching the purple theme

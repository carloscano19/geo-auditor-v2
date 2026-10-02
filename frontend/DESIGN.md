# Design System Tokens — LLM Dashboard Reference

This document catalogs the exact design tokens extracted from `/Users/carloscano/Desktop/Carlos apps/LLM-dashboard` (specifically `app/globals.css`, `app/layout.tsx`, `app/login/page.tsx`, and `app/page.tsx`) to be replicated in the GEO-AUDITOR frontend redesign.

---

## 1. Palette & Colors

### Base Backgrounds & Text
- **Page background**: `#f1f5f9` (Tailwind `slate-100` / `bg-[#f1f5f9]`)
  - *Source*: `app/globals.css:12`, `app/page.tsx:356`, `app/login/page.tsx:149`
- **Surface / Cards**: `#ffffff` (White cards: `bg-white border border-slate-200` or `border-slate-200/90`)
  - *Source*: `app/page.tsx:367`, `app/page.tsx:752`, `app/page.tsx:931`, `app/login/page.tsx:61`
- **Surface Muted / Inputs**: `bg-slate-50` with `border-slate-200` or `border-slate-300`
  - *Source*: `app/page.tsx:783`, `app/page.tsx:890`, `app/login/page.tsx:84`
- **Primary Text**: `#0f172a` (Tailwind `text-slate-900`)
  - *Source*: `app/globals.css:13`, `app/page.tsx:356`, `app/page.tsx:379`
- **Secondary Text**: `text-slate-700` / `text-slate-600`
  - *Source*: `app/page.tsx:428`, `app/page.tsx:762`, `app/page.tsx:775`
- **Muted Text / Meta**: `text-slate-500` / `text-slate-400`
  - *Source*: `app/page.tsx:382`, `app/page.tsx:403`, `app/page.tsx:441`, `app/login/page.tsx:55`

### Brand Accent (Red)
- **Brand Red Primary**: `bg-red-600` / `text-red-600` / `border-red-600` (`#dc2626`)
  - *Hover*: `hover:bg-red-500`
  - *Active*: `active:bg-red-700` or `active:scale-[0.98]`
  - *Shadow*: `shadow-sm shadow-red-600/20` or `shadow-red-600/30`
  - *Source*: `app/page.tsx:375`, `app/page.tsx:841`, `app/login/page.tsx:49`, `app/login/page.tsx:119`
- **Active Navigation Pill (Light Red)**:
  - Background: `bg-red-50/70`
  - Border: `border-red-200`
  - Text: `text-red-700`
  - Icon: `text-red-600`
  - Subtitle: `text-red-700/80`
  - Shadow: `shadow-xs`
  - *Source*: `app/page.tsx:418-444`

### State & Badges
- **Success / Active / Connected (Emerald)**:
  - Badge container: `bg-emerald-50 border border-emerald-200 text-emerald-700`
  - Pulsing dot: `w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse`
  - *Source*: `app/page.tsx:459-463`, `app/page.tsx:603-605`, `app/login/page.tsx:138`
- **Warning / Moderate (Amber)**:
  - Container: `bg-amber-50 border border-amber-200 text-amber-800`
  - Dot: `bg-amber-500`
  - *Source*: `app/page.tsx:514-534`, `app/page.tsx:567-576`
- **Critical / Danger / Disconnected (Red / Gray)**:
  - Error alert: `bg-red-50 border border-red-200 text-red-700`
  - Inactive / Disconnected badge: `bg-slate-100 border border-slate-200 text-slate-500` with `bg-slate-400` dot
  - *Source*: `app/page.tsx:870`, `app/login/page.tsx:108`
- **Neutral Pills / Badges**:
  - `bg-slate-100 border border-slate-200 text-slate-700` or `text-slate-600`
  - *Source*: `app/page.tsx:600`, `app/page.tsx:766`, `app/page.tsx:947`

---

## 2. Typography

- **Font Family**:
  - Sans: `-apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", Roboto, sans-serif`
  - Mono: `ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "JetBrains Mono", monospace`
  - *Source*: `app/globals.css:4`
- **Font Sizes & Weights**:
  - Brand Title: `text-sm font-bold tracking-tight text-slate-900`
  - Brand Subtitle: `text-[11px] font-medium text-slate-500`
  - Sidebar Section Header: `text-[10px] font-bold uppercase tracking-wider text-slate-400`
  - Nav Item Label: `text-xs font-semibold text-slate-700` (active: `text-slate-900 font-bold`)
  - Nav Item Subtitle: `text-[11px] text-slate-400` (active: `text-red-700/80 font-medium`)
  - Header Breadcrumb / Title: `text-sm sm:text-base font-semibold tracking-tight text-slate-900`
  - Header Subtitle: `text-xs text-slate-500`
  - Card Title: `text-lg sm:text-xl font-bold text-slate-900 tracking-tight`
  - Card Subtitle: `text-sm text-slate-600 leading-relaxed`
  - Section Headings: `text-sm sm:text-base font-bold text-slate-900`
  - Table Header: `text-xs font-bold text-slate-700 uppercase tracking-wider bg-slate-100`
  - Table Body: `text-sm text-slate-900` / `text-slate-600`

---

## 3. Radii, Shadows & Borders

- **Border Radii**:
  - Modals / Main Cards: `rounded-2xl` (`16px`)
  - Nav items, inputs, tables, nested cards: `rounded-xl` (`12px`)
  - Buttons, form controls, alert boxes: `rounded-lg` (`8px`) or `rounded-xl`
  - Badges / Pills: `rounded-full` (`9999px`)
  - Brand Logo Icon: `rounded-lg` (`8px`)
- **Borders**:
  - Default light border: `border border-slate-200` (`#e2e8f0`)
  - Input border: `border border-slate-300` or `border-slate-200`
  - Active / Focus ring: `focus:ring-2 focus:ring-red-500/20 focus:border-red-500`
- **Shadows**:
  - Subtle card shadow: `shadow-sm shadow-slate-200/50` or `shadow-xs`
  - Button shadow: `shadow-sm shadow-red-600/20`
  - Logo shadow: `shadow-sm shadow-red-600/30`
  - Mobile drawer: `shadow-2xl`

---

## 4. Layout Structure

- **Outer Wrapper**: `min-h-screen bg-[#f1f5f9] text-slate-900 flex`
- **Desktop Sidebar**:
  - Width: `w-72` (`288px`)
  - Fixed position: `fixed inset-y-0 left-0 z-50 bg-white border-r border-slate-200 flex flex-col justify-between`
  - Header height: `h-16 px-6 border-b border-slate-200 flex items-center justify-between shrink-0`
  - Brand logo: `w-8 h-8 rounded-lg bg-red-600 flex items-center justify-center font-bold text-white text-base shadow-sm shadow-red-600/30`
  - Section spacing: `px-4 py-6 space-y-6`
  - Footer: `p-4 border-t border-slate-200 bg-slate-50/50 space-y-2`
- **Mobile Responsive Drawer**:
  - Backdrop: `fixed inset-0 z-50 bg-slate-900/40 backdrop-blur-xs transition-opacity lg:hidden`
  - Offscreen translate: `-translate-x-full lg:translate-x-0`
  - Slide in on open: `translate-x-0 shadow-2xl`
- **Main Area Offset**:
  - Desktop offset: `lg:pl-72 flex-1 flex flex-col min-w-0`
- **Header Bar**:
  - `sticky top-0 z-30 border-b border-slate-200 bg-white/95 backdrop-blur-md shadow-xs h-16 px-4 sm:px-6 lg:px-8 flex items-center justify-between gap-4`
- **Content Container**:
  - `flex-1 max-w-6xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-8`

---

## 5. Component Tokens (GEO-AUDITOR Application)

### Top Status Badges (Header Bar)
- **AI Connected**:
  - When active (`ai_enabled`): `bg-emerald-50 border border-emerald-200 text-emerald-700` with pulsing `bg-emerald-500` dot.
  - When inactive: `bg-slate-100 border border-slate-200 text-slate-500` with `bg-slate-400` dot.
- **Google Data**:
  - When active (`serp_enabled`): `bg-emerald-50 border border-emerald-200 text-emerald-700` with pulsing `bg-emerald-500` dot.
  - When inactive: `bg-slate-100 border border-slate-200 text-slate-500` with `bg-slate-400` dot.
- **Ahrefs**:
  - When active (`ahrefs_enabled`): `bg-emerald-50 border border-emerald-200 text-emerald-700` with pulsing `bg-emerald-500` dot.
  - When inactive: `bg-slate-100 border border-slate-200 text-slate-500` with `bg-slate-400` dot.

### Report Tabs
- Pill / tab bar with clear light styling:
  - Tab button active: `bg-red-50/70 border border-red-200 text-red-700 font-bold shadow-xs`
  - Tab button inactive: `text-slate-600 hover:text-slate-900 hover:bg-slate-100 border border-transparent`

### Citation Score Ring
- Background circle: `#e2e8f0` (Slate 200) instead of dark `#262626`.
- Stroke colors:
  - `>= 80`: `#16a34a` (green-600)
  - `>= 60`: `#65a30d` (lime-600)
  - `>= 40`: `#ca8a04` (amber-600)
  - `>= 20`: `#ea580c` (orange-600)
  - `< 20`: `#dc2626` (red-600)

### Dimension Accordion
- Collapsed state: White card with `border-slate-200`, dimension name, score badge, weight, progress bar.
- Expanded state: Submetrics breakdown, recommendations, evidence blocks in light card styling.

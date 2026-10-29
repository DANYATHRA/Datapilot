import os
from pathlib import Path

PUBLIC_DIR = Path(r"c:\Users\DANYATHRA S\Desktop\Datapilot\frontend\public")
PUBLIC_DIR.mkdir(parents=True, exist_ok=True)

# 1. Icon-only mark: geometric compass & chart prism
LOGO_MARK_SVG = '''<svg width="48" height="48" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="dp-mark-grad" x1="4" y1="4" x2="44" y2="44" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#0284c7"/>
      <stop offset="100%" stop-color="#0369a1"/>
    </linearGradient>
    <linearGradient id="dp-needle-grad" x1="16" y1="32" x2="32" y2="16" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#ffffff" stop-opacity="0.9"/>
      <stop offset="100%" stop-color="#e0f2fe"/>
    </linearGradient>
  </defs>
  <!-- Geometric Hexagonal Shield with Rounded Vertices -->
  <rect x="4" y="4" width="40" height="40" rx="10" fill="url(#dp-mark-grad)" />
  <!-- Precision Compass / Chart Compass Needle -->
  <path d="M24 10L35 21L24 38L13 21L24 10Z" stroke="#ffffff" stroke-width="2" stroke-linejoin="round" fill="none" opacity="0.4"/>
  <!-- North-East Rising Pilot Needle -->
  <path d="M24 13L33 22L24 25L21 24L24 13Z" fill="url(#dp-needle-grad)"/>
  <path d="M24 35L15 26L24 23L27 24L24 35Z" fill="#38bdf8" opacity="0.7"/>
  <!-- Analytical Grid Lines -->
  <circle cx="24" cy="24" r="3.5" fill="#ffffff" />
  <circle cx="24" cy="24" r="1.5" fill="#0284c7" />
  <!-- Chart Trend Axis Nodes -->
  <circle cx="16" cy="32" r="1.75" fill="#ffffff" opacity="0.8"/>
  <circle cx="32" cy="16" r="1.75" fill="#38bdf8"/>
</svg>'''

# 2. Light logo (for light backgrounds: dark wordmark)
LOGO_LIGHT_SVG = '''<svg width="220" height="48" viewBox="0 0 220 48" fill="none" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="dp-mark-grad-l" x1="4" y1="4" x2="44" y2="44" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#0284c7"/>
      <stop offset="100%" stop-color="#0369a1"/>
    </linearGradient>
    <linearGradient id="dp-needle-grad-l" x1="16" y1="32" x2="32" y2="16" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#ffffff" stop-opacity="0.95"/>
      <stop offset="100%" stop-color="#e0f2fe"/>
    </linearGradient>
  </defs>
  <!-- Mark -->
  <g transform="translate(0, 0)">
    <rect x="4" y="4" width="40" height="40" rx="10" fill="url(#dp-mark-grad-l)" />
    <path d="M24 10L35 21L24 38L13 21L24 10Z" stroke="#ffffff" stroke-width="2" stroke-linejoin="round" fill="none" opacity="0.4"/>
    <path d="M24 13L33 22L24 25L21 24L24 13Z" fill="url(#dp-needle-grad-l)"/>
    <path d="M24 35L15 26L24 23L27 24L24 35Z" fill="#38bdf8" opacity="0.7"/>
    <circle cx="24" cy="24" r="3.5" fill="#ffffff" />
    <circle cx="24" cy="24" r="1.5" fill="#0284c7" />
  </g>
  <!-- Wordmark -->
  <text x="56" y="31" font-family="'IBM Plex Sans', -apple-system, sans-serif" font-size="22" font-weight="700" letter-spacing="-0.5px" fill="#0f172a">Data<tspan fill="#0284c7">Pilot</tspan></text>
</svg>'''

# 3. Dark logo (for dark backgrounds: light wordmark)
LOGO_DARK_SVG = '''<svg width="220" height="48" viewBox="0 0 220 48" fill="none" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="dp-mark-grad-d" x1="4" y1="4" x2="44" y2="44" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#0ea5e9"/>
      <stop offset="100%" stop-color="#0284c7"/>
    </linearGradient>
    <linearGradient id="dp-needle-grad-d" x1="16" y1="32" x2="32" y2="16" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="#ffffff" stop-opacity="0.95"/>
      <stop offset="100%" stop-color="#e0f2fe"/>
    </linearGradient>
  </defs>
  <!-- Mark -->
  <g transform="translate(0, 0)">
    <rect x="4" y="4" width="40" height="40" rx="10" fill="url(#dp-mark-grad-d)" />
    <path d="M24 10L35 21L24 38L13 21L24 10Z" stroke="#ffffff" stroke-width="2" stroke-linejoin="round" fill="none" opacity="0.4"/>
    <path d="M24 13L33 22L24 25L21 24L24 13Z" fill="url(#dp-needle-grad-d)"/>
    <path d="M24 35L15 26L24 23L27 24L24 35Z" fill="#38bdf8" opacity="0.7"/>
    <circle cx="24" cy="24" r="3.5" fill="#ffffff" />
    <circle cx="24" cy="24" r="1.5" fill="#0284c7" />
  </g>
  <!-- Wordmark -->
  <text x="56" y="31" font-family="'IBM Plex Sans', -apple-system, sans-serif" font-size="22" font-weight="700" letter-spacing="-0.5px" fill="#f8fafc">Data<tspan fill="#38bdf8">Pilot</tspan></text>
</svg>'''

# 4. Web App Manifest
MANIFEST = '''{
  "name": "DataPilot Analytics & Governance Platform",
  "short_name": "DataPilot",
  "description": "Enterprise end-to-end data analytics, cleaning, DuckDB SQL exploration, and automated reporting platform.",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#0b0f17",
  "theme_color": "#0284c7",
  "icons": [
    {
      "src": "/favicon-16.png",
      "sizes": "16x16",
      "type": "image/png"
    },
    {
      "src": "/favicon-32.png",
      "sizes": "32x32",
      "type": "image/png"
    },
    {
      "src": "/apple-touch-icon.png",
      "sizes": "180x180",
      "type": "image/png"
    },
    {
      "src": "/icon-512.png",
      "sizes": "512x512",
      "type": "image/png"
    }
  ]
}'''

# Write SVGs
(PUBLIC_DIR / "logo-mark.svg").write_text(LOGO_MARK_SVG, encoding="utf-8")
(PUBLIC_DIR / "logo-light.svg").write_text(LOGO_LIGHT_SVG, encoding="utf-8")
(PUBLIC_DIR / "logo-dark.svg").write_text(LOGO_DARK_SVG, encoding="utf-8")
(PUBLIC_DIR / "favicon.svg").write_text(LOGO_MARK_SVG, encoding="utf-8")
(PUBLIC_DIR / "site.webmanifest").write_text(MANIFEST, encoding="utf-8")

print("Wrote SVG logos and manifest.")

# Use Playwright to render pixel-perfect PNGs for 16, 32, 180, 512, and social preview (1200x630)
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    # Render Favicons
    mark_svg_path = (PUBLIC_DIR / "logo-mark.svg").as_uri()
    
    for size, filename in [(16, "favicon-16.png"), (32, "favicon-32.png"), (180, "apple-touch-icon.png"), (512, "icon-512.png")]:
        page.set_viewport_size({"width": size, "height": size})
        html_content = f'''<!DOCTYPE html>
        <html>
        <head><style>body,html{{margin:0;padding:0;overflow:hidden;background:transparent;}}</style></head>
        <body><img src="{mark_svg_path}" width="{size}" height="{size}" style="display:block;"/></body>
        </html>'''
        page.set_content(html_content)
        page.wait_for_timeout(200)
        page.screenshot(path=str(PUBLIC_DIR / filename), omit_background=True)
        print(f"Generated {filename} ({size}x{size})")

    # Render Social Preview Card (1200x630)
    page.set_viewport_size({"width": 1200, "height": 630})
    social_html = f'''<!DOCTYPE html>
    <html>
    <head>
      <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@500;600;700&family=IBM+Plex+Mono:wght@500&display=swap" rel="stylesheet">
      <style>
        body, html {{
          margin: 0; padding: 0; width: 1200px; height: 630px;
          background: linear-gradient(135deg, #090d16 0%, #0f172a 50%, #0369a1 100%);
          font-family: 'IBM Plex Sans', sans-serif;
          color: #ffffff;
          display: flex; flex-direction: column; justify-content: space-between;
          padding: 80px; box-sizing: border-box;
        }}
        .top {{ display: flex; align-items: center; gap: 20px; }}
        .badge {{ background: rgba(14, 165, 233, 0.15); border: 1px solid rgba(14, 165, 233, 0.35); color: #38bdf8; font-size: 14px; font-weight: 600; padding: 6px 14px; border-radius: 999px; letter-spacing: 0.5px; }}
        .title {{ font-size: 52px; font-weight: 700; line-height: 1.15; margin: 30px 0 16px; letter-spacing: -1px; }}
        .subtitle {{ font-size: 22px; color: #94a3b8; max-width: 860px; line-height: 1.45; }}
        .bottom {{ display: flex; justify-content: space-between; align-items: center; border-top: 1px solid rgba(255,255,255,0.1); padding-top: 24px; font-size: 16px; color: #64748b; }}
        .features {{ display: flex; gap: 32px; font-family: 'IBM Plex Mono', monospace; font-size: 15px; color: #cbd5e1; }}
      </style>
    </head>
    <body>
      <div class="top">
        <img src="{mark_svg_path}" width="56" height="56"/>
        <span style="font-size: 32px; font-weight: 700; letter-spacing: -0.5px;">Data<span style="color: #38bdf8;">Pilot</span></span>
        <span class="badge">Enterprise Analytics &amp; Governance</span>
      </div>
      <div>
        <div class="title">Intelligent Data Analytics,<br/>Automated Cleaning &amp; Visual Studio</div>
        <div class="subtitle">Deterministic 10-stage data engineering, in-process DuckDB query compilation, verified AI insights with mathematical reconciliation.</div>
      </div>
      <div class="bottom">
        <div class="features">
          <span>&bull; DuckDB Engine</span>
          <span>&bull; 23 Chart Types</span>
          <span>&bull; Version Audits</span>
          <span>&bull; Openpyxl Excel</span>
        </div>
        <span>datapilot.internal</span>
      </div>
    </body>
    </html>'''
    page.set_content(social_html)
    page.wait_for_timeout(400)
    page.screenshot(path=str(PUBLIC_DIR / "social-preview.png"))
    print("Generated social-preview.png (1200x630)")

    browser.close()

print("All branding assets successfully created!")

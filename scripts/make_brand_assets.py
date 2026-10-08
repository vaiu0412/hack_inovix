"""Render assets/favicon.png from the DEPORT mark (assets/logo_mark.svg).

Uses cairosvg when it is installed with a working Cairo library; otherwise draws the same
mark with Pillow (always available with Streamlit).

Run:  python scripts/make_brand_assets.py
"""
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "assets"
NAVY, BLUE, AMBER, WHITE = "#0B1E3F", "#2563EB", "#F59E0B", "#FFFFFF"


def with_cairosvg(out, size):
    import cairosvg  # needs the native Cairo library

    cairosvg.svg2png(url=str(ASSETS / "logo_mark.svg"), write_to=str(out), output_width=size, output_height=size)


def with_pillow(out, size):
    """The mark drawn at 8x on a 64-unit grid, then scaled down for smooth edges."""
    from PIL import Image, ImageDraw

    k = 8 * size / 64
    big = Image.new("RGBA", (int(64 * k), int(64 * k)), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)

    def s(*v):
        return [round(x * k) for x in v]

    d.rounded_rectangle(s(0, 0, 64, 64), radius=round(15 * k), fill=NAVY)
    # the D: stem rectangle + half disc (centre 32,32, radius 22)
    d.rectangle(s(12, 10, 32, 54), fill=BLUE)
    d.pieslice(s(10, 10, 54, 54), start=-90, end=90, fill=BLUE)
    w = round(3.6 * k)
    # route: up the stem, along the top, round the bowl to the decision node (43,32)
    d.line(s(21, 44, 21, 26), fill=WHITE, width=w)
    d.arc(s(21, 20, 33, 32), start=180, end=270, fill=WHITE, width=w)
    d.line(s(27, 20, 31, 20), fill=WHITE, width=w)
    d.arc(s(19, 20, 43, 44), start=270, end=360, fill=WHITE, width=w)
    for x, y in ((21, 44), (21, 26)):
        d.ellipse(s(x - 1.8, y - 1.8, x + 1.8, y + 1.8), fill=WHITE)
    # the road not taken (dotted), and the branch to the alternate route
    for angle in (20, 45, 70):
        import math

        x, y = 31 + 12 * math.cos(math.radians(angle)), 32 + 12 * math.sin(math.radians(angle))
        d.ellipse(s(x - 1.5, y - 1.5, x + 1.5, y + 1.5), fill=(255, 255, 255, 130))
    d.line(s(43, 32, 50.5, 24.5), fill=AMBER, width=w)
    d.ellipse(s(48.7, 22.7, 52.3, 26.3), fill=AMBER)
    # decision node and vehicle
    d.ellipse(s(39.1, 28.1, 46.9, 35.9), fill=NAVY, outline=WHITE, width=round(2.4 * k))
    d.ellipse(s(25.6, 15.6, 34.4, 24.4), fill=AMBER, outline=NAVY, width=round(1.8 * k))
    big.resize((size, size), Image.LANCZOS).save(out)


def main():
    out = ASSETS / "favicon.png"
    try:
        with_cairosvg(out, 64)
        print("favicon.png rendered with cairosvg")
    except Exception as error:  # no cairosvg / no Cairo DLL (typical on Windows)
        with_pillow(out, 64)
        print(f"favicon.png drawn with Pillow ({type(error).__name__}: cairosvg unavailable)")


if __name__ == "__main__":
    main()

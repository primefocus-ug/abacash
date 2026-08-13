# accounts/pwa_icons.py
#
# Generates PWA icons per-tenant. Two paths:
#
#   1. Tenant has uploaded a company_logo -> resize/pad it to the requested
#      icon size and return PNG bytes.
#   2. No logo -> render a fallback icon: gradient background + the first
#      1-2 letters of the company name, matching the .app-splash-mark
#      style already used on the loading screen (see base.html).
#
# Because storage is django-tenants' TenantFileSystemStorage
# (MULTITENANT_RELATIVE_MEDIA_ROOT = "%s"), files are already isolated on
# disk per schema — there is no cross-tenant leakage risk in reading
# company_logo here the same way the rest of the app does.
#
# Icons are content-hashed and served with long-lived, immutable cache
# headers, so regeneration cost is a non-issue: each tenant's browser
# fetches its icon once per logo version, not on every manifest load.

import hashlib
import io

from PIL import Image, ImageDraw, ImageFont

# Matches --teal-400 / --teal-600 from base.html's design tokens, so the
# fallback icon looks like it belongs to the same app as the splash screen.
GRADIENT_START = (18, 121, 112)   # #127970
GRADIENT_END = (15, 92, 88)       # #0f5c58
TEXT_COLOR = (255, 255, 255)

_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]


def _load_font(size):
    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _initials(company_name: str) -> str:
    words = [w for w in (company_name or "").split() if w]
    if not words:
        return "CO"
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][0] + words[1][0]).upper()


def _render_fallback_icon(company_name: str, size: int, maskable: bool = False) -> Image.Image:
    """
    Draws a rounded-square (or full-bleed, for maskable) gradient tile
    with the company's initials centered — the same visual language as
    .app-splash-mark in base.html.
    """
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # vertical gradient background
    for y in range(size):
        t = y / max(size - 1, 1)
        r = int(GRADIENT_START[0] + (GRADIENT_END[0] - GRADIENT_START[0]) * t)
        g = int(GRADIENT_START[1] + (GRADIENT_END[1] - GRADIENT_START[1]) * t)
        b = int(GRADIENT_START[2] + (GRADIENT_END[2] - GRADIENT_START[2]) * t)
        draw.line([(0, y), (size, y)], fill=(r, g, b, 255))

    if not maskable:
        # round the corners — maskable icons must stay full-bleed since
        # the OS applies its own mask shape (circle, squircle, etc.)
        radius = int(size * 0.22)
        mask = Image.new("L", (size, size), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.rounded_rectangle([(0, 0), (size - 1, size - 1)], radius=radius, fill=255)
        img.putalpha(mask)

    initials = _initials(company_name)
    # Maskable icons need extra safe-area padding (~20%) so the initials
    # aren't clipped when the OS crops to a circle.
    font_size = int(size * (0.34 if maskable else 0.42))
    font = _load_font(font_size)

    draw = ImageDraw.Draw(img)
    bbox = draw.textbbox((0, 0), initials, font=font)
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pos = ((size - text_w) / 2 - bbox[0], (size - text_h) / 2 - bbox[1])
    draw.text(pos, initials, font=font, fill=TEXT_COLOR)

    return img


def _resize_logo(logo_file, size: int, maskable: bool = False) -> Image.Image:
    """
    Opens an uploaded logo and fits it into a square icon. Uploaded logos
    are usually not square, so we letterbox onto a padded canvas rather
    than crop/stretch and distort the brand mark.
    """
    logo_file.seek(0)
    src = Image.open(logo_file).convert("RGBA")

    pad_fraction = 0.30 if maskable else 0.14  # maskable needs a bigger safe area
    inner = int(size * (1 - pad_fraction))
    src.thumbnail((inner, inner), Image.LANCZOS)

    canvas = Image.new("RGBA", (size, size), (255, 255, 255, 255) if maskable else (0, 0, 0, 0))
    offset = ((size - src.width) // 2, (size - src.height) // 2)
    canvas.paste(src, offset, src)

    if not maskable:
        radius = int(size * 0.22)
        mask = Image.new("L", (size, size), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.rounded_rectangle([(0, 0), (size - 1, size - 1)], radius=radius, fill=255)
        canvas.putalpha(mask)

    return canvas


def get_icon_png(company_settings, company_name: str, size: int, maskable: bool = False) -> bytes:
    """
    Returns PNG bytes for a PWA icon at the given size for the current
    tenant. Call this from a view with the request's own company_settings
    / company_name (already tenant-scoped via the `company` context
    processor) — never pass another tenant's objects in.
    """
    if company_settings and getattr(company_settings, "company_logo", None):
        try:
            img = _resize_logo(company_settings.company_logo, size, maskable=maskable)
        except Exception:
            img = _render_fallback_icon(company_name, size, maskable=maskable)
    else:
        img = _render_fallback_icon(company_name, size, maskable=maskable)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def get_icon_etag(company_settings, size: int, maskable: bool) -> str:
    """
    Cheap ETag so browsers/CDNs can revalidate without re-downloading.
    Based on the logo file's name+size (changes whenever a new logo is
    uploaded) rather than hashing image bytes on every request.
    """
    logo = getattr(company_settings, "company_logo", None) if company_settings else None
    key_parts = [str(size), str(maskable)]
    if logo:
        try:
            key_parts.append(logo.name)
            key_parts.append(str(logo.size))
        except Exception:
            key_parts.append("nologo")
    else:
        key_parts.append("nologo")
    raw = "|".join(key_parts).encode()
    return hashlib.sha1(raw).hexdigest()[:16]
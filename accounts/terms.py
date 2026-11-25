from html.parser import HTMLParser
import re
from xml.sax.saxutils import escape, quoteattr

import bleach
from bleach.css_sanitizer import CSSSanitizer


_ALLOWED_TAGS = {
    "p", "br", "div", "strong", "b", "em", "i", "u", "s", "strike",
    "sub", "sup", "span", "font", "ul", "ol", "li", "blockquote",
    "h1", "h2", "h3", "h4", "h5", "h6",
}
_FONT_FAMILIES = {
    "arial", "calibri", "courier new", "georgia", "times new roman",
    "tahoma", "trebuchet ms", "verdana", "sans-serif", "serif", "monospace",
}
_NAMED_COLORS = {
    "aqua", "black", "blue", "fuchsia", "gray", "green", "lime", "maroon",
    "navy", "olive", "purple", "red", "silver", "teal", "white", "yellow",
}
_COLOR_PATTERN = re.compile(
    r"^(?:#[0-9a-f]{3,4}|#[0-9a-f]{6}|#[0-9a-f]{8}|"
    r"(?:rgb|rgba)\([\d\s.,%]+\)|[a-z]+)$",
    re.IGNORECASE,
)
_REPORTLAB_FONT_NAMES = {
    "arial": "Helvetica",
    "calibri": "Helvetica",
    "courier new": "Courier",
    "georgia": "Times-Roman",
    "times new roman": "Times-Roman",
    "tahoma": "Helvetica",
    "trebuchet ms": "Helvetica",
    "verdana": "Helvetica",
    "sans-serif": "Helvetica",
    "serif": "Times-Roman",
    "monospace": "Courier",
}
_REPORTLAB_COLORS = {
    "aqua": "#00ffff",
    "black": "#000000",
    "blue": "#0000ff",
    "fuchsia": "#ff00ff",
    "gray": "#808080",
    "green": "#008000",
    "lime": "#00ff00",
    "maroon": "#800000",
    "navy": "#000080",
    "olive": "#808000",
    "purple": "#800080",
    "red": "#ff0000",
    "silver": "#c0c0c0",
    "teal": "#008080",
    "white": "#ffffff",
    "yellow": "#ffff00",
}
_CSS_SANITIZER = CSSSanitizer(
    allowed_css_properties={
        "background-color",
        "color",
        "font-family",
        "font-size",
        "font-style",
        "font-weight",
        "text-align",
        "text-decoration",
    }
)


def _allowed_attribute(tag, name, value):
    if name == "style":
        return True
    if name == "align" and tag in {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6"}:
        return value.lower() in {"left", "center", "right", "justify"}
    if tag != "font":
        return False
    if name == "size":
        return value in {"1", "2", "3", "4", "5", "6", "7"}
    if name == "face":
        return value.strip().lower() in _FONT_FAMILIES
    if name == "color":
        return bool(_COLOR_PATTERN.fullmatch(value.strip())) and (
            value.strip().lower() in _NAMED_COLORS
            or value.strip().startswith("#")
            or value.strip().lower().startswith(("rgb(", "rgba("))
        )
    return False


def sanitize_loan_terms(value):
    return bleach.clean(
        str(value or "").strip(),
        tags=_ALLOWED_TAGS,
        attributes=_allowed_attribute,
        protocols=[],
        strip=True,
        css_sanitizer=_CSS_SANITIZER,
    )


def _style_declarations(style):
    return {
        key.strip().lower(): value.strip()
        for declaration in style.split(";")
        if ":" in declaration
        for key, value in [declaration.split(":", 1)]
    }


def _reportlab_color(value):
    value = value.strip().lower()
    if value in _REPORTLAB_COLORS:
        return _REPORTLAB_COLORS[value]
    if value.startswith("#") and len(value) in {4, 5, 7, 9}:
        if len(value) in {4, 5}:
            return "#" + "".join(char * 2 for char in value[1:4])
        return value[:7]
    rgb = re.fullmatch(
        r"rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})(?:\s*,\s*[\d.]+)?\s*\)",
        value,
    )
    if rgb and all(int(channel) <= 255 for channel in rgb.groups()):
        return "#" + "".join(f"{int(channel):02x}" for channel in rgb.groups())
    return None


def _reportlab_font_family(value):
    family = value.split(",", 1)[0].strip().strip("\"'").lower()
    return _REPORTLAB_FONT_NAMES.get(family)


def _reportlab_font_size(value):
    value = value.strip().lower()
    sizes = {"1": 8, "2": 9, "3": 10, "4": 12, "5": 14, "6": 18, "7": 24}
    if value in sizes:
        return sizes[value]
    match = re.fullmatch(r"(\d+(?:\.\d+)?)(px|pt|em|rem|%)?", value)
    if not match:
        return None
    amount = float(match.group(1))
    unit = match.group(2) or "pt"
    if unit == "px":
        amount *= 0.75
    elif unit in {"em", "rem"}:
        amount *= 8
    elif unit == "%":
        amount *= 0.08
    return min(max(round(amount, 1), 6), 36)


def _font_markup(attributes, style=""):
    attributes = dict(attributes)
    declarations = _style_declarations(style)
    family = attributes.get("face") or declarations.get("font-family", "")
    color = attributes.get("color") or declarations.get("color", "")
    back_color = declarations.get("background-color", "")
    size = attributes.get("size") or declarations.get("font-size", "")

    reportlab_attributes = {}
    font_name = _reportlab_font_family(family)
    if font_name:
        reportlab_attributes["name"] = font_name
    reportlab_color = _reportlab_color(color)
    if reportlab_color:
        reportlab_attributes["color"] = reportlab_color
    reportlab_back_color = _reportlab_color(back_color)
    if reportlab_back_color:
        reportlab_attributes["backColor"] = reportlab_back_color
    font_size = _reportlab_font_size(size)
    if font_size:
        reportlab_attributes["size"] = str(font_size)

    opening = ""
    closing = ""
    weight = declarations.get("font-weight", "").lower()
    font_style = declarations.get("font-style", "").lower()
    decoration = declarations.get("text-decoration", "").lower()
    if weight in {"bold", "600", "700", "800", "900"}:
        opening += "<b>"
        closing = "</b>" + closing
    if font_style in {"italic", "oblique"}:
        opening += "<i>"
        closing = "</i>" + closing
    if "underline" in decoration.split():
        opening += "<u>"
        closing = "</u>" + closing
    if "line-through" in decoration.split():
        opening += "<strike>"
        closing = "</strike>" + closing
    if reportlab_attributes:
        encoded = " ".join(
            f"{name}={quoteattr(value)}"
            for name, value in reportlab_attributes.items()
        )
        opening += f"<font {encoded}>"
        closing = "</font>" + closing
    return opening, closing


class _ReportLabTermsParser(HTMLParser):
    _inline_tags = {
        "b": "b",
        "strong": "b",
        "i": "i",
        "em": "i",
        "u": "u",
        "s": "strike",
        "strike": "strike",
        "sub": "sub",
        "sup": "super",
        "ul": "ul",
        "ol": "ol",
        "li": "li",
    }
    _block_tags = {"p", "div", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.stack = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "br":
            self.parts.append("<br/>")
            return

        style = _style_declarations(attributes.get("style", ""))
        if tag in self._inline_tags:
            reportlab_tag = self._inline_tags[tag]
            opening, closing = f"<{reportlab_tag}>", f"</{reportlab_tag}>"
        elif tag == "font":
            opening, closing = _font_markup(attributes)
        elif tag == "span":
            opening, closing = _font_markup({}, attributes.get("style", ""))
        elif tag in self._block_tags:
            alignment = style.get("text-align", attributes.get("align", ""))
            para_attributes = (
                f" align={quoteattr(alignment)}"
                if alignment in {"left", "center", "right", "justify"}
                else ""
            )
            opening, closing = f"<para{para_attributes}>", "</para>"
            if tag in {"h1", "h2", "h3", "h4", "h5", "h6", "blockquote"}:
                opening += "<b>"
                closing = "</b>" + closing
        else:
            opening, closing = "", ""
        self.parts.append(opening)
        self.stack.append((tag, closing))

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                closing = "".join(entry[1] for entry in reversed(self.stack[index:]))
                del self.stack[index:]
                self.parts.append(closing)
                return

    def handle_data(self, data):
        escaped = escape(data).replace("\r\n", "\n").replace("\r", "\n")
        self.parts.append(escaped.replace("\n", "<br/>"))

    def get_markup(self):
        self.parts.extend(entry[1] for entry in reversed(self.stack))
        self.stack.clear()
        return "".join(self.parts)


def loan_terms_reportlab_markup(value):
    parser = _ReportLabTermsParser()
    parser.feed(sanitize_loan_terms(value))
    parser.close()
    return parser.get_markup()

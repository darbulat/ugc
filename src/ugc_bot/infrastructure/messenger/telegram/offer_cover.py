"""A reusable anonymous cover, rendered once per bot process."""

from functools import cache
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont


@cache
def neutral_offer_cover() -> bytes:
    width, height = 864, 350
    image = (
        Image.linear_gradient("L")
        .rotate(90, expand=True)
        .resize((width, height))
    )
    cover = Image.composite(
        Image.new("RGB", (width, height), "#dffac7"),
        Image.new("RGB", (width, height), "#a9e9cb"),
        image,
    )
    draw = ImageDraw.Draw(cover, "RGBA")
    for offset in (0, 54, 108):
        draw.ellipse(
            (502 + offset, -110, 966 - offset, 400),
            outline=(28, 86, 55, 103),
            width=3,
        )
    draw.text(
        (54, 102),
        "UGC",
        font=ImageFont.load_default(size=104),
        fill="#153524",
    )
    draw.rounded_rectangle((60, 237, 183, 244), radius=4, fill="#153524")
    output = BytesIO()
    cover.save(output, format="JPEG", quality=90, optimize=True)
    return output.getvalue()

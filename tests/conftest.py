import io
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def jpeg_bytes() -> bytes:
    img = Image.new("RGB", (640, 480), (200, 30, 30))
    out = io.BytesIO()
    img.save(out, format="JPEG")
    return out.getvalue()

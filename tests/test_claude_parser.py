"""Проверяем сборку запроса к Claude без обращения к API."""
from types import SimpleNamespace

from app.claude_parser import ClaudeParser, ImagePick, ProductDraft
from app.config import BusinessConfig


class FakeMessages:
    def __init__(self, result):
        self.result = result
        self.kwargs = None

    def parse(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(stop_reason="end_turn", parsed_output=self.result, content=[])


def make(result):
    fm = FakeMessages(result)
    client = SimpleNamespace(beta=SimpleNamespace(messages=fm))
    cfg = BusinessConfig.model_validate({"catalog": {"categories": [{"id": 1, "title": "Одежда"}]}})
    return ClaudeParser("claude-opus-5-5", cfg, client=client), fm


def test_build_draft_request(jpeg_bytes):
    draft = ProductDraft(title="t", description_html="", category="Одежда", collections=[], image_search_query="q",
                         purchase_price_from_note=0, uncertainties="")
    parser, fm = make(draft)
    out = parser.build_draft([jpeg_bytes, jpeg_bytes], "хлопок", 350)
    assert out is draft
    kw = fm.kwargs
    assert kw["model"] == "claude-opus-5-5" and kw["output_format"] is ProductDraft
    assert kw["thinking"] == {"type": "adaptive"} and kw["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in kw["betas"]
    assert "Одежда" in kw["system"][0]["text"] and kw["system"][0]["cache_control"] == {"type": "ephemeral"}
    content = kw["messages"][0]["content"]
    assert [b["type"] for b in content] == ["image", "image", "text"]
    assert content[0]["source"]["media_type"] == "image/jpeg"
    assert "350" in content[-1]["text"] and "хлопок" in content[-1]["text"]


def test_pick_images_request(jpeg_bytes):
    parser, fm = make(ImagePick(selected_indices=[2], reason="r"))
    out = parser.pick_matching_images([jpeg_bytes], [jpeg_bytes, jpeg_bytes], 3)
    assert out.selected_indices == [2]
    content = fm.kwargs["messages"][0]["content"]
    assert sum(1 for b in content if b["type"] == "image") == 3
    assert fm.kwargs["output_config"] == {"effort": "low"}

"""Tests for Google Gemma fallback translation in agent/tools.py."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from agent import tools as agent_tools
from core import rulepack
from store.memory import MemoryStore
from store.readonly import ReadOnlyStoreView

ROOT = Path(__file__).resolve().parent.parent
PACK_PATH = ROOT / "tests" / "fixtures" / "pack_min.json"


def test_translate_delegates_to_gemma_when_not_in_templates():
    pack = rulepack.load(PACK_PATH)
    view = ReadOnlyStoreView(MemoryStore())
    _, _, translate, _ = agent_tools.make_tools(view, pack)

    mock_resp = MagicMock()
    mock_resp.text = "नमस्ते, यह एक परीक्षण संदेश है।"

    with patch("os.environ.get", side_effect=lambda k, d=None: "fake-key" if k == "GEMINI_API_KEY" else d):
        with patch("google.genai.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.models.generate_content.return_value = mock_resp
            mock_client_cls.return_value = mock_client

            result = translate("Hello, this is a custom follow-up message.", "hi")
            assert result == "नमस्ते, यह एक परीक्षण संदेश है।"


def test_translate_returns_untranslated_marker_when_gemma_offline():
    pack = rulepack.load(PACK_PATH)
    view = ReadOnlyStoreView(MemoryStore())
    _, _, translate, _ = agent_tools.make_tools(view, pack)

    # When no API key is present or model off
    with patch("os.environ.get", return_value="0"):
        result = translate("Hello, this is a custom follow-up message.", "hi")
        assert result.startswith("[untranslated:hi]")

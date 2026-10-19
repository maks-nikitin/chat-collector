"""Преобразование «богатых» постов Telegram (поле Message.rich_message) в простые
JSON-блоки, которые легко рисовать на фронтенде.

Модуль чистый: никаких запросов в сеть. Фото и файлы блоки только *ссылаются*
(photo_id / doc_id), скачивает их telegram_service.

Форматы результата:
  run    = {"t": "текст", "b": True, "i": True, "u": True, "s": True, "code": True, "url": "https://..."}
  блоки  = {"type": "heading", "level": 1..6, "runs": [run]}
           {"type": "paragraph", "runs": [run]}
           {"type": "quote", "runs": [run], "caption": [run]}
           {"type": "code", "runs": [run]}
           {"type": "list", "ordered": bool, "start": int, "items": [[run], ...]}
           {"type": "divider"}
           {"type": "photo", "photo_id": int, "caption": [run]}
           {"type": "video" | "audio" | "file", "doc_id": int, "caption": [run]}
"""
import logging
from typing import List, Optional

log = logging.getLogger("uvicorn.error")

_STYLES = {
    "TextBold": "b",
    "TextItalic": "i",
    "TextUnderline": "u",
    "TextStrike": "s",
    "TextFixed": "code",
}

_HEADINGS = {
    "PageBlockTitle": 1, "PageBlockHeading1": 1,
    "PageBlockHeader": 2, "PageBlockHeading2": 2,
    "PageBlockSubtitle": 3, "PageBlockSubheader": 3, "PageBlockHeading3": 3,
    "PageBlockHeading4": 4, "PageBlockHeading5": 5, "PageBlockHeading6": 6,
}

_PARAGRAPHS = {"PageBlockParagraph", "PageBlockKicker", "PageBlockFooter"}
_SAFE_URL_PREFIXES = ("http://", "https://", "mailto:", "tel:")


def _safe_url(url: Optional[str]) -> Optional[str]:
    if url and url.strip().lower().startswith(_SAFE_URL_PREFIXES):
        return url.strip()
    return None


def runs_of(rt) -> List[dict]:
    """RichText -> плоский список кусков текста со стилями."""
    out: List[dict] = []

    def emit(text: str, styles: frozenset, url: Optional[str]):
        if not text:
            return
        run = {"t": text}
        for s in styles:
            run[s] = True
        if url:
            run["url"] = url
        out.append(run)

    def walk(node, styles: frozenset, url: Optional[str]):
        if node is None:
            return
        if isinstance(node, str):
            emit(node, styles, url)
            return
        name = type(node).__name__
        if name in ("TextEmpty", "TextImage"):
            return
        if name == "TextCustomEmoji":
            emit(node.alt, styles, url)  # кастомный эмодзи показываем его обычным аналогом
            return
        texts = getattr(node, "texts", None)
        if texts is not None:  # TextConcat
            for child in texts:
                walk(child, styles, url)
            return

        inner = getattr(node, "text", None)
        new_styles = styles | {_STYLES[name]} if name in _STYLES else styles
        new_url = url
        if name == "TextUrl":
            new_url = _safe_url(getattr(node, "url", None))
        elif name == "TextEmail":
            new_url = _safe_url("mailto:" + (getattr(node, "email", "") or ""))
        elif name == "TextPhone":
            new_url = _safe_url("tel:" + (getattr(node, "phone", "") or ""))
        elif name == "TextAutoUrl":
            new_url = _safe_url("".join(r["t"] for r in runs_of(inner)))
        walk(inner, new_styles, new_url)

    walk(rt, frozenset(), None)
    return out


def plain_text(rt) -> str:
    return "".join(r["t"] for r in runs_of(rt))


def _caption(cap) -> List[dict]:
    return runs_of(getattr(cap, "text", None)) if cap is not None else []


def _list_item_runs(item) -> List[dict]:
    if getattr(item, "text", None) is not None:
        return runs_of(item.text)
    runs: List[dict] = []
    for blk in convert_blocks(getattr(item, "blocks", []) or []):
        r = blk.get("runs")
        if r:
            if runs:
                runs.append({"t": "\n"})
            runs.extend(r)
    return runs


def convert_blocks(blocks) -> List[dict]:
    """Список PageBlock -> плоский список простых блоков (вложенные раскрываются)."""
    result: List[dict] = []
    for b in blocks or []:
        name = type(b).__name__

        if name in _HEADINGS:
            result.append({"type": "heading", "level": _HEADINGS[name], "runs": runs_of(b.text)})
        elif name in _PARAGRAPHS:
            result.append({"type": "paragraph", "runs": runs_of(b.text)})
        elif name == "PageBlockAuthorDate":
            result.append({"type": "paragraph", "runs": runs_of(b.author)})
        elif name == "PageBlockPreformatted":
            result.append({"type": "code", "runs": runs_of(b.text)})
        elif name in ("PageBlockBlockquote", "PageBlockPullquote"):
            result.append({"type": "quote", "runs": runs_of(b.text), "caption": runs_of(b.caption)})
        elif name == "PageBlockBlockquoteBlocks":
            runs: List[dict] = []
            for inner in convert_blocks(b.blocks):
                if inner.get("runs"):
                    if runs:
                        runs.append({"t": "\n"})
                    runs.extend(inner["runs"])
            result.append({"type": "quote", "runs": runs, "caption": runs_of(b.caption)})
        elif name == "PageBlockDivider":
            result.append({"type": "divider"})
        elif name == "PageBlockList":
            result.append({"type": "list", "ordered": False, "start": 1,
                           "items": [_list_item_runs(i) for i in b.items]})
        elif name == "PageBlockOrderedList":
            result.append({"type": "list", "ordered": True, "start": getattr(b, "start", None) or 1,
                           "items": [_list_item_runs(i) for i in b.items]})
        elif name == "PageBlockPhoto":
            result.append({"type": "photo", "photo_id": b.photo_id, "caption": _caption(b.caption)})
        elif name == "PageBlockVideo":
            result.append({"type": "video", "doc_id": b.video_id, "caption": _caption(b.caption),
                           "gif": bool(getattr(b, "autoplay", False) and getattr(b, "loop", False))})
        elif name == "PageBlockAudio":
            result.append({"type": "audio", "doc_id": b.audio_id, "caption": _caption(b.caption)})
        elif name == "PageBlockDocument":
            result.append({"type": "file", "doc_id": b.document_id, "caption": _caption(b.caption)})
        elif name == "PageBlockCover":
            result.extend(convert_blocks([b.cover]))
        elif name in ("PageBlockCollage", "PageBlockSlideshow"):
            result.extend(convert_blocks(b.items))
        elif name == "PageBlockDetails":
            title = runs_of(b.title)
            if title:
                result.append({"type": "paragraph", "runs": [dict(r, b=True) for r in title]})
            result.extend(convert_blocks(b.blocks))
        elif name in ("PageBlockAnchor", "PageBlockChannel", "PageBlockRelatedArticles", "PageBlockUnsupported"):
            continue  # нечего показывать
        else:
            inner = getattr(b, "text", None)
            if inner is not None and not isinstance(inner, str):
                result.append({"type": "paragraph", "runs": runs_of(inner)})
            else:
                log.warning("rich_message: пропущен неизвестный блок %s", name)
    return result


def blocks_plain_text(blocks: List[dict]) -> str:
    """Весь текст блоков одной строкой (для API, превью реплаев и списка чатов)."""
    parts = []
    for b in blocks:
        if b.get("runs"):
            parts.append("".join(r["t"] for r in b["runs"]).strip())
        elif b.get("type") == "list":
            parts.extend("".join(r["t"] for r in item).strip() for item in b["items"])
    return "\n".join(p for p in parts if p)

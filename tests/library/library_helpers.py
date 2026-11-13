import json
from pathlib import Path
from types import SimpleNamespace


class FakeParseError(Exception):
    pass


class FakeLoader:
    """.json 卡内容即字段字典；内容含 'BROKEN' 则解析失败；其它扩展名按文件名造卡。"""

    def __init__(self):
        self.calls: list[str] = []

    def __call__(self, path):
        path = Path(path)
        self.calls.append(path.name)
        if path.suffix.lower() != ".json":
            return make_card(name=path.stem)
        text = path.read_text(encoding="utf-8")
        if "BROKEN" in text:
            raise FakeParseError("not a card")
        return make_card(**json.loads(text))


def make_card(**kw):
    base = dict(
        name="", description="", personality="", scenario="", first_mes="",
        mes_example="", alternate_greetings=[], creator="", creator_notes="", tags=[],
        character_version="", system_prompt="", post_history_instructions="",
        character_book=None, extensions={}, spec="chara_card_v3", raw={},
        regex_scripts=[], scripts=[],
    )
    base.update(kw)
    return SimpleNamespace(**base)


def write_card(root: Path, rel: str, **fields) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(fields, ensure_ascii=False), encoding="utf-8")
    return p

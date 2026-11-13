from pathlib import Path
from collections import Counter
import copy
import hashlib
import json
import re

folder = Path(__file__).resolve().parents[1]
review_path = folder / "新闻问题_审核稿.txt"
cards_path = folder / "新闻卡片.json"
review_bytes = review_path.read_bytes()
review_text = review_bytes.decode("utf-8-sig")
cards = json.loads(cards_path.read_text(encoding="utf-8"))
before = copy.deepcopy(cards)
groups = {}
types = Counter()
active = None
for line_number, raw_line in enumerate(review_text.splitlines(), 1):
    line = raw_line.strip()
    if not line:
        continue
    header = re.fullmatch(r"(E\d{3})\s+(.+)", line)
    if header:
        active = header.group(1)
        assert active not in groups, f"重复新闻编号：{active}"
        groups[active] = []
        continue
    if active is None:
        assert line == "新闻问题审核稿" or line.startswith("核查时点："), (line_number, line)
        continue
    question = re.fullmatch(r"(\d+)\.\s*(【(开放|事实)】)\s*(.+)", line)
    assert question is not None, f"未识别的题目行{line_number}：{line}"
    assert int(question.group(1)) == len(groups[active]) + 1, f"题号不连续：{active}，行{line_number}"
    groups[active].append(question.group(2) + question.group(4))
    types[question.group(3)] += 1

assert len(cards) == len(groups) == 30
assert set(groups) == {card["id"] for card in cards}
for card in cards:
    questions = groups[card["id"]]
    assert questions, f"新闻没有题目：{card['id']}"
    assert len(questions) == len(set(questions)), f"重复题目：{card['id']}"
    card["questions"] = questions
for original, revised in zip(before, cards):
    assert {k: v for k, v in original.items() if k != "questions"} == {
        k: v for k, v in revised.items() if k != "questions"
    }
serialized = json.dumps(cards, ensure_ascii=False, indent=2) + "\n"
assert json.loads(serialized) == cards

archive = folder / ".history" / "2026-11-14_整合审核问题前"
suffix = 1
while archive.exists():
    archive = folder / ".history" / f"2026-11-14_整合审核问题前_{suffix}"
    suffix += 1
assert cards_path.resolve().parent == folder.resolve()
assert archive.resolve().is_relative_to(folder.resolve())
archive.mkdir(parents=True)
cards_path.rename(archive / cards_path.name)
with cards_path.open("x", encoding="utf-8", newline="\n") as handle:
    handle.write(serialized)

written = json.loads(cards_path.read_text(encoding="utf-8"))
assert written == cards
assert all(card["questions"] == groups[card["id"]] for card in written)
assert review_path.read_bytes() == review_bytes
report = {
    "news_cards": len(cards),
    "questions": sum(len(card["questions"]) for card in cards),
    "question_types": dict(types),
    "count_distribution": dict(Counter(len(card["questions"]) for card in cards)),
    "per_news": {card["id"]: len(card["questions"]) for card in cards},
    "review_text_sha256": hashlib.sha256(review_bytes).hexdigest(),
    "review_text_unchanged": True,
    "non_question_fields_unchanged": True,
    "question_text_preserved": True,
    "format": "字符串数组；保留题型标签，移除行号",
    "backup": str(archive / cards_path.name)
}
with (archive / "整合核对结果.json").open("x", encoding="utf-8", newline="\n") as handle:
    json.dump(report, handle, ensure_ascii=False, indent=2)
    handle.write("\n")
print(json.dumps(report, ensure_ascii=False))

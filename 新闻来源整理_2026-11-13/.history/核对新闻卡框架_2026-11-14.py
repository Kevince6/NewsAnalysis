from pathlib import Path
from datetime import date
import hashlib
import json

folder = Path(__file__).resolve().parents[1]
schema = json.loads((folder / "新闻卡.schema.json").read_text(encoding="utf-8"))
cards = json.loads((folder / "新闻卡示例.json").read_text(encoding="utf-8"))
required = set(schema["$defs"]["card"]["required"])
news_ids = set()
quotes = []
for card in cards:
    assert set(card) == required
    assert card["id"] not in news_ids
    news_ids.add(card["id"])
    cutoff = date.fromisoformat(card["as_of"])
    assert isinstance(card["category"], str)
    assert isinstance(card["questions"], list)
    sources = {source["id"]: source for source in card["sources"]}
    assert len(sources) == len(card["sources"])
    fact_ids = set()
    for fact in card["facts"]:
        assert fact["id"] not in fact_ids
        fact_ids.add(fact["id"])
        assert fact["text"] and fact["evidence"]
        for evidence in fact["evidence"]:
            assert evidence["source_id"] in sources and evidence["quote"]
            quotes.append(evidence["quote"])
        for values in fact.get("attrs", {}).values():
            assert isinstance(values, list) and values
            assert all(isinstance(value, str) and value.strip() for value in values)
    for source in sources.values():
        assert source["url"].startswith("https://")
        if "published_at" in source:
            assert date.fromisoformat(source["published_at"]) <= cutoff
expected = {
    "新闻来源数据.json": "334ee9c847cc340378467efc38187e2c543a63f3db92920681dc44f905d76700",
    "30条新闻来源_简洁版.html": "4b5901dc9d6365430ae9471fe7c5cf983bf31ed2fed172e314f3bb6b3ee61a47",
}
assert all(hashlib.sha256((folder / name).read_bytes()).hexdigest() == digest
           for name, digest in expected.items())
print(json.dumps({"cards": len(cards), "facts": sum(len(c["facts"]) for c in cards),
                  "old_files_unchanged": True, "quotes": quotes}, ensure_ascii=False))

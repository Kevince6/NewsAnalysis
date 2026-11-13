from pathlib import Path
from datetime import date
from urllib.parse import urlsplit
import copy
import hashlib
import json
import re
import runpy

root = Path(__file__).resolve().parent
folder = root.parents[1]
registry_path = folder / "新闻来源数据.json"
html_path = folder / "30条新闻来源_简洁版.html"
before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (registry_path, html_path)}
registry = json.loads(registry_path.read_text(encoding="utf-8"))
originals = {event["id"]: event for event in registry["events"]}
drafts = json.loads((root / "事实复核稿.json").read_text(encoding="utf-8"))
sources = {s["id"]: copy.deepcopy(s) for e in registry["events"] for s in e["sources"]}
sources.update({
    "E014-S5": {
        "id": "E014-S5", "title": "Case on Impeachment Trial of President (Yoon Suk Yeol), 2024Hun-Na8",
        "publisher": "韩国宪法法院（英文案件检索）",
        "url": "https://www.ccourt.go.kr/site/eng/decisions/casesearch/caseSearch.do"
    },
    "E023-S4": {
        "id": "E023-S4", "title": "张碧晨：今后将不再演唱《年轮》",
        "publisher": "中国新闻周刊｜新浪财经转载",
        "url": "https://finance.sina.com.cn/cj/2025-07-25/doc-infhswis3072721.shtml",
        "date": "2025-07-25"
    },
    "E024-S4": {
        "id": "E024-S4", "title": "人口贩运受害者、中国籍演员王星已回国",
        "publisher": "央视新闻｜第一财经转载",
        "url": "https://www.yicai.com/news/102437430.html", "date": "2025-01-11"
    }
})
sources["E028-S1"]["url"] = "https://www.info.gov.hk/gia/general/202610/29/P2026102900476.htm"
sources["E028-S1"]["title"] = "政府公開就大埔宏福苑火災成立的獨立委員會報告"
sources["E009-S3"]["title"] = "Meta收购Moltbook（TechCrunch报道）"

# These are publication dates, not event dates or dates printed in report titles.
publication_dates = {
    "E002-S2": "2026-11-13", "E011-S1": "2026-11-06", "E011-S2": "2026-11-09",
    "E021-S2": "2025-07-21", "E023-S2": "2025-07-26", "E028-S3": "2026-10-29"
}
unknown_publication_dates = {"E005-S1", "E005-S2", "E008-S1", "E014-S5"}

# Literal wording was checked again against the source, rather than paraphrased as a quote.
literal_fixes = {
    ("E008", 1, 1): "Both are now in U.S. custody",
    ("E012", 4, 1): "ByteDance retains 19.9% of the Joint Venture.",
    ("E027", 3, 1): "要求英伟达公司就对华销售的H20算力芯片漏洞后门安全风险问题进行说明并提交相关证明材料。",
    ("E012", 2, 0): "in the process of restoring service",
}
for card in drafts:
    for index, fact in enumerate(card["facts"], 1):
        for ev_index, evidence in enumerate(fact["evidence"]):
            key = (card["id"], index, ev_index)
            if key in literal_fixes:
                evidence["quote"] = literal_fixes[key]

audit = runpy.run_path(str(root / "核对草稿.py"))
normalize, canonical, corpus = audit["normalize"], audit["canonical"], audit["corpus"]
cards, trace = [], []
for draft in drafts:
    event_id = draft["id"]
    event = originals[event_id]
    facts = []
    used_sources = set()
    for index, item in enumerate(draft["facts"], 1):
        fact = {"id": f"{event_id}-F{index}", **item}
        for ev in fact["evidence"]:
            used_sources.add(ev["source_id"])
            key = canonical(sources[ev["source_id"]]["url"])
            hits = [name for name, urls, body in corpus if key in urls and normalize(ev["quote"]) in body]
            assert hits, (fact["id"], ev)
            trace.append({"fact_id": fact["id"], "source_id": ev["source_id"], "quote": ev["quote"], "cache_files": hits})
        facts.append(fact)
    card_sources = []
    for source_id in sorted(used_sources, key=lambda value: int(value.split("-S")[1])):
        source = sources[source_id]
        item = {key: source[key] for key in ("id", "title", "publisher", "url")}
        if source_id not in unknown_publication_dates:
            value = publication_dates.get(source_id)
            if value is None:
                match = re.match(r"\d{4}-\d{2}-\d{2}", source.get("date", ""))
                if match:
                    value = match.group()
            if value is not None:
                item["published_at"] = value
        card_sources.append(item)
    card = {
        "id": event_id, "title": event["title"], "category": event["category"],
        "summary": draft["summary"], "note": draft["note"], "as_of": "2026-11-14",
        "questions": [], "facts": facts, "sources": card_sources
    }
    cards.append(card)

# Check the properties used by the approved schema, plus reference integrity and cutoff dates.
schema = json.loads((folder / "新闻卡.schema.json").read_text(encoding="utf-8"))
def validate(instance, rule):
    if "$ref" in rule:
        return validate(instance, schema["$defs"][rule["$ref"].split("/")[-1]])
    kind = rule.get("type")
    expected = {"object": dict, "array": list, "string": str}
    if kind:
        assert isinstance(instance, expected[kind]), (kind, instance)
    if isinstance(instance, dict):
        assert set(rule.get("required", [])) <= set(instance)
        assert len(instance) >= rule.get("minProperties", 0)
        properties = rule.get("properties", {})
        if rule.get("additionalProperties") is False:
            assert set(instance) <= set(properties)
        for key, value in instance.items():
            if "propertyNames" in rule:
                validate(key, rule["propertyNames"])
            if key in properties:
                validate(value, properties[key])
            elif isinstance(rule.get("additionalProperties"), dict):
                validate(value, rule["additionalProperties"])
    elif isinstance(instance, list):
        assert len(instance) >= rule.get("minItems", 0)
        if rule.get("uniqueItems"):
            assert len({json.dumps(value, ensure_ascii=False, sort_keys=True) for value in instance}) == len(instance)
        if "items" in rule:
            for value in instance:
                validate(value, rule["items"])
    elif isinstance(instance, str):
        assert len(instance) >= rule.get("minLength", 0)
        if "pattern" in rule:
            assert re.search(rule["pattern"], instance), instance
        if rule.get("format") == "date":
            assert date.fromisoformat(instance).isoformat() == instance
        if rule.get("format") == "uri":
            assert urlsplit(instance).scheme in {"http", "https"} and urlsplit(instance).netloc

validate(cards, schema)
assert [card["id"] for card in cards] == [f"E{i:03d}" for i in range(1, 31)]
all_ids = []
for card in cards:
    assert 3 <= len(card["facts"]) <= 5
    assert 1 <= len(card["sources"]) <= 5
    assert card["questions"] == []
    source_ids = {source["id"] for source in card["sources"]}
    assert len(source_ids) == len(card["sources"])
    for source in card["sources"]:
        assert source["id"].startswith(card["id"] + "-S")
        if "published_at" in source:
            assert source["published_at"] <= card["as_of"]
    for fact in card["facts"]:
        assert all(ev["source_id"] in source_ids for ev in fact["evidence"])
    all_ids.extend([card["id"], *(f["id"] for f in card["facts"]), *source_ids])
assert len(all_ids) == len(set(all_ids))
assert "相对日期与主办方公告存在文字矛盾" in cards[16]["note"]
assert all(hashlib.sha256((folder / name).read_bytes()).hexdigest() == digest for name, digest in before.items())

target = folder / "新闻卡片.json"
if target.exists():
    archive = root / "生成前版本"
    suffix = 1
    while archive.exists():
        archive = root / f"生成前版本_{suffix}"
        suffix += 1
    assert target.resolve().parent == folder.resolve()
    assert archive.resolve().is_relative_to(folder.resolve())
    archive.mkdir()
    target.rename(archive / target.name)
with target.open("x", encoding="utf-8", newline="\n") as handle:
    json.dump(cards, handle, ensure_ascii=False, indent=2)
    handle.write("\n")
report = {
    "cards": len(cards), "facts": sum(len(c["facts"]) for c in cards),
    "sources": sum(len(c["sources"]) for c in cards), "evidence": len(trace),
    "as_of": "2026-11-14", "questions_all_empty": True,
    "approved_schema_constraints_checked": True, "broken_source_references": 0,
    "source_quote_matches": len(trace), "other_working_files_unchanged": True,
    "user_confirmed_date_choice": "E017使用2026-03-28，并保留相对日期文字矛盾说明",
    "quote_trace": trace
}
report_path = root / "交付检查结果.json"
suffix = 1
while report_path.exists():
    report_path = root / f"交付检查结果_{suffix}.json"
    suffix += 1
with report_path.open("x", encoding="utf-8", newline="\n") as handle:
    json.dump(report, handle, ensure_ascii=False, indent=2)
    handle.write("\n")
print(json.dumps({key: value for key, value in report.items() if key != "quote_trace"}, ensure_ascii=False))

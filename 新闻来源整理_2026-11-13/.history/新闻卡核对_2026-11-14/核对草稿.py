from pathlib import Path
import json
import re
from urllib.parse import unquote, urlsplit

root = Path(__file__).resolve().parent
registry = json.loads((root.parents[1] / "新闻来源数据.json").read_text(encoding="utf-8"))
sources = {s["id"]: s for e in registry["events"] for s in e["sources"]}
sources.update({
    "E014-S5": {"url": "https://www.ccourt.go.kr/site/eng/decisions/casesearch/caseSearch.do"},
    "E023-S4": {"url": "https://finance.sina.com.cn/cj/2025-07-25/doc-infhswis3072721.shtml"},
    "E024-S4": {"url": "https://www.yicai.com/news/102437430.html"},
})
sources["E028-S1"] = {**sources["E028-S1"], "url": "https://www.info.gov.hk/gia/general/202610/29/P2026102900476.htm"}
def normalize(value):
    value = re.sub(r"^L\d+(?:@P\d+(?:-\d+)?)?:\s?", "", value, flags=re.M)
    value = re.sub(r"【\d+†([^†】]+)(?:†[^】]+)?】", r"\1", value)
    value = re.sub(r"\^\{[^}]*\}", "", value)
    return re.sub(r"\s+", " ", value).strip()
def canonical(url):
    parts = urlsplit(unquote(url))
    if "apnews.com" in parts.netloc:
        identifier = re.search(r"([0-9a-f]{30,32})$", parts.path)
        if identifier:
            return "ap:" + identifier.group(1)
    return parts.netloc.removeprefix("www.") + parts.path.rstrip("/") + ("?" + parts.query if parts.query else "")
corpus = []
for path in root.glob("*.txt"):
    for part in path.read_text(encoding="utf-8").split("--------------------------------------------------------------------------------"):
        head = part.split("cite", 1)[0]
        links = re.findall(r"https?://[^\s)]+", head)
        corpus.append((path.name, {canonical(url) for url in links}, normalize(part)))
drafts = []
for path in sorted(root.glob("事实草稿_*.json")):
    drafts.extend(json.loads(path.read_text(encoding="utf-8")))
failures, matches = [], []
for card in drafts:
    for index, fact in enumerate(card["facts"], 1):
        for ev in fact["evidence"]:
            expected = canonical(sources[ev["source_id"]]["url"])
            hits = [name for name, urls, body in corpus if expected in urls and normalize(ev["quote"]) in body]
            item = {"fact": card["id"] + "-F" + str(index), "source": ev["source_id"], "quote": ev["quote"]}
            if hits:
                matches.append({**item, "files": hits})
            else:
                elsewhere = [name for name, urls, body in corpus if normalize(ev["quote"]) in body]
                failures.append({**item, "elsewhere": elsewhere})
report = {"cards": len(drafts), "facts": sum(len(c["facts"]) for c in drafts),
          "matched_evidence": len(matches), "unmatched": failures, "matches": matches}
report_path = root / "摘录检查_初次.json"
if not report_path.exists():
    with report_path.open("x", encoding="utf-8") as target:
        json.dump(report, target, ensure_ascii=False, indent=2)
print(json.dumps({key: value for key, value in report.items() if key != "matches"}, ensure_ascii=False))

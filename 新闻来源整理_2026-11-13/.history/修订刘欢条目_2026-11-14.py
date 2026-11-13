from pathlib import Path
import copy
import html
import json
import re

folder = Path(__file__).resolve().parents[1]
page = folder / "30条新闻来源_简洁版.html"
data_path = folder / "新闻来源数据.json"
old_html = page.read_text(encoding="utf-8")
old_json = data_path.read_text(encoding="utf-8")
registry = json.loads(old_json)
original_events = copy.deepcopy(registry["events"])
event = next(e for e in registry["events"] if e["id"] == "E002")
event.update({
    "title": "刘欢病逝：主要死因为感染性休克",
    "coverage": "2026-11-13（11月12日公开信、次日全文刊载）",
    "status": "家属已披露主要死因",
    "revised_at": "2026-11-14",
    "summary": "刘欢于2026年9月25日在上海病逝，享年63岁。[1] 11月12日，妻子卢璐委托水均益发布公开信，披露死亡医学证明书所载主要死因为感染性休克，并说明其曾长期患膀胱癌。癌症病史应与此次披露的主要死因区分。[2] 关于股骨头缺血性坏死，卢璐称他2009年已接受人工髋关节置换，术后康复、基本未再出问题，并澄清网传“不死癌症”说法；不能将这段骨病史写成此次死亡原因。[2]",
    "note": "根据11月12日家属公开信修订。主要死因采用家属转述的死亡医学证明书字段；区分癌症病史和主要死因，不据此推断癌症与临终感染完全无关。旧版“具体死因未披露”已经过时。"
})
event["sources"] = [event["sources"][0], {
    "title": "刘欢妻子卢璐8000字公开信全文公布",
    "publisher": "卢璐公开信｜水均益受托发布，新湖南全文刊载",
    "date": "2026-11-12（新湖南11月13日刊载）",
    "url": "https://m.voc.com.cn/xhn/news/202611/34246958.html",
    "kind": "权威媒体转引当事方",
    "role": "全文核实死亡医学证明书所载主要死因、膀胱癌病史，以及2009年股骨头旧病手术康复的说明。",
    "access": "正文已核读",
    "id": "E002-S2"
}]
registry["updated_at"] = "2026-11-14"
escape = lambda value: html.escape(str(value), quote=True)
summary = re.sub(r"\[(\d+)\]", lambda m: '<a class="ref" href="#E002-S' + m.group(1) + '">[' + m.group(1) + ']</a>', escape(event["summary"]))
source_lines = []
for i, source in enumerate(event["sources"], 1):
    source_lines.append(
        '<li id="E002-S' + str(i) + '"><a class="source" href="' + escape(source["url"]) +
        '" target="_blank" rel="noopener noreferrer">' + escape(source["title"]) +
        '</a> <span class="meta">— ' + escape(source["publisher"]) + '，' +
        escape(source["date"]) + '</span></li>'
    )
new_section = (
    '<section id="E002">\n<h2>2. ' + escape(event["title"]) +
    ' <span class="category">' + escape(event["category"]) +
    '</span></h2>\n<p>' + summary + '</p>\n<ol>' +
    "\n".join(source_lines) + '</ol>\n</section>'
)
match = re.search(r'<section id="E002">.*?</section>', old_html, re.S)
assert match is not None
new_html = old_html[:match.start()] + new_section + old_html[match.end():]
for old_event, new_event in zip(original_events, registry["events"]):
    if old_event["id"] != "E002":
        assert old_event == new_event
assert len(registry["events"]) == 30
assert sum(len(e["sources"]) for e in registry["events"]) == 79
assert '具体死因未披露' not in new_section and '这份当事单位讣告没有披露具体疾病或医学死因' not in new_section
assert new_html.count('<section id=') == 30
assert new_html.count('class="source"') == 79

archive = folder / ".history" / "2026-11-14_刘欢修订前"
suffix = 1
while archive.exists():
    archive = folder / ".history" / ("2026-11-14_刘欢修订前_" + str(suffix))
    suffix += 1
archive.mkdir(parents=True)
page.rename(archive / page.name)
data_path.rename(archive / data_path.name)
with page.open("x", encoding="utf-8", newline="\n") as target:
    target.write(new_html)
with data_path.open("x", encoding="utf-8", newline="\n") as target:
    target.write(json.dumps(registry, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({
    "updated": str(page),
    "archive": str(archive),
    "topics": len(registry["events"]),
    "sources": sum(len(e["sources"]) for e in registry["events"]),
    "liuhuan_sources": len(event["sources"]),
    "other_topics_unchanged": True
}, ensure_ascii=False))


from pathlib import Path
import copy
import html
import json
import re

folder = Path(__file__).resolve().parents[1]
page = folder / "30条新闻来源_简洁版.html"
data_path = folder / "新闻来源数据.json"
old_html = page.read_text(encoding="utf-8")
registry = json.loads(data_path.read_text(encoding="utf-8"))
original_events = copy.deepcopy(registry["events"])
event = next(e for e in registry["events"] if e["id"] == "E005")
paragraphs = [
    "2026年11月3日，美国改选众议院全部435席及参议院35席，民主党夺回两院控制权。[1][2] 按Ballotpedia美东时间11月12日10时汇总，众院民主党254席、共和党165席、16席未决；参院民主党阵营55席、共和党44席、1席未决（民主党阵营含2名独立议员；以上为机构判定，非最终认证）。[2]",
    "参院由选前共和党53比47领先，转为民主党阵营净增8席。关键翻转包括得州的詹姆斯·塔拉里科、俄亥俄州的谢罗德·布朗；11月11日，密西西比州的斯科特·科洛姆又被判定击败共和党现任议员辛迪·海德—史密斯，为民主党再添一席。[2]",
    "选后将形成民主党控制国会、共和党总统特朗普掌握行政部门的分权局面。PNC经济研究团队认为，预算、税收等重大立法需要跨党谈判，民主党席位仍不足以单独推翻总统否决。[3] 争议也延伸至民主党内部：克里斯·范霍伦11月12日宣布挑战查克·舒默，争夺下一届参院民主党领袖，党内投票定于12月上旬。[4]",
]
event.update({
    "title": "2026年美国中期选举：两院易手与关键翻转席位",
    "coverage": "席位为2026-11-12美东10:00快照；选后领袖竞逐报道截至11月13日",
    "status": "补充席位对比、关键州翻转及选后影响",
    "summary": "\n\n".join(paragraphs),
    "note": "参院55席为民主党阵营口径，含2名独立议员，由未改选席位与本次胜选席位合计；本次35席中民主党赢21席，共和党13席，1席未决。众院254+165+16=435。所有席位数注明Ballotpedia快照时间，不称最终认证。PNC对立法谈判的判断明确归属研究团队；范霍伦宣布挑战的当地日期为11月12日，AP报道UTC日期为11月13日。",
    "revised_at": "2026-11-14",
})
event["sources"] = [
    event["sources"][0],
    {
        "id": "E005-S2",
        "title": "Election results, 2026: U.S. Congress（席位表及关键州判定时间线）",
        "publisher": "Ballotpedia",
        "date": "2026-11-12 10:00 EST（所读版本更新时间）",
        "url": "https://ballotpedia.org/Election_results,_2026:_U.S._Congress",
        "kind": "可信专业机构",
        "role": "直接核读435席众院254/165/16表、35席参院21/13/1表，及选前53/47、两名独立议员口径；参院阵营55/44/1含未改选席位。时间线列出得州、俄亥俄、密西西比等州易手及11月11日科洛姆胜选判定。",
        "access": "正文已核读",
    },
    {
        "id": "E005-S3",
        "title": "2026 Midterm elections: Implications of a divided government（第1—2页）",
        "publisher": "PNC Economics Research",
        "date": "2026-11-06",
        "url": "https://www.pnc.com/content/dam/pnc-com/pdf/aboutpnc/EconomicReports/EconomicUpdates/2026/PNC_Econ_Research_2026_Midterms.pdf#page=1",
        "kind": "机构分析原文",
        "role": "说明两院控制权变化后与共和党总统形成分权政府，及预算、税收立法和总统否决权约束。此项为署名经济研究分析，不冒充官方选举认证或已经发生的政策结果。",
        "access": "正文已核读",
    },
    {
        "id": "E005-S4",
        "title": "Van Hollen to challenge Schumer for Senate Democratic leader",
        "publisher": "美联社 AP",
        "date": "2026-11-13（UTC报道；当地11月12日宣布）",
        "url": "https://apnews.com/article/6d74c189cb6c065c9a810a1cf1a53436",
        "kind": "可信媒体",
        "role": "核实范霍伦公开挑战舒默、争夺新一届参院民主党领袖，党内秘密投票在12月上旬；不将宣布参选写成已当选。",
        "access": "检索返回的报道正文已核读",
    },
]
registry["updated_at"] = "2026-11-14"
escape = lambda value: html.escape(str(value), quote=True)
def render_paragraph(text):
    return "<p>" + re.sub(r"\[(\d+)\]", lambda m:
        '<a class="ref" href="#E005-S' + m.group(1) + '">[' + m.group(1) + ']</a>',
        escape(text)) + "</p>"
sources_html = []
for item in event["sources"]:
    sources_html.append('<li id="' + item["id"] + '"><a class="source" href="' +
        escape(item["url"]) + '" target="_blank" rel="noopener noreferrer">' +
        escape(item["title"]) + '</a> <span class="meta">— ' +
        escape(item["publisher"]) + '，' + escape(item["date"]) + '</span></li>')
section = '<section id="E005">\n<h2>5. ' + escape(event["title"]) + \
    ' <span class="category">' + escape(event["category"]) + '</span></h2>\n' + \
    '\n'.join(render_paragraph(text) for text in paragraphs) + '\n<ol>' + \
    '\n'.join(sources_html) + '</ol>\n</section>'
new_html, count = re.subn(r'<section id="E005">.*?</section>', lambda m: section,
                           old_html, count=1, flags=re.S)
assert count == 1
for before, after in zip(original_events, registry["events"]):
    if before["id"] != "E005":
        assert before == after
        pattern = '<section id="' + before["id"] + '">.*?</section>'
        assert re.search(pattern, old_html, re.S).group() == re.search(pattern, new_html, re.S).group()
assert set(re.findall(r"\[(\d+)\]", event["summary"])) == {"1", "2", "3", "4"}
assert len(registry["events"]) == new_html.count('<section id=') == 30
assert new_html.count('class="source"') == sum(len(e["sources"]) for e in registry["events"]) == 93
assert not re.search(r'<(?:button|input|aside|details|h3)\b', new_html)
archive = folder / ".history" / "2026-11-14_美国选举重写前"
suffix = 1
while archive.exists():
    archive = folder / ".history" / ("2026-11-14_美国选举重写前_" + str(suffix))
    suffix += 1
archive.mkdir(parents=True)
page.rename(archive / page.name)
data_path.rename(archive / data_path.name)
with page.open("x", encoding="utf-8", newline="\n") as target:
    target.write(new_html)
with data_path.open("x", encoding="utf-8", newline="\n") as target:
    target.write(json.dumps(registry, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({"updated": "E005", "summary_chars": len(event["summary"]),
                  "sources_in_topic": 4, "total_sources": 93, "other_topics_unchanged": True}, ensure_ascii=False))

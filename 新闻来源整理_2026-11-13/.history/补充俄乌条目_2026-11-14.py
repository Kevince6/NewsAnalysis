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
event = next(e for e in registry["events"] if e["id"] == "E003")
paragraphs = [
    "截至2026年11月13日，俄乌跨境袭击仍在持续。联合国9月月报核实乌克兰当月有328名平民死亡、2105人受伤。[1] 11月13日美联社转述当地通报：俄境内三地袭击致7死17伤；乌克兰扎波罗热一次住宅楼袭击致30人受伤，其中6名儿童。[2] 前者是月度核实数据，后者是局部事件通报，均非双方军队总伤亡。",
    "斡旋方面，俄、美、乌11月10—11日在阿联酋阿布扎比会谈，达成大规模换俘的原则性安排；俄方称拟各向对方移交超过1000名被俘人员，具体落实仍待后续，领土、停火和安全保障等问题仍有重大分歧。[3] 乌总统府13日公告确认，泽连斯基在都柏林会见美国特使威特科夫、库什纳，讨论换俘、欧洲代表参与和后续多边会晤。[4] 这些接触尚不等于达成全面停火。"
]
event.update({
    "title": "俄乌战争：近期伤亡与斡旋进展（截至2026年11月13日）",
    "coverage": "2026-11-13（北京时间11月14日检索；联合国月度数据对应9月）",
    "status": "交战持续，换俘安排待落实",
    "revised_at": "2026-11-14",
    "summary": "\n\n".join(paragraphs),
    "note": "区分联合国核实的2026年9月乌克兰平民伤亡、11月13日俄乌局部袭击的当地通报和双方军队伤亡；三者不能替代或相加。换俘人数来自俄方关于拟议安排的表述，不表示已经完成交换；欧洲参与外交协调不等于已加入本轮俄美乌三方会议。"
})
event["sources"] = [
    {
        "id": "E003-S1",
        "title": "Protection of Civilians in Armed Conflict — September 2026",
        "publisher": "联合国人权高专办驻乌克兰人权监测团",
        "date": "2026-10-15（统计2026年9月）",
        "url": "https://ukraine.ohchr.org/en/Protection-of-Civilians-in-Armed-Conflict-September-2026",
        "kind": "官方原文",
        "role": "直接核实9月乌克兰平民328人死亡、2105人受伤；不是11月或俄乌军人总伤亡。",
        "access": "正文已核读"
    },
    {
        "id": "E003-S2",
        "title": "Ukraine launches nearly 1,200 drones at Russia as US-led talks to consider wider European security",
        "publisher": "美联社 AP｜转述俄乌当地部门通报",
        "date": "2026-11-13",
        "url": "https://apnews.com/article/russia-ukraine-war-putin-trump-zelenskyy-europe-157d168cb7ff9cae318cbf6cecb3988f",
        "kind": "可信媒体",
        "role": "核实俄境内三地7死17伤及扎波罗热单次袭击30人受伤的最新正文通报；数字仍可能更新。",
        "access": "正文已核读"
    },
    {
        "id": "E003-S3",
        "title": "俄美乌会谈达成换俘协议 仍存重大分歧",
        "publisher": "新华社｜人民网转载",
        "date": "2026-11-12（报道当地11月11日会谈结果）",
        "url": "https://world.people.com.cn/n1/2026/1112/c1002-40832302.html",
        "kind": "权威媒体",
        "role": "核实三方会谈地点、日期、拟议换俘规模及领土、安全保障等未决问题；明确超过1000人是俄方关于拟议安排的说法。",
        "access": "正文已核读"
    },
    {
        "id": "E003-S4",
        "title": "Volodymyr Zelenskyy Discussed Outcomes of This Week’s Negotiations with Steve Witkoff and Jared Kushner",
        "publisher": "乌克兰总统府",
        "date": "2026-11-13",
        "url": "https://www.president.gov.ua/en/news/volodimir-zelenskij-obgovoriv-zi-stivenom-vitkoffom-i-dzhare-107325",
        "kind": "当事方原文",
        "role": "直接核实泽连斯基在都柏林会见美国两名特使，以及乌方对换俘、欧洲参与和后续多边会晤的表述。",
        "access": "正文已核读"
    }
]
registry["updated_at"] = "2026-11-14"
escape = lambda value: html.escape(str(value), quote=True)
def render_paragraph(value):
    return "<p>" + re.sub(r"\[(\d+)\]", lambda m: '<a class="ref" href="#E003-S' + m.group(1) + '">[' + m.group(1) + ']</a>', escape(value)) + "</p>"
sources_html = []
for i, source in enumerate(event["sources"], 1):
    sources_html.append(
        '<li id="E003-S' + str(i) + '"><a class="source" href="' + escape(source["url"]) +
        '" target="_blank" rel="noopener noreferrer">' + escape(source["title"]) +
        '</a> <span class="meta">— ' + escape(source["publisher"]) + '，' +
        escape(source["date"]) + '</span></li>'
    )
new_section = (
    '<section id="E003">\n<h2>3. ' + escape(event["title"]) +
    ' <span class="category">' + escape(event["category"]) +
    '</span></h2>\n' + "\n".join(render_paragraph(p) for p in paragraphs) +
    '\n<ol>' + "\n".join(sources_html) + '</ol>\n</section>'
)
match = re.search(r'<section id="E003">.*?</section>', old_html, re.S)
assert match is not None
new_html = old_html[:match.start()] + new_section + old_html[match.end():]
for old, new in zip(original_events, registry["events"]):
    if old["id"] != "E003":
        assert old == new
assert len(registry["events"]) == 30
total_sources = sum(len(e["sources"]) for e in registry["events"])
assert total_sources == 81
assert new_html.count('<section id=') == 30
assert new_html.count('class="source"') == total_sources
archive = folder / ".history" / "2026-11-14_俄乌补充前"
suffix = 1
while archive.exists():
    archive = folder / ".history" / ("2026-11-14_俄乌补充前_" + str(suffix))
    suffix += 1
archive.mkdir(parents=True)
page.rename(archive / page.name)
data_path.rename(archive / data_path.name)
with page.open("x", encoding="utf-8", newline="\n") as target:
    target.write(new_html)
with data_path.open("x", encoding="utf-8", newline="\n") as target:
    target.write(json.dumps(registry, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({
    "updated": "E003",
    "topics": len(registry["events"]),
    "sources": total_sources,
    "ukraine_sources": len(event["sources"]),
    "summary_characters": len(event["summary"]),
    "other_topics_unchanged": True
}))


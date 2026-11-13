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
event = next(e for e in registry["events"] if e["id"] == "E004")
paragraphs = [
    "法国内政部11月7日通报，全国约14.6万人参加141场行动，其中巴黎约4.6万人（官方示威人数估计，不是骚乱参与者人数）。[3]",
    "巴黎警方11月6日公报记载：10月17日相关事件中855人被拘捕，297名执法人员及111名居民、示威者受伤；18日又有351人被拘捕，36家商店受损，其中33家被抢掠（警方事后通报，PDF第36页；拘捕不等于定罪）。[1]",
    "使馆10月30日记载的10月31日申报路线为：巴士底广场→共和国广场→圣殿街→歌剧院广场→协和广场（当时尚待警方审批）。[2] 另据法国最高行政法院10月31日裁定，CGT等工会游行原拟的“巴士底—民族广场”路线被限制，可走巴尼奥莱门→沿元帅大道→沙朗通门（该场游行获准的替代路线，不能与使馆所列申报路线混写）。[4]",
    "巴黎市政府10月28日说明，将向受损商户援助基金出资300万欧元，并已动员2000余名市政工作人员恢复公共空间（援助与处置投入，不是损失估价；该页未列核定损失总额）。[5]"
]
event.update({
    "title": "2026年秋巴黎示威与骚乱",
    "coverage": "2026-11-07（11月14日复核；路线、损毁及援助信息分别注明原日期）",
    "status": "官方数字、申报路线与获准路线分别标注",
    "revised_at": "2026-11-14",
    "summary": "\n\n".join(paragraphs),
    "note": "示威人数估计不是骚乱人数；全国与巴黎口径分开，拘捕不等于定罪。使馆10月30日记录的申报路线与最高行政法院10月31日裁定涉及的CGT等工会游行路线是不同文件中的路线，不将其拼接为一条已批准路线。300万欧元为巴黎市对援助基金的出资，不是经济损失总额。警方数据见行政公报PDF第36页。"
})
event["sources"] = [
    {
        "id": "E004-S1",
        "title": "Recueil des actes administratifs spécial n°75-2026-667（第36页）",
        "publisher": "巴黎警察局｜法兰西岛大区政府网站",
        "date": "2026-11-06",
        "url": "https://www.prefectures-regions.gouv.fr/ile-de-france/irecontenu/telechargement/142339/1034675/file/recueil-75-2026-667-recueil-des-actes-administratifs-special%20du%2006.11.2026.pdf#page=36",
        "kind": "官方原文",
        "role": "第36页记载10月17日855次拘捕、297名执法人员及111名居民/示威者受伤，18日351次拘捕、36家商店受损其中33家被抢掠；链接直接定位该页。",
        "access": "正文已核读"
    },
    {
        "id": "E004-S2",
        "title": "关于10月31日和11月5日游行示威的领事提醒",
        "publisher": "中国驻法国大使馆",
        "date": "2026-10-30",
        "url": "https://fr.china-embassy.gov.cn/zgzfg/zgsg/lsqwc/zytz/202610/t20261030_12050327.htm",
        "kind": "官方原文",
        "role": "官方网页记录巴士底—共和国—圣殿街—歌剧院—协和广场申报路线，并明确当时警方尚在审批；使馆说明信息来自媒体及新媒体平台，不等同法方批准文件。",
        "access": "正文已核读"
    },
    {
        "id": "E004-S3",
        "title": "Bilan de la mobilisation du 7 novembre 2026（11月7日示威情况通报）",
        "publisher": "法国内政部",
        "date": "2026-11-07",
        "url": "https://www.interieur.gouv.fr/actualites/actualites-du-ministere/bilan-de-mobilisation-du-7-novembre-2026-des-corteges-emailles-de-nombreux-incidents-dans-grandes",
        "kind": "官方原文",
        "role": "直接核实全国约146000名示威者、巴黎约46000名示威者及141场行动；这些数字不是骚乱参与者总数。",
        "access": "正文已核读"
    },
    {
        "id": "E004-S4",
        "title": "Décision n°521001（10月31日游行路线裁定）",
        "publisher": "法国最高行政法院 Conseil d’État",
        "date": "2026-10-31",
        "url": "https://www.conseil-etat.fr/fr/arianeweb/CE/decision/2026-10-31/521001",
        "kind": "官方原文",
        "role": "第2、7段及裁定结论核实工会原拟巴士底—民族广场路线受到限制，以及Porte de Bagnolet经boulevards des Maréchaux至Porte de Charenton的替代路线。",
        "access": "正文已核读"
    },
    {
        "id": "E004-S5",
        "title": "Violences et dégradations : près de 3 millions d’euros d’aides pour les commerçants",
        "publisher": "巴黎市政府 Ville de Paris",
        "date": "2026-10-28（网页更新时间）",
        "url": "https://www.paris.fr/pages/manifestations-du-17-octobre-pres-de-1000-agents-mobilises-une-cellule-d-aide-pour-les-commercants-36918",
        "kind": "官方原文",
        "role": "核实巴黎市出资300万欧元援助受损商户，以及2000余名市政人员恢复公共空间；出资金额不是损失估值。",
        "access": "正文已核读"
    }
]
registry["updated_at"] = "2026-11-14"
escape = lambda value: html.escape(str(value), quote=True)
def render_paragraph(value):
    return "<p>" + re.sub(r"\[(\d+)\]", lambda m: '<a class="ref" href="#E004-S' + m.group(1) + '">[' + m.group(1) + ']</a>', escape(value)) + "</p>"
sources_html = []
for i, source in enumerate(event["sources"], 1):
    sources_html.append(
        '<li id="E004-S' + str(i) + '"><a class="source" href="' + escape(source["url"]) +
        '" target="_blank" rel="noopener noreferrer">' + escape(source["title"]) +
        '</a> <span class="meta">— ' + escape(source["publisher"]) + '，' +
        escape(source["date"]) + '</span></li>'
    )
new_section = (
    '<section id="E004">\n<h2>4. ' + escape(event["title"]) +
    ' <span class="category">' + escape(event["category"]) +
    '</span></h2>\n' + "\n".join(render_paragraph(p) for p in paragraphs) +
    '\n<ol>' + "\n".join(sources_html) + '</ol>\n</section>'
)
match = re.search(r'<section id="E004">.*?</section>', old_html, re.S)
assert match is not None
new_html = old_html[:match.start()] + new_section + old_html[match.end():]
for old, new in zip(original_events, registry["events"]):
    if old["id"] != "E004":
        assert old == new
assert len(registry["events"]) == 30
total_sources = sum(len(e["sources"]) for e in registry["events"])
assert total_sources == 84
assert new_html.count('<section id=') == 30
assert new_html.count('class="source"') == total_sources
archive = folder / ".history" / "2026-11-14_巴黎补充前"
suffix = 1
while archive.exists():
    archive = folder / ".history" / ("2026-11-14_巴黎补充前_" + str(suffix))
    suffix += 1
archive.mkdir(parents=True)
page.rename(archive / page.name)
data_path.rename(archive / data_path.name)
with page.open("x", encoding="utf-8", newline="\n") as target:
    target.write(new_html)
with data_path.open("x", encoding="utf-8", newline="\n") as target:
    target.write(json.dumps(registry, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({
    "updated": "E004",
    "topics": len(registry["events"]),
    "sources": total_sources,
    "paris_sources": len(event["sources"]),
    "summary_characters": len(event["summary"]),
    "other_topics_unchanged": True
}))


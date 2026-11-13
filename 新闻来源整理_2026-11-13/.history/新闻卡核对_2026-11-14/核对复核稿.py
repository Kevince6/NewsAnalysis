from pathlib import Path
import json
import runpy

root = Path(__file__).resolve().parent
audit = runpy.run_path(str(root / "核对草稿.py"))
normalize, canonical = audit["normalize"], audit["canonical"]
corpus, sources = audit["corpus"], audit["sources"]
cards = json.loads((root / "事实复核稿.json").read_text(encoding="utf-8"))
failures, count = [], 0
for card in cards:
    for index, fact in enumerate(card["facts"], 1):
        for ev in fact["evidence"]:
            count += 1
            key = canonical(sources[ev["source_id"]]["url"])
            hits = [name for name, urls, body in corpus if key in urls and normalize(ev["quote"]) in body]
            if not hits:
                elsewhere = [name for name, urls, body in corpus if normalize(ev["quote"]) in body]
                failures.append({"fact": card["id"] + "-F" + str(index),
                                 "source": ev["source_id"], "quote": ev["quote"], "elsewhere": elsewhere})
print(json.dumps({"reviewed_cards": len(cards), "reviewed_facts": sum(len(c["facts"]) for c in cards),
                  "evidence": count, "unmatched": failures}, ensure_ascii=False))

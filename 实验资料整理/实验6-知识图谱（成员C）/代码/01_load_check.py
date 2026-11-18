import json
import sys
from pathlib import Path

# Windows 终端（尤其 Anaconda）可能是 GBK，先切 UTF-8 避免中文乱码/报错
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# 自动向上找到“实验资料整理”目录：脚本放在哪个子文件夹里都能用
HERE = Path(__file__).resolve().parent
ROOT = HERE
while ROOT.name != "实验资料整理" and ROOT.parent != ROOT:
    ROOT = ROOT.parent

E6 = ROOT / "实验6-知识图谱（成员C）" / "接口数据"
E2 = ROOT / "实验2-实体识别（成员A）" / "结果"

def load_routes():    return json.loads((E6 / "routes.json").read_text(encoding="utf-8"))
def load_advices():   return json.loads((E6 / "advices.json").read_text(encoding="utf-8"))
def load_entities():  return json.loads((E2 / "entities.json").read_text(encoding="utf-8"))

if __name__ == "__main__":
    print("定位到的根目录:", ROOT)
    routes, advices, entities = load_routes(), load_advices(), load_entities()
    print("路线数:", len(routes), "| 建议数:", len(advices), "| 实体文档数:", len(entities))
    from collections import Counter
    print("每景区路线:", dict(Counter(r["scenic"] for r in routes)))
    print("实体类型:", Counter(e["type"] for d in entities for e in d["entities"]))

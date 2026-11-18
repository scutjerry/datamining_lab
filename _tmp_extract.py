# -*- coding: utf-8 -*-
"""从任务书 docx 提取实验7 相关章节，输出到 txt 便于查看。"""
import sys
from docx import Document

src = r"C:\Users\Lenovo\OneDrive\Desktop\数据挖掘实验\实验资料整理\00-任务书与规范\《数据挖掘》探索性实验任务书及评分细则【Final】.docx"
out = r"C:\Users\Lenovo\OneDrive\Desktop\数据挖掘实验\_taskbook_exp7.txt"

doc = Document(src)
lines = []
for p in doc.paragraphs:
    t = p.text.strip()
    if t:
        lines.append(t)
for tbl in doc.tables:
    for row in tbl.rows:
        cells = [c.text.strip().replace("\n", " ") for c in row.cells]
        lines.append("| " + " | ".join(cells) + " |")

full = "\n".join(lines)
with open(out, "w", encoding="utf-8") as f:
    f.write(full)

# 打印实验7 段落
idx = [i for i, l in enumerate(lines) if ("实验7" in l or "实验七" in l or "Agent" in l or "规划" in l)]
print("命中行号:", idx[:60])
print("总行数:", len(lines))
for i in idx:
    lo, hi = max(0, i - 2), min(len(lines), i + 3)
    print("----", i)
    for j in range(lo, hi):
        print("   ", lines[j][:160])

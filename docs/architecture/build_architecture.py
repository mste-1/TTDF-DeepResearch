"""Build the standalone project introduction diagram and offline HTML viewer.

Run with Python's standard library: python docs/architecture/build_architecture.py
"""
from pathlib import Path
from html import escape
import json

OUT = Path(__file__).resolve().parent
parts = []

def add(s):
    parts.append(s)

def rect(x, y, w, h, fill, stroke="none", radius=16, extra=""):
    add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}" stroke="{stroke}" {extra}/>')

def text(x, y, value, size=22, fill="#24374B", weight=400, extra=""):
    add(f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" font-weight="{weight}" {extra}>{escape(value)}</text>')

def path(d, color="#8499AA", dash=False, arrow=True, width=2):
    marker = ' marker-end="url(#arrow-teal)"' if color == "#168A80" else ' marker-end="url(#arrow)"'
    add(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round"' + (' stroke-dasharray="7 7"' if dash else '') + (marker if arrow else '') + '/>')

def group(key):
    add(f'<g data-module="{key}">')

def end():
    add('</g>')

def chip(x, y, w, label, color="#EAF4F2", ink="#167A71", size=18):
    rect(x, y, w, 32, color, radius=16)
    text(x+w/2, y+22, label, size, ink, 500, 'text-anchor="middle"')

add('''<svg xmlns="http://www.w3.org/2000/svg" width="1800" height="1120" viewBox="0 0 1800 1120" role="img" aria-labelledby="architecture-title architecture-description">
<title id="architecture-title">Deep Research Agent 项目功能架构图</title>
<desc id="architecture-description">研究需求先转化为研究简报与报告初稿。研究主管调度多个子主题研究，调用联网搜索、去重和摘要能力，压缩并汇总研究笔记。主管按需修订草稿，依次进行质量评分和红队审阅，反馈进入下一轮研究。当研究结束后，综合研究发现与当前草稿生成带来源引用的报告。底层提供模型、联网搜索、研究上下文和过程管理能力。</desc>
<defs>
  <linearGradient id="page-wash" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#FBFCFE"/><stop offset="1" stop-color="#F0F5F7"/></linearGradient>
  <linearGradient id="navy-wash" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#193D53"/><stop offset="1" stop-color="#102B40"/></linearGradient>
  <linearGradient id="teal-wash" x1="0" y1="0" x2="1" y2="0"><stop stop-color="#E7F5F0"/><stop offset="1" stop-color="#F4F9F6"/></linearGradient>
  <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M1 1 L9 5 L1 9" fill="none" stroke="#8499AA" stroke-width="1.6"/></marker>
  <marker id="arrow-teal" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M1 1 L9 5 L1 9" fill="none" stroke="#168A80" stroke-width="1.6"/></marker>
  <filter id="soft-shadow" x="-10%" y="-15%" width="120%" height="140%"><feDropShadow dx="0" dy="7" stdDeviation="10" flood-color="#18394C" flood-opacity="0.055"/></filter>
</defs>
<style>text{font-family:"Microsoft YaHei","PingFang SC","Noto Sans CJK SC",sans-serif} .module-outline{stroke-width:1.3}</style>
''')
rect(0, 0, 1800, 1120, "url(#page-wash)", radius=0)
rect(64, 47, 34, 7, "#178C80", radius=3)
text(112, 58, "DEEP RESEARCH / FUNCTIONAL ARCHITECTURE", 17, "#526D80", 600, 'letter-spacing="2"')
text(64, 118, "从一个研究问题，到一份有据可循的报告", 42, "#142F43", 700)
text(64, 162, "Deep Research Agent", 23, "#2A5062", 600)
text(325, 162, "多智能体协作 · 自进化评估 · 对抗式降噪", 23, "#647D8C")
chip(1442, 102, 130, "多主题研究")
chip(1586, 102, 150, "反馈驱动改进")

# Three functional zones.
rect(64, 222, 274, 654, "#EEF2F6", "#DFE7EC", 22)
rect(374, 222, 1030, 654, "#FFFFFF", "#DCE6EB", 22, 'filter="url(#soft-shadow)"')
rect(1440, 222, 296, 654, "#EAF0F4", "#DCE6EB", 22)
for x, num, label in [(88,"01","需求与研究准备"),(414,"02","研究与改进引擎"),(1464,"03","研究成果交付")]:
    text(x, 269, num, 18, "#7C929F", 600)
    text(x+37, 269, label, 24, "#213E50", 600)
chip(1178, 244, 186, "任务内迭代改进", "#F0F7F4", "#18776C", 18)

group("prepare")
for y in [308,492,676]:
    rect(88,y,226,130,"#FFFFFF","#DCE5EA",14, 'class="module-outline"')
text(108,342,"研究需求",25,"#243D50",600)
text(108,378,"自然语言描述问题",19,"#657C8B")
text(108,408,"目标 · 范围 · 关注点",19,"#657C8B")
text(108,526,"研究简报",25,"#243D50",600)
text(108,562,"明确研究范围",19,"#657C8B")
text(108,592,"整理需要回答的问题",19,"#657C8B")
text(108,710,"报告初稿",25,"#243D50",600)
text(108,746,"建立初始内容框架",19,"#657C8B")
text(108,776,"作为后续修订起点",19,"#657C8B")
end()
path("M201 438 V484")
path("M201 622 V668")
path("M314 741 H347 Q356 741 356 732 V361 Q356 352 365 352 H406")
text(201,845,"先建框架，再用证据完善",17,"#6C8391",extra='text-anchor="middle"')

group("supervisor")
rect(414,308,950,88,"url(#navy-wash)",radius=16,extra='class="module-outline"')
rect(438,330,40,40,"#31586C",radius=11)
text(458,357,"研",22,"#E0F7EE",600,'text-anchor="middle"')
text(494,344,"研究主管",27,"#FFFFFF",600)
text(494,375,"统筹研究方向与下一步行动",18,"#BAD0DB")
for x,label in [(843,"拆解主题"),(1013,"调度研究"),(1183,"判断完成")]:
    text(x,360,label,22,"#E5F1F5",500)
end()
path("M624 396 V440")
path("M1139 396 V440")

group("research")
rect(414,448,420,264,"#F4F8FB","#DCE7EE",16, 'class="module-outline"')
text(438,485,"多主题研究",26,"#27465B",600)
text(810,485,"按需并行",17,"#678496",extra='text-anchor="end"')
for x,label in [(438,"研究主题 A"),(566,"研究主题 B"),(694,"研究主题 …")]:
    rect(x,505,116,43,"#E5EEF5",radius=9)
    text(x+58,533,label,17,"#395B72",500,'text-anchor="middle"')
path("M624 548 V570",arrow=True)
rect(438,578,372,48,"#FFFFFF","#DCE7EE",9)
text(624,609,"联网检索 → 去重 → 网页摘要",20,"#436274",500,'text-anchor="middle"')
path("M624 626 V648")
text(624,683,"压缩研究笔记 · 保留来源链接",20,"#436274",500,'text-anchor="middle"')
end()
path("M834 490 H906")
text(851,478,"发现",16,"#718694",extra='text-anchor="middle"')

group("refine")
rect(914,448,450,84,"url(#teal-wash)","#D2E9DF",14,'class="module-outline"')
text(938,483,"草稿修订",26,"#256A5E",600)
text(938,513,"结合新证据，补齐缺口、修正内容",19,"#537C73")
end()
path("M1015 532 V570")

group("evaluate")
rect(914,578,202,134,"#F0F7F3","#D5E7DC",14,'class="module-outline"')
text(936,614,"质量评估",24,"#2D6657",600)
text(936,650,"全面性 · 准确性",18,"#547D6E")
text(936,680,"连贯性 · 改进建议",18,"#547D6E")
end()
path("M1116 645 H1140")

group("redteam")
rect(1148,578,216,134,"#FCF4E9","#EEDFCC",14,'class="module-outline"')
text(1170,614,"红队审阅",24,"#986126",600)
text(1170,650,"检查遗漏与偏题",18,"#95744D")
text(1170,680,"质疑矛盾与逻辑缺陷",18,"#95744D")
end()

# Feedback is task-local, and is triggered after revision.
path("M1256 712 V754 Q1256 772 1238 772 H891 Q873 772 873 754 V404", "#168A80", dash=True, width=2.6)
text(1058,812,"评分与质疑回流，驱动下一轮研究",20,"#167A71",500,'text-anchor="middle"')
text(438,761,"持续获取信息",19,"#526E80",500)
text(438,794,"持续完善报告",19,"#526E80",500)
text(889,848,"研究完成或达到迭代上限后，进入最终报告生成",17,"#7A8F9C",extra='text-anchor="middle"')

path("M1364 352 H1456")
text(1414,337,"结束研究",16,"#6C8391",extra='text-anchor="middle"')
group("report")
rect(1464,308,248,478,"url(#navy-wash)",radius=17,extra='class="module-outline"')
text(1488,395,"最终研究报告",27,"#FFFFFF",600)
text(1488,430,"综合研究发现与当前草稿",17,"#C0D2DE")
rect(1488,456,200,106,"#26495F",radius=10)
text(1507,485,"研究结论",19,"#E8F1F6",500)
rect(1507,502,137,5,"#86A8B9",radius=2)
rect(1507,517,158,5,"#638CA0",radius=2)
rect(1507,532,100,5,"#638CA0",radius=2)
for y,label in [(604,"结构化章节"),(650,"多维分析与结论"),(696,"来源引用与参考资料")]:
    add(f'<circle cx="1495" cy="{y-7}" r="4" fill="#79CAB4"/>')
    text(1511,y,label,19,"#DFEBF0")
text(1588,752,"与用户输入语言一致",17,"#AAC4D3",extra='text-anchor="middle"')
end()
text(1588,829,"Markdown · 可保存与分享",17,"#567588",extra='text-anchor="middle"')

text(64,910,"贯穿研究全流程的能力支撑",18,"#5D7687",500)
group("foundation")
rect(64,926,1672,116,"#FFFFFF","#DAE5EB",18, 'class="module-outline"')
for x,title,desc in [(92,"模型能力","按角色配置，支撑研究与写作"),(508,"联网搜索","获取外部网页与来源信息"),(924,"研究上下文","串联简报、笔记、草稿与反馈"),(1340,"过程管理","保留评分记录、日志与迭代预算")]:
    rect(x,950,5,53,"#A8C7CE",radius=2)
    text(x+22,973,title,23,"#2A495D",600)
    text(x+22,1009,desc,18,"#68808F")
end()
path("M65 1080 H108",width=2)
text(121,1086,"研究流程",16,"#738997")
path("M247 1080 H294", "#168A80",dash=True,width=2)
text(307,1086,"改进反馈",16,"#738997")
text(1736,1086,"基于当前项目实现 · 功能介绍视图 · 2026.10",16,"#8296A2",extra='text-anchor="end"')
add('</svg>')
svg = '\n'.join(parts)
(OUT / "deep-research-architecture.svg").write_text(svg, encoding="utf-8")

details = {
    "overview": {"title":"以研究为主线，以反馈推动改进", "body":"从自然语言需求出发，先建立研究简报与报告初稿，再围绕信息缺口开展多主题研究。研究主管结合证据、质量评分和红队意见持续完善草稿，最后生成带来源引用的研究报告。", "tags":["需求驱动", "多智能体协作", "任务内迭代", "来源引用"]},
    "prepare": {"title":"需求准备：把问题变成研究任务", "body":"将用户消息整理为研究简报，明确需要覆盖的主题和范围，并生成初始报告草稿。初稿用于提供后续修订的起点，内容会在研究过程中逐步补充与修正。", "tags":["自然语言输入", "研究简报", "报告初稿"], "source":"agents/draft_agent.py · write_research_brief / write_draft_report"},
    "supervisor": {"title":"研究主管：决定下一步研究什么", "body":"围绕简报与当前草稿识别信息缺口，委派子主题研究、汇总研究发现，并决定是否修订草稿或结束研究。评分与红队意见会回到主管的上下文，用于指导后续行动。", "tags":["任务拆解", "按需调度", "研究完成判断"], "source":"agents/supervisor.py · supervisor / supervisor_tools"},
    "research": {"title":"多主题研究：从网页信息中提炼发现", "body":"每个子研究智能体围绕独立主题反复检索和分析。搜索结果按 URL 去重，网页正文生成摘要，研究结束后压缩为带来源信息的研究笔记。主管可以同时委派多个子主题。", "tags":["独立主题上下文", "联网搜索", "去重与摘要", "笔记压缩"], "source":"agents/research_agent.py · tools/tool.py"},
    "refine": {"title":"草稿修订：用新证据逐步完善报告", "body":"写作角色结合研究简报、已有研究发现和当前草稿生成更新版本。项目中的“降噪”指通过补充证据、修订内容来减少报告的不完整与不精确之处。", "tags":["证据补充", "内容修订", "渐进完善"], "source":"tools/tool.py · refine_draft_report"},
    "evaluate": {"title":"质量评估：让改进有明确的反馈", "body":"评估角色从全面性、准确性、连贯性三个维度对修订稿打分，返回原因与建议，记录质量历史；低分会触发后续修复提醒。这里的“自进化”体现为当前任务中的报告改进。", "tags":["多维评分", "改进建议", "质量历史"], "source":"agents/evaluator_agent.py · agents/supervisor.py"},
    "redteam": {"title":"红队审阅：从反对视角寻找缺口", "body":"修订稿经过质量评估后进入红队审阅。红队检查覆盖不足、偏题、矛盾和逻辑缺陷，提出关键且可操作的质疑；这些意见注入主管上下文，促使进一步研究与修订。", "tags":["对抗审阅", "逻辑检查", "反馈回流"], "source":"agents/red_team_agent.py · prompts/red_team.py"},
    "report": {"title":"报告交付：综合证据，形成完整叙述", "body":"研究阶段结束后，独立的写作步骤结合研究简报、汇总发现与当前草稿生成最终报告。输出使用 Markdown，提示词要求结构化章节、分析结论、来源引用及参考资料，并与用户输入语言一致。", "tags":["最终综合", "结构化报告", "来源引用", "Markdown"], "source":"agent_builder.py · final_report_generation / prompts/final_report.py"},
    "foundation": {"title":"能力支撑：让各研究角色协同工作", "body":"模型按角色统一配置，搜索层连接外部网页，任务状态保留简报、研究笔记、草稿、评分和审阅意见。日志与迭代预算支持过程追踪；Notebook 示例提供内存中的会话检查点。", "tags":["角色模型配置", "搜索能力", "任务状态", "日志与迭代管理"], "source":"llm.py · tools/search_factory.py · states/ · logging.py · run.ipynb"}
}

template = '''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="Deep Research Agent 项目功能架构：多智能体研究、自进化评估与红队反馈驱动的报告生成。">
<title>Deep Research Agent · 项目架构</title>
<style>
:root{color-scheme:light;--ink:#18364a;--muted:#657d8d;--teal:#147d73;--line:#dce6eb}
*{box-sizing:border-box}body{margin:0;background:#f2f5f7;color:var(--ink);font-family:"Microsoft YaHei","PingFang SC",sans-serif}button,a{-webkit-tap-highlight-color:transparent}button{font:inherit;cursor:pointer}button:focus-visible,a:focus-visible,[data-module]:focus-visible{outline:3px solid #268d81;outline-offset:4px}header{min-height:72px;padding:16px 32px;background:#fff;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;gap:16px}.brand{display:flex;align-items:center;gap:12px;font-size:17px;font-weight:700}.brand-mark{display:grid;place-items:center;width:32px;height:32px;background:#193d53;border-radius:9px;color:#b8ead8;font-size:19px}.brand small{font-weight:400;font-size:12px;letter-spacing:2px;color:var(--muted);margin-left:10px}.actions{display:flex;gap:8px;flex-wrap:wrap}.button{border:1px solid #d6e2e7;background:#fff;color:#294b5e;border-radius:8px;min-height:36px;padding:7px 14px;font-size:13px}.button:hover{background:#eff5f6}.button.primary{background:#183e52;color:#fff;border-color:#183e52}.button.primary:hover{background:#24536a}main{max-width:1920px;margin:auto;padding:16px 24px 32px}.viewer{overflow:hidden;border:1px solid var(--line);border-radius:14px;background:#f9fbfc;box-shadow:0 10px 36px #1c3e5008}.toolbar{padding:10px 16px;display:flex;align-items:center;justify-content:space-between;gap:14px;border-bottom:1px solid #e5edf1;background:#fff}.toolbar-note{font-size:12px;color:var(--muted)}.zoom-controls{display:flex;align-items:center;gap:6px;flex-shrink:0}.zoom-controls button{padding:4px 10px;min-height:29px;font-size:12px}.zoom-controls output{min-width:46px;text-align:center;font-size:12px;font-variant-numeric:tabular-nums;color:#5c7685}#viewport{height:calc(100svh - 158px);min-height:430px;overflow:auto;overscroll-behavior:contain;scrollbar-color:#b9cbd4 #edf2f5}#stage{width:max-content;min-width:100%;min-height:100%;display:flex;align-items:center;justify-content:center}#stage>svg{display:block;flex-shrink:0;height:auto}#stage [data-module]{cursor:pointer}#stage [data-module]:hover .module-outline{stroke:#53a998;stroke-width:2.5}#stage [data-module].selected .module-outline{stroke:#138b79;stroke-width:3.2}#viewer:fullscreen{border:none;border-radius:0}#viewer:fullscreen #viewport{height:calc(100svh - 52px)}.detail-area{margin-top:20px;background:#fff;border:1px solid var(--line);border-radius:14px;padding:24px 28px}.module-nav{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:22px}.module-nav button{border:1px solid #dce6eb;border-radius:30px;background:#fff;padding:8px 14px;color:#607c8c;font-size:13px;min-height:36px}.module-nav button[aria-pressed="true"]{color:#fff;background:#224d60;border-color:#224d60}.detail-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(230px,320px);gap:40px}h1{font-size:21px;font-weight:600;margin:0 0 13px}#detail-body{font-size:14px;line-height:1.9;max-width:920px;margin:0;color:#5d7484}.tags{display:flex;gap:8px;flex-wrap:wrap;margin-top:18px}.tag{background:#edf5f2;color:#478070;padding:5px 10px;border-radius:5px;font-size:12px}.talk-track{border-left:2px solid #c9ddd9;padding:2px 0 0 22px;color:#5a7584;font-size:13px;line-height:1.85}.talk-track strong{display:block;color:#345c6c;margin-bottom:7px;font-weight:600}.talk-track p{margin:0}details{margin-top:24px;border-top:1px solid #e5ecef;padding-top:16px;color:#748995;font-size:12px;line-height:1.9}summary{cursor:pointer;width:fit-content;color:#5d7988}details p{margin:10px 0 0}#detail-source{overflow-wrap:anywhere}footer{display:flex;justify-content:space-between;gap:12px;padding:20px 4px 0;font-size:11px;color:#8396a1;flex-wrap:wrap}.mobile-note{display:none}#notice{color:#346d61;font-size:12px;min-height:16px;margin-top:8px} @media(max-width:760px){header{padding:12px 16px;flex-wrap:wrap}.brand small{display:none}.brand{font-size:15px}.button{min-height:40px}main{padding:12px 10px 24px}.toolbar{padding:10px;flex-wrap:wrap}.toolbar-note{display:none}.mobile-note{display:inline;font-size:11px;color:#7a8e99}.zoom-controls{gap:3px}.zoom-controls button{min-height:36px;padding:5px 8px}#viewport{height:58svh;min-height:400px}.detail-area{padding:20px 17px}.detail-grid{grid-template-columns:1fr;gap:23px}.module-nav{gap:6px}.module-nav button{font-size:12px;padding:7px 10px;min-height:38px}h1{font-size:18px}.talk-track{padding-left:16px}footer{line-height:1.8}}@media print{@page{size:A3 landscape;margin:8mm}body,main{background:white;margin:0;padding:0}header,.toolbar,.detail-area,footer{display:none}.viewer{border:0;box-shadow:none}#viewport{height:auto!important;min-height:0;overflow:visible}#stage{width:100%;display:block;min-height:0}#stage>svg{width:100%!important;height:auto!important}}
</style>
</head>
<body>
<header><div class="brand"><span class="brand-mark" aria-hidden="true">研</span>Deep Research Agent <small>项目功能架构</small></div><div class="actions"><button type="button" class="button" id="fullscreen">全屏展示</button><button type="button" class="button primary" id="download">下载 SVG</button></div></header>
<main>
<section class="viewer" id="viewer" aria-label="项目架构图">
<div class="toolbar"><span class="toolbar-note">点击图中模块，查看功能介绍与讲解要点</span><span class="mobile-note">可横向滚动查看全图</span><div class="zoom-controls"><button type="button" class="button" id="zoom-out" aria-label="缩小架构图">−</button><output id="zoom-level" aria-live="polite">100%</output><button type="button" class="button" id="zoom-in" aria-label="放大架构图">＋</button><button type="button" class="button" id="fit">适应窗口</button><button type="button" class="button" id="actual">原始尺寸</button></div></div>
<div id="viewport" tabindex="0" aria-label="架构图查看区域，可滚动"><div id="stage">__SVG__</div></div>
</section>
<section class="detail-area" aria-label="模块功能介绍">
<nav class="module-nav" aria-label="选择架构模块">__NAV__</nav>
<div class="detail-grid"><div aria-live="polite"><h1 id="detail-title"></h1><p id="detail-body"></p><div class="tags" id="detail-tags"></div></div><aside class="talk-track"><strong>一分钟介绍本项目</strong><p>输入一个研究问题，系统组织多个研究角色收集信息；再用质量评分和红队质疑推动报告改进，最终交付一份结构清晰、带来源引用的研究报告。</p></aside></div>
<details><summary>查看实现依据与范围说明</summary><p id="detail-source"></p><p>依据当前目录中的主流程、智能体、搜索工具、状态定义和提示词整理；本页为功能架构展示，不连接模型或搜索服务。</p><p>“自进化”表示当前任务中的报告迭代；“降噪”表示检索、摘要与修订过程中的信息精炼。质量评分和红队审阅由草稿修订触发，不是每次搜索后都必经的步骤，也不是最终报告的强制验收门槛。</p><p>模型配置目前走 OpenAI 兼容接口，默认检索后端为 Tavily；自定义搜索文件仅为扩展示例。主入口是 Notebook，图中未将独立产品界面、私有知识库或跨任务学习列为已有能力。</p></details>
<div id="notice" role="status"></div>
</section>
<footer><span>Deep Research Agent · 项目介绍资料</span><span>SVG 矢量图与本页面内容一致 · 单文件离线可用 · 2026.10</span></footer>
</main>
<script>
'use strict';
const moduleDetails=__DETAILS__;
const svg=document.querySelector('#stage>svg');
const originalSvg=new XMLSerializer().serializeToString(svg);
const viewport=document.getElementById('viewport');
let zoom=1,fitMode=true;
function setZoom(value){zoom=Math.max(.15,Math.min(2.5,value));svg.style.width=(1800*zoom)+'px';svg.style.height=(1120*zoom)+'px';document.getElementById('zoom-level').value=Math.round(zoom*100)+'%';}
function fit(){fitMode=true;setZoom(Math.min((viewport.clientWidth-12)/1800,(viewport.clientHeight-12)/1120));viewport.scrollTop=0;viewport.scrollLeft=0;}
function selectModule(key){const item=moduleDetails[key];if(!item)return;document.getElementById('detail-title').textContent=item.title;document.getElementById('detail-body').textContent=item.body;document.getElementById('detail-source').textContent='对应代码：'+(item.source||'agent_builder.py · agents/ · tools/ · states/（均位于 deep_research/ 下，另见 run.ipynb）');const tags=document.getElementById('detail-tags');tags.replaceChildren(...item.tags.map(t=>{const el=document.createElement('span');el.className='tag';el.textContent=t;return el;}));document.querySelectorAll('[data-select]').forEach(el=>el.setAttribute('aria-pressed',String(el.dataset.select===key)));svg.querySelectorAll('[data-module]').forEach(el=>{el.classList.toggle('selected',el.dataset.module===key);el.setAttribute('aria-pressed',String(el.dataset.module===key));});}
document.querySelectorAll('[data-select]').forEach(el=>el.addEventListener('click',()=>selectModule(el.dataset.select)));
svg.querySelectorAll('[data-module]').forEach(el=>{el.setAttribute('tabindex','0');el.setAttribute('role','button');el.setAttribute('aria-label',moduleDetails[el.dataset.module].title);el.addEventListener('click',()=>selectModule(el.dataset.module));el.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();selectModule(el.dataset.module);}});});
document.getElementById('zoom-in').addEventListener('click',()=>{fitMode=false;setZoom(zoom*1.2);});
document.getElementById('zoom-out').addEventListener('click',()=>{fitMode=false;setZoom(zoom/1.2);});
document.getElementById('fit').addEventListener('click',fit);
document.getElementById('actual').addEventListener('click',()=>{fitMode=false;setZoom(1);});
const notice=document.getElementById('notice');
document.getElementById('download').addEventListener('click',()=>{const blob=new Blob(['<?xml version="1.0" encoding="UTF-8"?>\\n'+originalSvg],{type:'image/svg+xml;charset=utf-8'});const url=URL.createObjectURL(blob);const link=document.createElement('a');link.href=url;link.download='deep-research-architecture.svg';document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1500);notice.textContent='已生成 SVG 下载文件，可用于文档、PPT 或印刷。';});
document.getElementById('fullscreen').addEventListener('click',async()=>{try{if(document.fullscreenElement){await document.exitFullscreen();}else{await document.getElementById('viewer').requestFullscreen();}}catch{notice.textContent='当前浏览器不支持页面全屏，可使用浏览器自带全屏功能。';}});
document.addEventListener('fullscreenchange',()=>{document.getElementById('fullscreen').textContent=document.fullscreenElement?'退出全屏':'全屏展示';if(fitMode)fit();});
new ResizeObserver(()=>{if(fitMode)fit();}).observe(viewport);
selectModule('overview');
if(window.innerWidth<=760){fitMode=false;setZoom(.65);}else{fit();}
</script>
</body>
</html>
'''
labels={"overview":"整体概览","prepare":"需求准备","supervisor":"研究主管","research":"多主题研究","refine":"草稿修订","evaluate":"质量评估","redteam":"红队审阅","report":"报告交付","foundation":"能力支撑"}
nav=''.join(f'<button type="button" data-select="{key}" aria-pressed="false">{label}</button>' for key,label in labels.items())
page=template.replace('__SVG__',svg).replace('__DETAILS__',json.dumps(details,ensure_ascii=False)).replace('__NAV__',nav)
(OUT/'index.html').write_text(page,encoding='utf-8')
print('Created deep-research-architecture.svg and index.html')

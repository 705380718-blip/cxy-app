from __future__ import annotations

import sys
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor


BLUE = RGBColor(20, 105, 78)
DARK = RGBColor(24, 35, 30)
MUTED = RGBColor(96, 108, 102)
LIGHT = "E8F2ED"
LINE = "D7E0DB"


def set_font(run, size=11, bold=False, color=DARK, name="PingFang SC"):
    run.font.name = name
    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), name)
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color


def set_cell_shading(cell, fill):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def set_cell_margins(cell, top=80, start=120, bottom=80, end=120):
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    margins = tc_pr.first_child_found_in("w:tcMar")
    if margins is None:
        margins = OxmlElement("w:tcMar")
        tc_pr.append(margins)
    for edge, value in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        node = margins.find(qn(f"w:{edge}"))
        if node is None:
            node = OxmlElement(f"w:{edge}")
            margins.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def set_table_widths(table, widths):
    table.autofit = False
    for row in table.rows:
        for index, width in enumerate(widths):
            row.cells[index].width = Inches(width)
            set_cell_margins(row.cells[index])
            row.cells[index].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER


def add_para(doc, text="", size=11, bold=False, color=DARK, after=6, align=None, keep=False):
    paragraph = doc.add_paragraph()
    paragraph.paragraph_format.space_before = Pt(0)
    paragraph.paragraph_format.space_after = Pt(after)
    paragraph.paragraph_format.line_spacing = 1.25
    paragraph.paragraph_format.keep_with_next = keep
    if align is not None:
        paragraph.alignment = align
    set_font(paragraph.add_run(text), size=size, bold=bold, color=color)
    return paragraph


def add_bullet(doc, text, style="List Bullet"):
    paragraph = doc.add_paragraph(style=style)
    paragraph.paragraph_format.left_indent = Inches(0.375)
    paragraph.paragraph_format.first_line_indent = Inches(-0.188)
    paragraph.paragraph_format.space_after = Pt(4)
    paragraph.paragraph_format.line_spacing = 1.25
    set_font(paragraph.add_run(text))
    return paragraph


def add_step(doc, number, title, text):
    paragraph = doc.add_paragraph()
    paragraph.paragraph_format.space_before = Pt(5)
    paragraph.paragraph_format.space_after = Pt(4)
    paragraph.paragraph_format.keep_with_next = True
    set_font(paragraph.add_run(f"{number}. {title}"), size=12, bold=True, color=BLUE)
    add_para(doc, text, after=7)


def add_note(doc, title, text, fill=LIGHT):
    table = doc.add_table(rows=1, cols=1)
    table.autofit = False
    cell = table.cell(0, 0)
    cell.width = Inches(6.5)
    set_cell_margins(cell, top=120, start=160, bottom=120, end=160)
    set_cell_shading(cell, fill)
    p = cell.paragraphs[0]
    p.paragraph_format.space_after = Pt(3)
    set_font(p.add_run(title), size=11, bold=True, color=BLUE)
    p2 = cell.add_paragraph()
    p2.paragraph_format.space_after = Pt(0)
    p2.paragraph_format.line_spacing = 1.2
    set_font(p2.add_run(text), size=10.5)
    doc.add_paragraph().paragraph_format.space_after = Pt(1)


def configure_styles(doc):
    normal = doc.styles["Normal"]
    normal.font.name = "PingFang SC"
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "PingFang SC")
    normal.font.size = Pt(11)
    normal.font.color.rgb = DARK
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.25
    for name, size, before, after in (
        ("Heading 1", 16, 18, 10),
        ("Heading 2", 13, 14, 7),
        ("Heading 3", 12, 10, 5),
    ):
        style = doc.styles[name]
        style.font.name = "PingFang SC"
        style._element.rPr.rFonts.set(qn("w:eastAsia"), "PingFang SC")
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = BLUE
        style.paragraph_format.space_before = Pt(before)
        style.paragraph_format.space_after = Pt(after)
        style.paragraph_format.keep_with_next = True


def build(output: Path):
    doc = Document()
    section = doc.sections[0]
    section.top_margin = Inches(0.82)
    section.bottom_margin = Inches(0.72)
    section.left_margin = Inches(1)
    section.right_margin = Inches(1)
    section.header_distance = Inches(0.42)
    section.footer_distance = Inches(0.42)
    configure_styles(doc)

    header = section.header.paragraphs[0]
    header.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    set_font(header.add_run("群聊问题整理 · Mac 本机版"), size=9, color=MUTED)
    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_font(footer.add_run("本机离线运行 · 不上传聊天数据 · 版本 0.1.0"), size=8.5, color=MUTED)

    add_para(doc, "MAC 本机工具", size=10, bold=True, color=BLUE, after=22, align=WD_ALIGN_PARAGRAPH.CENTER)
    add_para(doc, "群聊问题整理", size=28, bold=True, color=DARK, after=6, align=WD_ALIGN_PARAGRAPH.CENTER)
    add_para(doc, "安装、首次配置与日常使用手册", size=14, color=MUTED, after=22, align=WD_ALIGN_PARAGRAPH.CENTER)
    add_note(
        doc,
        "先看结论",
        "软件只在当前 Mac 的 127.0.0.1 上运行，不提供云同步，也不会把聊天、规则或报告上传到其他服务器。每台 Mac 的微信数据库密钥不同，第一次使用必须在本机单独准备。",
    )

    meta = doc.add_table(rows=4, cols=2)
    meta.style = "Table Grid"
    set_table_widths(meta, [1.45, 5.05])
    for row, (label, value) in zip(meta.rows, [
        ("适用系统", "Apple Silicon Mac（M1/M2/M3/M4），macOS 13 或更高"),
        ("适配微信", "已实测微信 4.1.11–4.1.12；升级后需重新确认兼容性"),
        ("本地地址", "http://127.0.0.1:8791/"),
        ("默认保留", "首次导入最近 7 天；采集记录默认保存 7 天，可在规则页修改"),
    ]):
        set_cell_shading(row.cells[0], LIGHT)
        p1, p2 = row.cells[0].paragraphs[0], row.cells[1].paragraphs[0]
        set_font(p1.add_run(label), size=10, bold=True, color=BLUE)
        set_font(p2.add_run(value), size=10)

    doc.add_heading("1. 软件包里有什么", level=1)
    add_bullet(doc, "1-首次密钥准备.command：新 Mac 第一次使用，或微信升级/换号后密钥失效时运行。")
    add_bullet(doc, "2-启动服务.command：启动本机后台；随后在浏览器输入固定地址。")
    add_bullet(doc, "3-停止服务.command：退出本机后台服务。")
    add_bullet(doc, "4-清除本工具数据.command：清除采集记录、问题、报告、规则和状态，不删除微信原始聊天。")
    add_bullet(doc, "程序文件：内置运行环境和程序代码；不要改名、移动其中内容或单独发送。")
    add_bullet(doc, "使用手册.docx：当前文档。")

    doc.add_heading("2. 第一次使用", level=1)
    add_step(doc, 1, "安装并登录官方微信", "将官方微信安装到“应用程序”目录，使用需要整理群聊的账号正常登录。无需准备专用微信号。")
    add_step(doc, 2, "解压并保留完整文件夹", "将整个“群聊问题整理-Mac-命令版”文件夹解压到桌面、应用程序或文稿目录。不要放入 iCloud、网盘或多人共享目录，也不要把 command 与“程序文件”拆开。")
    add_step(doc, 3, "准备本机密钥", "双击“1-首次密钥准备.command”，阅读安全提示后继续。它会在桌面制作一个临时签名的微信副本，并运行约 3 分钟。在倒计时期间，请在这个临时微信副本中确认登录，依次打开“收藏”和“朋友圈”，并在朋友圈滚动一次。")
    add_note(doc, "密钥准备的安全边界", "该步骤使用 Frida 读取临时签名微信副本运行时的密钥，只用于当前用户自己的本机数据库。密钥写入 ~/.config/wechat-keys.json，权限仅限当前用户；软件包内不含发布者密钥。此方式不是微信官方接口，可能受微信版本变化或用户协议影响。", "FFF4DE")
    add_step(doc, 4, "确认密钥成功并启动", "终端出现“Done. Keys saved”和“已验证”后才算准备成功；倒计时一直为 0 且最后提示无法解密时，需要按上一步重试。随后双击“2-启动服务.command”。")
    add_step(doc, 5, "打开固定地址", "看到“服务已启动”后，本终端窗口可以关闭。在 Safari、Chrome 或 Edge 地址栏手工输入 http://127.0.0.1:8791/。macOS 若询问终端是否允许访问微信容器、桌面或文稿，请按实际用途允许。")
    add_step(doc, 6, "配置提取规则", "进入“提取规则”，逐行填写精确群名、自己的微信昵称、可选的 @指定人员和关键词；确认保存天数后点击“保存规则”。")
    add_step(doc, 7, "启动监听", "回到首页点击“启动监听”。首次启用每个群会按保存天数导入本机现有历史；看到“监听并解码中”表示链路已工作。")

    doc.add_heading("3. 日常使用", level=1)
    daily = doc.add_table(rows=1, cols=3)
    daily.style = "Table Grid"
    headers = ("区域", "用途", "建议操作")
    for i, label in enumerate(headers):
        set_cell_shading(daily.rows[0].cells[i], LIGHT)
        set_font(daily.rows[0].cells[i].paragraphs[0].add_run(label), size=10, bold=True, color=BLUE)
    rows = [
        ("采集记录", "查看本机已解析消息", "使用搜索、分页；图片以占位文案显示"),
        ("待复核问题", "确认是否纳入报告", "数据多时使用“全选本页”和批量确认/忽略"),
        ("提取规则", "调整群、@人员、关键词和保存天数", "群名必须与微信显示名完全一致"),
        ("汇总报告", "按开始/结束日期生成 Markdown", "复制到文档或飞书；同一区间重复生成会更新"),
        ("刷新", "重新读取页面数据", "看到“刷新中…”和完成提示即为有效"),
    ]
    for values in rows:
        cells = daily.add_row().cells
        for i, value in enumerate(values):
            set_font(cells[i].paragraphs[0].add_run(value), size=9.5, bold=i == 0)
    set_table_widths(daily, [1.2, 2.15, 3.15])

    doc.add_heading("4. 离线、隐私与数据位置", level=1)
    add_bullet(doc, "日常查看、复核和报告生成可离线使用；断网后微信本身不能接收新消息。")
    add_bullet(doc, "后台只绑定 127.0.0.1:8791，局域网其他设备不能访问。")
    add_bullet(doc, "本工具没有云同步、遥测或外部上传接口；浏览器只请求本机地址。")
    add_bullet(doc, "工具数据位于 ~/Library/Application Support/群聊问题整理/data/mac-listener.db；运行日志位于同目录的 logs/app.log；解密快照位于 ~/Library/Application Support/wechat-group-organizer/private/live。")
    add_bullet(doc, "密钥位于 ~/.config/wechat-keys.json。不要通过微信、邮件、网盘或工单传递该文件。")

    doc.add_heading("5. 清除与卸载", level=1)
    add_step(doc, 1, "停止服务", "在首页点击“停止监听”，然后双击“3-停止服务.command”。")
    add_step(doc, 2, "清除业务数据", "双击“4-清除本工具数据.command”。它只删除 ~/Library/Application Support/群聊问题整理/data 内的本地数据库，不触碰微信原始聊天记录。")
    add_step(doc, 3, "完全卸载（可选）", "删除软件文件夹；如需同时移除密钥与解密快照，再手动删除 ~/.config/wechat-keys.json 和 ~/Library/Application Support/wechat-group-organizer。此操作不可恢复。")

    doc.add_heading("6. 常见问题", level=1)
    faq = [
        ("首页显示无法解析", "先确认官方微信已运行、微信版本在已验证范围内，并重新执行首次密钥准备。"),
        ("双击启动命令没有打开网页", "命令版不会自动打开浏览器。终端提示服务已启动后，请手工访问 http://127.0.0.1:8791/；失败时查看 ~/Library/Application Support/群聊问题整理/logs/app.log。"),
        ("密钥倒计时一直为 0", "在临时签名微信副本中确认登录，倒计时期间打开收藏、朋友圈并滚动。只有最后通过数据库解密验证才算成功。"),
        ("找不到指定群", "群名必须精确一致；同名群无法唯一匹配时，请先在微信中改成唯一群名。"),
        ("没有历史消息", "只读取当前 Mac 微信本地库仍保存的消息；本机已删除、未同步或超过设置窗口的消息无法补拉。"),
        ("图片为什么看不到", "当前只识别图片消息，不下载或解密媒体文件，因此统一显示“此内容为图片，不支持展示”。"),
        ("微信升级后失效", "先停止监听，重新执行首次密钥准备；若版本超出页面提示的验证范围，不要强制绕过门禁。"),
    ]
    for question, answer in faq:
        add_para(doc, question, size=11, bold=True, color=BLUE, after=2, keep=True)
        add_para(doc, answer, size=10, after=4)

    doc.add_heading("7. 使用前检查清单", level=1)
    for text in (
        "[ ] 仅处理本人有权访问、且群成员已知情的数据",
        "[ ] 官方微信已安装、登录并保持运行；首次密钥准备已完成",
        "[ ] 已填写精确群名和本人昵称",
        "[ ] 保存天数符合实际隐私与合规要求",
        "[ ] 首页状态为“监听并解码中”，解码错误为 0",
    ):
        add_para(doc, text, size=10, after=2)

    warning = doc.add_table(rows=1, cols=1)
    warning.autofit = False
    cell = warning.cell(0, 0)
    cell.width = Inches(6.5)
    set_cell_margins(cell, top=100, start=150, bottom=100, end=150)
    set_cell_shading(cell, "FCE8E6")
    paragraph = cell.paragraphs[0]
    paragraph.paragraph_format.space_after = Pt(2)
    set_font(paragraph.add_run("重要提醒："), size=10.5, bold=True, color=BLUE)
    set_font(paragraph.add_run("这是个人微信本地数据库的非官方兼容方案，不等同于微信官方授权能力。用于交付他人前，应确保数据主体知情、符合组织制度与适用法律，并在微信升级后重新做兼容性验证。"), size=9.8)

    output.parent.mkdir(parents=True, exist_ok=True)
    doc.save(output)


if __name__ == "__main__":
    build(Path(sys.argv[1]))

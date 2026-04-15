#!/usr/bin/env python
"""
read_pdf.py — 将 PDF 转为 Markdown 文本，双引擎策略：
  1. 首选：MarkItDown（快，无需 Java，适合大多数文字型 PDF）
  2. Fallback：opendataloader-pdf（需要 Java 11+，质量更高，适合复杂排版/表格/公式）

Fallback 触发条件（任一满足）：
  - MarkItDown 抛出异常
  - MarkItDown 输出为空或长度 < MIN_CONTENT_LENGTH（默认 200 字符）
  - 传入 --force-odl 标志强制使用 opendataloader-pdf

插件支持（可选）：
  - 通过 config.json 的 markitdown_plugins 节启用
  - markitdown-ocr：对 PDF 中嵌入的图片做 OCR（需要 openai 包和 OPENAI_API_KEY）
  - 启用后自动传入 enable_plugins=True 和 llm_client

安装建议（仅 PDF/Word/Excel，减少无关依赖加快 import）：
  pip install 'markitdown[pdf,docx,xlsx]'   # 精简安装
  pip install 'markitdown[all]'              # 全量安装（含音频、图片等转换器）
  pip install markitdown-ocr openai          # OCR 插件（可选）

用法：
  python read_pdf.py <pdf_path>              # 自动选择引擎
  python read_pdf.py <pdf_path> --force-odl  # 强制使用 opendataloader-pdf

⚠️ Gotcha（opendataloader-pdf）：
  - 需要 Java 11+，运行前确认 `java -version`
  - 每次调用都会启动一个 JVM 进程，比 MarkItDown 慢 5-10 秒
  - 输出写入临时目录，脚本读取后清理
  - Windows 路径需要正斜杠或转义反斜杠
"""
import sys
import os
import json
import warnings
import tempfile
import shutil

# pydub 在被 MarkItDown 间接 import 时，若找不到 ffmpeg 会打印 RuntimeWarning。
# 该警告与 PDF 转换完全无关，在 import 前全局屏蔽。
warnings.filterwarnings(
    "ignore",
    message="Couldn't find ffmpeg or avconv",
    category=RuntimeWarning,
)

MIN_CONTENT_LENGTH = 200  # 少于此字符数视为提取失败，触发 fallback

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
CONFIG_PATH = os.path.join(SKILL_DIR, "config.json")


def _load_plugin_config() -> dict:
    """从 config.json 读取 markitdown_plugins 节，不存在时返回空 dict（插件关闭）。"""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg.get("markitdown_plugins", {})
    except Exception:
        return {}


def _is_useful(text: str) -> bool:
    """判断提取结果是否有实质内容"""
    if not text:
        return False
    stripped = text.strip()
    return len(stripped) >= MIN_CONTENT_LENGTH


def read_with_markitdown(pdf_path: str) -> str | None:
    """
    使用 MarkItDown 提取，失败返回 None。

    插件行为由 config.json markitdown_plugins 节控制：
      { "enabled": true, "ocr": { "enabled": true, "llm_model": "gpt-4o" } }

    OCR 插件需要 OPENAI_API_KEY 环境变量和 markitdown-ocr + openai 包。
    插件默认关闭，不影响无 OpenAI key 的环境。
    """
    try:
        from markitdown import MarkItDown
    except ImportError:
        print(
            "[read_pdf] MarkItDown 未安装，跳过。\n"
            "  精简安装（推荐）: pip install 'markitdown[pdf,docx,xlsx]'\n"
            "  全量安装:         pip install 'markitdown[all]'",
            file=sys.stderr,
        )
        return None

    plugin_cfg = _load_plugin_config()
    plugins_enabled = plugin_cfg.get("enabled", False)
    ocr_cfg = plugin_cfg.get("ocr", {})
    ocr_enabled = plugins_enabled and ocr_cfg.get("enabled", False)

    kwargs: dict = {}

    if plugins_enabled:
        kwargs["enable_plugins"] = True

    if ocr_enabled:
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            print("[read_pdf] markitdown-ocr 已启用但未找到 OPENAI_API_KEY，跳过 OCR 插件", file=sys.stderr)
        else:
            try:
                from openai import OpenAI
                kwargs["llm_client"] = OpenAI(api_key=api_key)
                kwargs["llm_model"] = ocr_cfg.get("llm_model", "gpt-4o")
                print(
                    f"[read_pdf] OCR 插件已启用（模型: {kwargs['llm_model']}）",
                    file=sys.stderr,
                )
            except ImportError:
                print(
                    "[read_pdf] openai 包未安装，OCR 插件跳过。运行: pip install openai",
                    file=sys.stderr,
                )

    try:
        md = MarkItDown(**kwargs)
        result = md.convert(pdf_path)
        text = result.text_content or ""
        if _is_useful(text):
            return text
        print(f"[read_pdf] MarkItDown 输出内容过少（{len(text.strip())} 字符），尝试 fallback", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[read_pdf] MarkItDown 失败：{e}，尝试 fallback", file=sys.stderr)
        return None


def read_with_opendataloader(pdf_path: str) -> str | None:
    """使用 opendataloader-pdf 提取，失败返回 None"""
    try:
        import opendataloader_pdf as odl
    except ImportError:
        print("[read_pdf] opendataloader-pdf 未安装。运行: pip install -U opendataloader-pdf", file=sys.stderr)
        return None

    tmp_dir = tempfile.mkdtemp(prefix="odl_pdf_")
    try:
        print("[read_pdf] 启动 opendataloader-pdf（需要 Java 11+，首次较慢）...", file=sys.stderr)
        odl.convert(
            input_path=pdf_path,
            output_dir=tmp_dir,
            format="markdown",
            quiet=True,
            use_struct_tree=True,   # 利用 PDF 结构树，保留语义顺序
            reading_order="xycut",  # xycut 算法更适合学术论文多栏排版
        )

        # 找到输出的 .md 文件
        md_files = [f for f in os.listdir(tmp_dir) if f.endswith(".md")]
        if not md_files:
            print("[read_pdf] opendataloader-pdf 未生成 .md 文件", file=sys.stderr)
            return None

        md_path = os.path.join(tmp_dir, md_files[0])
        with open(md_path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()

        if _is_useful(text):
            return text

        print("[read_pdf] opendataloader-pdf 输出内容过少", file=sys.stderr)
        return None

    except FileNotFoundError:
        print("[read_pdf] Java 未找到。请安装 JDK 11+：https://adoptium.net/", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[read_pdf] opendataloader-pdf 失败：{e}", file=sys.stderr)
        return None
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def read_pdf(pdf_path: str, force_odl: bool = False) -> str:
    """
    主入口：优先 MarkItDown，失败时 fallback 到 opendataloader-pdf。
    force_odl=True 时跳过 MarkItDown 直接用 opendataloader-pdf。
    """
    pdf_path = os.path.normpath(pdf_path)
    if not os.path.exists(pdf_path):
        print(f"ERROR: File not found: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    if not force_odl:
        text = read_with_markitdown(pdf_path)
        if text is not None:
            print("[read_pdf] ✓ MarkItDown 成功", file=sys.stderr)
            return text

    text = read_with_opendataloader(pdf_path)
    if text is not None:
        print("[read_pdf] ✓ opendataloader-pdf 成功", file=sys.stderr)
        return text

    print("ERROR: 两种引擎均无法提取内容，请检查 PDF 文件或 Java 安装", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: read_pdf.py <pdf_path> [--force-odl]", file=sys.stderr)
        sys.exit(1)

    path = sys.argv[1]
    force = "--force-odl" in sys.argv

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(read_pdf(path, force_odl=force))

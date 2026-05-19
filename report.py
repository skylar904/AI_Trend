from datetime import datetime
from pathlib import Path


def generate_markdown_report(articles):
    today = datetime.now().strftime("%Y-%m-%d")

    lines = []
    lines.append(f"# {today} AI 科技情報")
    lines.append("")
    lines.append("## 今日新文章整理")
    lines.append("")

    for i, article in enumerate(articles, start=1):
        lines.append(f"## {i}. {article['title']}")
        lines.append("")
        lines.append(f"- 來源：{article['source']}")
        lines.append(f"- 類別：{article['category']}")
        lines.append(f"- 發布時間：{article['published']}")
        lines.append(f"- 連結：{article['link']}")
        lines.append("")

        if article.get("ai_summary"):
            lines.append(article["ai_summary"])
            lines.append("")
        elif article.get("summary"):
            lines.append("### RSS 原始摘要")
            lines.append("")
            lines.append(article["summary"])
            lines.append("")

        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def save_report(markdown_text):
    today = datetime.now().strftime("%Y-%m-%d")

    report_dir = Path("reports")
    report_dir.mkdir(exist_ok=True)

    file_path = report_dir / f"{today}.md"
    file_path.write_text(markdown_text, encoding="utf-8")

    return file_path
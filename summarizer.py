import os
from openai import OpenAI
from dotenv import load_dotenv


load_dotenv()

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY")
)


def summarize_article(article):
    """
    將單篇文章整理成中文科技情報摘要。
    """

    title = article.get("title", "")
    source = article.get("source", "")
    category = article.get("category", "")
    summary = article.get("summary", "")
    link = article.get("link", "")

    prompt = f"""
你是一個給資工/電子相關學生看的 AI 科技情報整理員。

請根據下面文章資訊，用繁體中文整理成簡潔但有用的情報。

文章標題：
{title}

來源：
{source}

分類：
{category}

RSS 原始摘要：
{summary}

連結：
{link}

請輸出格式如下：

### 中文摘要
用 2~4 句話說明這篇文章/工具/消息在講什麼。

### 為什麼重要
用 2~3 句話說明它可能代表什麼趨勢，或為什麼值得注意。

### 適合誰關注
列出適合關注的人，例如 AI 工具使用者、軟體工程師、研究生、資工學生、創業者等。

### 對鴨妤的建議
請用很白話的方式說明：
這個東西需不需要追？
如果值得追，建議先看什麼？
如果不重要，也請直接說可以略過。
"""

    response = client.responses.create(
        model="gpt-5.4-nano",
        input=prompt
    )

    return response.output_text
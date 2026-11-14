"""Смалява свалена страница на екскурзия до фикстура за тестовете.

    uv run python tests/reduce_fixture.py сваленa.html > tests/fixtures/<име>.html

Остават само нещата, които четецът гледа: og-таговете, класът на <body>,
цената в заглавието и описанието (.single_tour_content) без скриптове, стилове,
картинки и атрибути. Текстът не се пипа – от дължината му зависи кое е „карта“.
"""
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup, Comment

KEEP_ATTRS = {"class", "colspan", "rowspan"}


def reduce(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    metas = []
    for prop in ("og:title", "og:description", "og:image"):
        m = soup.find("meta", property=prop)
        if m and m.get("content"):
            metas.append(f'<meta property="{prop}" content="{m["content"].replace(chr(34), "&quot;")}">')
    body_cls = " ".join(c for c in (soup.body.get("class", []) if soup.body else [])
                        if c.startswith(("postid-", "single")))
    price = soup.select_one(".single_tour_price")
    content = soup.select_one(".single_tour_content")
    if content is None:
        raise SystemExit("Няма .single_tour_content – това не е страница на екскурзия.")
    for t in content(["script", "style", "svg", "noscript", "template", "iframe", "img", "picture", "video", "form"]):
        t.decompose()
    for c in content.find_all(string=lambda s: isinstance(s, Comment)):
        c.extract()
    for el in content.find_all(True):
        el.attrs = {k: v for k, v in el.attrs.items() if k in KEEP_ATTRS}
        if "class" in el.attrs:
            cls = [c for c in el.attrs["class"] if c.startswith(("twu-", "pp_accordion"))]
            if cls:
                el.attrs["class"] = cls
            else:
                del el.attrs["class"]
    body = re.sub(r"[ \t]*\n\s*", "\n", str(content))
    body = re.sub(r">[ \t]+<", ">\n<", body)   # по един елемент на ред – за четими разлики в git
    title = soup.title.string.strip() if soup.title and soup.title.string else ""
    price_html = f'<div class="single_tour_price">{price.get_text(" ", strip=True)}</div>' if price else ""
    return (f'<!doctype html>\n<html lang="bg">\n<head>\n<meta charset="utf-8">\n<title>{title}</title>\n'
            + "\n".join(metas) + f'\n</head>\n<body class="{body_cls}">\n{price_html}\n{body}\n</body>\n</html>\n')


if __name__ == "__main__":
    sys.stdout.write(reduce(Path(sys.argv[1]).read_text(encoding="utf-8")))

#!/usr/bin/env python3
"""Extrai as 10 autorais do PDF 'Karine e os Vagalumes', descolunando via
coordenadas com detecção de calha (gutter). Saída: JSON {ordem, titulo, texto}."""
import json, sys
import pdfplumber

PDF = "/home/danielar/Downloads/Karine e os Vagalumes - Repertorio .pdf"

# tom/progressão principal por música (do próprio PDF), para o cabeçalho
TONS = {
    "Tardes de Novembro": "G  (G–G9–Em7 · C9 · D)",
    "Luzes da Cidade": "G7M  (G7M–Bm7–Am7–D7(9))",
    "Fruto Proibido": "Am7–D7(9)–G7M–Bm7  (BPM ~145)",
    "Nossas Canções": "Am7–Gm7  (refrão C7(9)–D7(9)) · ternário",
    "Meu Rapaz": "Bbm7–Eb7(9)–Abm7–D7(9)",
    "Gaiola": "—",
    "Novos Tempos": "E–C–A–B",
    "Minha Felicidade": "C7M–D7M (a música toda)",
    "SuperStar": "Em–B–C–F",
    "Bicicleta": "—",
}


def detect_gutter(words, width):
    """Retorna x da calha central se a página for de 2 colunas, senão None."""
    step = 2
    n = int(width // step) + 2
    covered = [False] * n
    for w in words:
        a, b = int(w["x0"] // step), int(w["x1"] // step)
        for k in range(a, b + 1):
            if 0 <= k < n:
                covered[k] = True
    lo, hi = width * 0.35, width * 0.65
    best = None
    run_start = run_end = None
    for k in range(n):
        x = k * step
        if not covered[k] and lo <= x <= hi:
            if run_start is None:
                run_start = x
            run_end = x
        else:
            if run_start is not None:
                if best is None or (run_end - run_start) > (best[1] - best[0]):
                    best = (run_start, run_end)
                run_start = None
    if run_start is not None and (best is None or (run_end - run_start) > (best[1] - best[0])):
        best = (run_start, run_end)
    if best and (best[1] - best[0]) >= 14:
        return (best[0] + best[1]) / 2
    return None


def column_lines(words):
    rows = {}
    for w in words:
        rows.setdefault(round(w["top"] / 3.0), []).append(w)
    out = []
    for key in sorted(rows):
        ws = sorted(rows[key], key=lambda w: w["x0"])
        out.append(" ".join(w["text"] for w in ws))
    return out


def page_lines(page):
    words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
    if not words:
        return []
    g = detect_gutter(words, page.width)
    if g:
        left = [w for w in words if w["x0"] < g]
        right = [w for w in words if w["x0"] >= g]
        return column_lines(left) + [""] + column_lines(right)
    return column_lines(words)


def extract(pdf_path=PDF):
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            pages.append("\n".join(page_lines(page)).strip())

    # Ordem fixa das páginas 3–12 do PDF
    ORDER = list(TONS.keys())

    songs = []
    for idx, body in enumerate(pages[2:], 1):  # pula capa (1) e índice (2)
        title = ORDER[idx - 1] if idx - 1 < len(ORDER) else f"Música {idx}"
        # remove do corpo qualquer linha igual ao título
        rest = "\n".join(
            l for l in body.split("\n") if l.strip().lower() != title.lower()
        ).strip()
        songs.append({"n": idx, "title": title, "tom": TONS.get(title, "—"), "body": rest})
    return songs


def main():
    json.dump(extract(), sys.stdout, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()

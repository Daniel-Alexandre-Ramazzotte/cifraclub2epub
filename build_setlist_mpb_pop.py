#!/usr/bin/env python3
"""Driver em lote: gera EPUB + PDF da setlist 'MPB & Pop pra Cantar Junto'
no tom original das músicas, reusando as funções do cifraclub2epub.py."""
import sys, subprocess, html as htmlmod
from pathlib import Path
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent))
from cifraclub2epub import (
    slugify, build_url, fetch_page, parse_main_cifra,
    strip_embedded_tabs, strip_lyricless_chords, strip_to_lyrics, build_epub, CSS,
)


def render_pdf(items, out_dir, base, title, subtitle, key):
    """Monta HTML a partir de items[key] e converte para PDF via LibreOffice."""
    parts = [
        "<html><head><meta charset='utf-8'><style>", CSS,
        "h1{page-break-before:always;} .first{page-break-before:avoid;}",
        f"</style></head><body><h1 class='first' style='font-size:1.8em'>{htmlmod.escape(title)}</h1>",
        f"<p style='font-family:sans-serif'>{htmlmod.escape(subtitle)}</p>",
    ]
    for c in items:
        parts.append(
            f"<h1>{htmlmod.escape(c['title'])}</h1>"
            f"<h2>{htmlmod.escape(c['artist'])}</h2>"
            f"<pre>{htmlmod.escape(c[key])}</pre>"
        )
    parts.append("</body></html>")
    html_path = out_dir / f"{base}.html"
    html_path.write_text("".join(parts), encoding="utf-8")
    subprocess.run(
        ["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(out_dir), str(html_path)],
        check=True, timeout=180, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    pdf_path = out_dir / f"{base}.pdf"
    if pdf_path.exists():
        print(f"✓ PDF:  {pdf_path} ({pdf_path.stat().st_size/1024:.1f} KB)")
    else:
        print(f"⚠ PDF não gerado: {base}")
    return pdf_path

TITLE = "Setlist · MPB & Pop pra Cantar Junto"

# (artista_principal, [artistas_alternativos], musica) — ordem do show
SETLIST = [
    ("Tom Jobim",       ["Antonio Carlos Jobim"],     "Corcovado"),
    ("Tom Jobim",       ["Vinicius de Moraes"],        "Garota de Ipanema"),
    ("Joao Gilberto",   ["Tom Jobim"],                 "Chega de Saudade"),
    ("Tribalistas",     [],                            "Velha Infancia"),
    ("Liniker",         [],                            "Caju"),
    ("Marina Sena",     ["Marisa Monte"],              "Me Toca"),
    ("Marisa Monte",    [],                            "Vilarejo"),
    ("Nando Reis",      [],                            "All Star"),
    ("Tribalistas",     [],                            "Ja Sei Namorar"),
    ("Roberta Campos",  ["Nando Reis"],                "De Janeiro a Janeiro"),
    ("Nando Reis",      [],                            "Pra Voce Guardei o Amor"),
    ("Ana Carolina",    [],                            "Quem de Nos Dois"),
    ("Ana Carolina",    ["Mato Grosso e Mathias"],     "Rosas"),
    ("Raca Negra",      ["Lulu Santos"],               "Sabado a Noite"),   # correção do usuário
    ("A-ha",            ["aha"],                       "Take On Me"),
    ("Cyndi Lauper",    [],                            "Girls Just Want to Have Fun"),
    ("Coldplay",        [],                            "The Scientist"),
    ("Radiohead",       [],                            "Creep"),
    ("Oasis",           [],                            "Wonderwall"),
    ("Legiao Urbana",   [],                            "Tempo Perdido"),
    ("Rita Lee",        [],                            "Lanca Perfume"),
    ("Rita Lee",        [],                            "Erva Venenosa"),
    ("Seu Jorge",       ["Zeca Pagodinho"],            "Amiga da Minha Mulher"),
]


def extract_tom(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    import re as _re
    el = soup.find(id="cifra_tom")
    txt = el.get_text(strip=True) if el else None
    if not txt:
        sp = soup.find("span", string=_re.compile(r"tom", _re.I))
        txt = sp.get_text(strip=True) if sp else None
    if txt:
        return _re.sub(r"^\s*tom\s*:?\s*", "", txt, flags=_re.I).strip() or None
    return None


def fetch_song(primary, alts, song):
    song_slug = slugify(song)
    for artist in [primary, *alts]:
        url = build_url(slugify(artist), song_slug)
        html = fetch_page(url)
        if not html:
            continue
        data = parse_main_cifra(html)
        if data:
            data["tom"] = extract_tom(html)
            data["source_url"] = url
            return data
    return None


def main():
    cifras = []
    falhas = []
    for i, (primary, alts, song) in enumerate(SETLIST, 1):
        print(f"[{i:02d}/{len(SETLIST)}] {song} — {primary} …", end=" ", flush=True)
        data = fetch_song(primary, alts, song)
        if not data:
            print("✗ FALHOU")
            falhas.append((i, song, primary))
            continue
        base_text = strip_embedded_tabs(data["chord_text"])   # tom original: sem transpor
        text = strip_lyricless_chords(base_text)              # remove intros/solos sem letra
        lyrics = strip_to_lyrics(base_text)                   # versão só com a letra
        tom = data.get("tom") or "?"
        cifras.append({
            "n": i,
            "title": f"{i:02d}. {data['title']}",
            "artist": f"{data['artist']}  ·  Tom original: {tom}",
            "chord_text": text,
            "lyrics": lyrics,
        })
        print(f"✓ (tom {tom})")

    if not cifras:
        print("Nenhuma cifra baixada. Abortando.")
        return 1

    out_dir = Path(__file__).parent
    base = "setlist-mpb-pop-cantar-junto"
    epub_path = out_dir / f"{base}.epub"
    html_path = out_dir / f"{base}.html"

    # EPUB (reusa build_epub do app)
    build_epub(cifras, epub_path, TITLE)
    print(f"\n✓ EPUB: {epub_path} ({epub_path.stat().st_size/1024:.1f} KB)")

    # PDF com cifras (tom original)
    render_pdf(cifras, out_dir, base, TITLE,
               "Cifras no tom original — gerado pelo cifraclub2epub.", "chord_text")

    # PDF só com a letra
    render_pdf(cifras, out_dir, f"{base}-letras", f"{TITLE} — Só Letras",
               "Versão só com a letra — gerado pelo cifraclub2epub.", "lyrics")

    if falhas:
        print("\n⚠ Não baixadas (ajustar artista/slug):")
        for i, song, art in falhas:
            print(f"   {i:02d}. {song} — {art}")
    print(f"\nTotal no caderno: {len(cifras)}/{len(SETLIST)} músicas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

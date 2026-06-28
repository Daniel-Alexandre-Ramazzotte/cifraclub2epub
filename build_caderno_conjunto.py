#!/usr/bin/env python3
"""Caderno CONJUNTO: autorais (Karine e os Vagalumes) + covers (Cifra Club),
na ordem alternativa do show. Gera EPUB + PDF (cifras) + PDF (só letras)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from cifraclub2epub import (
    slugify, strip_embedded_tabs, strip_lyricless_chords, strip_to_lyrics, build_epub,
)
from build_setlist_mpb_pop import SETLIST, fetch_song, render_pdf
from extract_autorais import extract

TITLE = "Caderno Karine e os Vagalumes — Autoral + Covers"

# Ordem alternativa: ("A", título autoral) | ("C", nome do cover como no SETLIST)
JOINT = [
    ("C", "Velha Infancia"),
    ("A", "Tardes de Novembro"),
    ("C", "Caju"),
    ("A", "Luzes da Cidade"),
    ("C", "Vilarejo"),
    ("A", "Minha Felicidade"),
    ("C", "All Star"),
    ("A", "Novos Tempos"),
    ("C", "Ja Sei Namorar"),
    ("A", "Bicicleta"),
    ("C", "Quem de Nos Dois"),
    ("A", "Nossas Canções"),
    ("C", "Take On Me"),
    ("A", "Fruto Proibido"),
    ("C", "The Scientist"),
    ("A", "Meu Rapaz"),
    ("C", "Creep"),
    ("A", "Gaiola"),
    ("C", "Wonderwall"),
    ("A", "SuperStar"),
    ("C", "Tempo Perdido"),
    ("C", "Lança Perfume"),  # cover extra
    ("C", "Amiga da Minha Mulher"),
]

COVER_LOOKUP = {slugify(song): (primary, alts, song) for primary, alts, song in SETLIST}
AUTORAIS = {a["title"]: a for a in extract()}


def main():
    entries = []
    falhas = []
    for i, (kind, name) in enumerate(JOINT, 1):
        if kind == "A":
            a = AUTORAIS.get(name)
            if not a:
                print(f"[{i:02d}] ⟡ {name} … ✗ autoral não encontrada")
                falhas.append((i, name))
                continue
            body = a["body"]
            entries.append({
                "title": f"{i:02d}. {name}  ⟡",
                "artist": f"Karine e os Vagalumes  ·  Tom: {a['tom']}",
                "chord_text": body,
                "lyrics": strip_to_lyrics(body),
            })
            print(f"[{i:02d}] ⟡ {name} … ✓ autoral")
        else:
            entry = COVER_LOOKUP.get(slugify(name))
            if not entry:
                print(f"[{i:02d}] {name} … ✗ não está no SETLIST")
                falhas.append((i, name))
                continue
            primary, alts, song = entry
            data = fetch_song(primary, alts, song)
            if not data:
                print(f"[{i:02d}] {name} … ✗ download falhou")
                falhas.append((i, name))
                continue
            base = strip_embedded_tabs(data["chord_text"])
            tom = data.get("tom") or "?"
            entries.append({
                "title": f"{i:02d}. {data['title']}",
                "artist": f"{data['artist']}  ·  Tom original: {tom}",
                "chord_text": strip_lyricless_chords(base),
                "lyrics": strip_to_lyrics(base),
            })
            print(f"[{i:02d}] {name} … ✓ cover (tom {tom})")

    if not entries:
        print("Nada para gerar."); return 1

    out_dir = Path(__file__).parent
    base = "caderno-karine-vagalumes-conjunto"
    epub_path = out_dir / f"{base}.epub"

    build_epub(entries, epub_path, TITLE)
    print(f"\n✓ EPUB: {epub_path} ({epub_path.stat().st_size/1024:.1f} KB)")
    render_pdf(entries, out_dir, base, TITLE,
               "Autorais (⟡) no tom da banda + covers no tom original.", "chord_text")
    render_pdf(entries, out_dir, f"{base}-letras", f"{TITLE} — Só Letras",
               "Versão só com a letra.", "lyrics")

    print(f"\nTotal: {len(entries)}/{len(JOINT)} músicas"
          f" ({sum(1 for k,_ in JOINT if k=='A')} autorais + {sum(1 for k,_ in JOINT if k=='C')} covers).")
    if falhas:
        print("Falhas:", falhas)
    return 0


if __name__ == "__main__":
    sys.exit(main())

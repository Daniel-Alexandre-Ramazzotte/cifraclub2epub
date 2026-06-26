#!/usr/bin/env python3
"""
cifraclub2epub — baixa cifras do Cifra Club e gera EPUB para Kindle
Uso no Termux (Android). Requer: pip install requests beautifulsoup4 ebooklib
"""

import os
import re
import sys
import shutil
import subprocess
import unicodedata
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from ebooklib import epub

# ── Configurações ────────────────────────────────────────────────────────────

KINDLE_EMAIL = os.environ.get("KINDLE_EMAIL", "alexandre.ramazzotte@kindle.com")

HEADERS_DESKTOP = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
}

HEADERS_MOBILE = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 13; Pixel 7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Mobile Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
}

CACHE_DIR = Path.home() / ".cache" / "cifraclub2epub"
DOWNLOADS_DIR = Path.home() / "storage" / "downloads"

# ── Notas para transposição ───────────────────────────────────────────────────

CHROMATIC = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
ENHARMONIC = {
    "Db": "C#", "Eb": "D#", "Fb": "E", "Gb": "F#",
    "Ab": "G#", "Bb": "A#", "Cb": "B",
}

# ── Utilitários ───────────────────────────────────────────────────────────────

def slugify(text: str) -> str:
    """Converte texto em slug URL-safe."""
    text = text.lower().strip()
    # Remove sufixos entre parênteses: (Ao Vivo), (feat. X), etc.
    text = re.sub(r"\(.*?\)", "", text)
    # Remove 'feat.' e variantes
    text = re.sub(r"\bfeat\.?\b.*", "", text, flags=re.IGNORECASE)
    # Normaliza acentos
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    # Substitui & e separadores por hífen
    text = re.sub(r"[&/\\]", "-", text)
    # Remove caracteres que não são alfanuméricos ou hífen
    text = re.sub(r"[^\w\s-]", "", text)
    # Colapsa espaços/hífens
    text = re.sub(r"[\s_-]+", "-", text)
    return text.strip("-")


def _looks_like_html(text: str) -> bool:
    """Heurística para detectar HTML válido vs conteúdo binário corrompido."""
    sample = text[:500].lower()
    return any(tag in sample for tag in ["<html", "<!doctype", "<head", "<meta"])


def save_debug_html(html: str, artist: str, song: str):
    """Salva HTML de debug em cache e em Downloads."""
    name = f"falha_{slugify(artist)}_{slugify(song)}.html"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / name).write_text(html, encoding="utf-8", errors="replace")
    if DOWNLOADS_DIR.exists():
        shutil.copy(CACHE_DIR / name, DOWNLOADS_DIR / name)
        print(f"   ⚠ HTML de debug salvo em Downloads/{name}", file=sys.stderr)


# ── Fetch ─────────────────────────────────────────────────────────────────────

def _fetch_with_requests(url: str) -> str | None:
    session = requests.Session()
    # Aquece a sessão na homepage primeiro
    try:
        session.get("https://www.cifraclub.com.br/", headers=HEADERS_DESKTOP, timeout=10)
    except Exception:
        pass
    for headers in (HEADERS_DESKTOP, HEADERS_MOBILE):
        try:
            r = session.get(url, headers=headers, timeout=15)
            if r.status_code == 200:
                text = r.content.decode("utf-8", errors="replace")
                if _looks_like_html(text):
                    return text
            if r.status_code == 403:
                continue
            print(f"   ⚠ HTTP {r.status_code} em {url}", file=sys.stderr)
            return None
        except requests.RequestException as e:
            print(f"   ⚠ Erro de rede: {e}", file=sys.stderr)
    return None


def _fetch_with_curl(url: str) -> str | None:
    curl = shutil.which("curl")
    if not curl:
        return None
    try:
        result = subprocess.run(
            [curl, "-sL", "--compressed",
             "-H", f"User-Agent: {HEADERS_DESKTOP['User-Agent']}",
             "-H", "Accept-Language: pt-BR,pt;q=0.9",
             url],
            capture_output=True, timeout=20,
        )
        text = result.stdout.decode("utf-8", errors="replace")
        if _looks_like_html(text):
            return text
    except Exception:
        pass
    return None


def fetch_page(url: str) -> str | None:
    """Tenta requests (desktop + mobile) depois curl como fallback."""
    text = _fetch_with_requests(url)
    if text:
        return text
    print("   ↻ Tentando curl como fallback…", file=sys.stderr)
    return _fetch_with_curl(url)


# ── Parser de cifra ───────────────────────────────────────────────────────────

def parse_main_cifra(html: str) -> dict | None:
    """
    Extrai título, artista e texto da cifra do HTML.
    Tenta 4 estratégias em cascata.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Metadados
    title_tag = soup.find("h1", class_=re.compile(r"title|cifra", re.I)) or soup.find("h1")
    artist_tag = soup.find("h2", class_=re.compile(r"artist|artista", re.I)) or soup.find("h2")
    title = title_tag.get_text(strip=True) if title_tag else "Desconhecido"
    artist = artist_tag.get_text(strip=True) if artist_tag else "Desconhecido"

    chord_text = None

    # Estratégia 1: <pre> direto
    pre = soup.find("pre")
    if pre:
        chord_text = pre.get_text()

    # Estratégia 2: div.cifra_cnt com <br>
    if not chord_text:
        div = soup.find("div", class_=re.compile(r"cifra_cnt|cifra-cnt", re.I))
        if div:
            for br in div.find_all("br"):
                br.replace_with("\n")
            chord_text = div.get_text("")

    # Estratégia 3: qualquer div com classe 'cifra'
    if not chord_text:
        div = soup.find("div", class_=re.compile(r"\bcifra\b", re.I))
        if div:
            for br in div.find_all("br"):
                br.replace_with("\n")
            chord_text = div.get_text("")

    # Estratégia 4: maior bloco de texto com padrão de acorde
    if not chord_text:
        candidates = soup.find_all(["div", "section", "article"])
        best = None
        best_score = 0
        for tag in candidates:
            text = tag.get_text()
            score = len(re.findall(r"\b[A-G][#b]?(?:m|maj|min|dim|aug|sus|add)?\d*\b", text))
            if score > best_score:
                best_score = score
                best = tag
        if best:
            for br in best.find_all("br"):
                br.replace_with("\n")
            chord_text = best.get_text("")

    if not chord_text:
        return None

    # Normaliza quebras de linha (máximo 2 consecutivas)
    chord_text = re.sub(r"\n{3,}", "\n\n", chord_text).strip()

    return {"title": title, "artist": artist, "chord_text": chord_text}


# ── Transposição de acordes ───────────────────────────────────────────────────

def transpose_chord_token(chord: str, semitones: int) -> str:
    """Transpõe um token de acorde (ex: 'F#m7b5', 'D/F#') por N semitons."""
    if semitones == 0:
        return chord

    def transpose_note(note: str) -> str:
        note = ENHARMONIC.get(note, note)
        if note not in CHROMATIC:
            return note
        idx = (CHROMATIC.index(note) + semitones) % 12
        return CHROMATIC[idx]

    # Acorde com baixo: D/F# → transpõe ambos
    if "/" in chord:
        parts = chord.split("/", 1)
        return "/".join(transpose_note_in_chord(p, semitones) for p in parts)

    return transpose_note_in_chord(chord, semitones)


def transpose_note_in_chord(chord: str, semitones: int) -> str:
    """Transpõe a nota raiz de um acorde, preservando qualidade (m, maj7, etc.)."""
    m = re.match(r"^([A-G][#b]?)(.*)", chord)
    if not m:
        return chord
    root, quality = m.group(1), m.group(2)
    root = ENHARMONIC.get(root, root)
    if root not in CHROMATIC:
        return chord
    idx = (CHROMATIC.index(root) + semitones) % 12
    return CHROMATIC[idx] + quality


def transpose_text(text: str, semitones: int) -> str:
    """Transpõe todos os acordes num bloco de texto de cifra."""
    if semitones == 0:
        return text

    CHORD_RE = re.compile(
        r"\b([A-G][#b]?(?:m|maj|min|dim|aug|sus|add)?(?:\d+)?(?:[#b]\d+)?(?:/[A-G][#b]?)?)\b"
    )

    def replace_chord(m):
        return transpose_chord_token(m.group(1), semitones)

    # Só aplica nas linhas de acorde (linhas sem letras comuns de música)
    lines = text.split("\n")
    result = []
    for line in lines:
        # Linha de acorde: tem tokens de acorde e pouco texto alfabético fora deles
        stripped = CHORD_RE.sub("", line)
        alpha_outside = re.sub(r"\s", "", stripped)
        if len(alpha_outside) <= 4 and CHORD_RE.search(line):
            line = CHORD_RE.sub(replace_chord, line)
        result.append(line)
    return "\n".join(result)


# ── Filtro de tablatura ───────────────────────────────────────────────────────

def strip_embedded_tabs(text: str) -> str:
    """Remove blocos de tablatura do texto da cifra."""
    lines = text.split("\n")
    filtered = []
    skip = False
    for line in lines:
        # Cabeçalho de tab
        if re.match(r"\[Tab\s*[-–]", line, re.IGNORECASE):
            skip = True
        # Linhas de tab: e|, B|, G|, D|, A|, E|
        elif re.match(r"\s*[eEBGDAd]\|", line):
            skip = True
        elif skip and line.strip() == "":
            skip = False
            continue
        elif skip:
            continue
        if not skip:
            filtered.append(line)
    return "\n".join(filtered)


# ── Construção do EPUB ────────────────────────────────────────────────────────

CSS = """
body { font-family: monospace; font-size: 0.85em; margin: 1em; }
h1 { font-size: 1.4em; margin-bottom: 0.2em; }
h2 { font-size: 1.0em; color: #555; margin-top: 0; margin-bottom: 1.2em; }
pre { white-space: pre-wrap; word-wrap: break-word; line-height: 1.5; }
"""


def build_epub(cifras: list[dict], out_path: Path, title: str):
    """
    cifras: lista de dicts com keys title, artist, chord_text
    """
    book = epub.EpubBook()
    book.set_title(title)
    book.set_language("pt")

    style = epub.EpubItem(
        uid="style", file_name="style.css",
        media_type="text/css", content=CSS
    )
    book.add_item(style)

    chapters = []
    for i, c in enumerate(cifras):
        content = (
            f"<h1>{c['title']}</h1>"
            f"<h2>{c['artist']}</h2>"
            f"<pre>{c['chord_text']}</pre>"
        )
        ch = epub.EpubHtml(
            title=c["title"],
            file_name=f"cap_{i+1:03d}.xhtml",
            lang="pt",
        )
        ch.content = f'<html><body>{content}</body></html>'
        ch.add_item(style)
        book.add_item(ch)
        chapters.append(ch)

    book.toc = tuple(chapters)
    book.spine = ["nav"] + chapters
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    epub.write_epub(str(out_path), book)


# ── Email via Android intent ──────────────────────────────────────────────────

def open_email_with_attachment(path: Path, to_email: str, subject: str, body: str) -> bool:
    """Abre cliente de email no Android com anexo via am start."""
    am = shutil.which("am")
    if not am:
        return False
    try:
        subprocess.run([
            am, "start",
            "-a", "android.intent.action.SEND",
            "--es", "android.intent.extra.EMAIL", to_email,
            "--es", "android.intent.extra.SUBJECT", subject,
            "--es", "android.intent.extra.TEXT", body,
            "--eu", "android.intent.extra.STREAM", f"file://{path}",
            "--et", "type", "application/epub+zip",
        ], check=True, timeout=10)
        return True
    except Exception:
        return False


# ── CLI helpers ───────────────────────────────────────────────────────────────

def ask_yn(prompt: str, default: bool = True) -> bool:
    hint = "S/n" if default else "s/N"
    resp = input(f"{prompt} [{hint}]: ").strip().lower()
    if resp == "":
        return default
    return resp in ("s", "sim", "y", "yes")


def parse_url_or_slug(raw: str) -> tuple[str, str] | None:
    """Extrai (artista, musica) de uma URL ou retorna None."""
    m = re.search(
        r"cifraclub\.com\.br/([^/?\s]+)/([^/?\s]+)",
        raw.strip()
    )
    if m:
        return m.group(1), m.group(2)
    return None


def build_url(artist_slug: str, song_slug: str) -> str:
    return f"https://www.cifraclub.com.br/{artist_slug}/{song_slug}/"


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    print("╔══════════════════════════════╗")
    print("║  cifraclub2epub  🎸📖        ║")
    print("╚══════════════════════════════╝\n")

    cifras = []

    while True:
        print(f"─── Música {len(cifras)+1} ───")
        raw = input("URL ou 'artista/musica' (Enter para finalizar): ").strip()
        if not raw:
            if not cifras:
                print("Nenhuma música adicionada. Saindo.")
                return 0
            break

        # Resolve artista/música
        parsed = parse_url_or_slug(raw)
        if parsed:
            artist_slug, song_slug = parsed
        else:
            # Entrada manual
            artist_slug = slugify(input("  Artista: "))
            song_slug = slugify(input("  Música:  "))

        url = build_url(artist_slug, song_slug)
        print(f"  Buscando {url} …")

        html = fetch_page(url)
        if not html:
            print(f"  ✗ Não consegui baixar a página.", file=sys.stderr)
            continue

        data = parse_main_cifra(html)
        if not data:
            save_debug_html(html, artist_slug, song_slug)
            print(f"  ✗ Não encontrei a cifra na página.", file=sys.stderr)
            continue

        print(f"  ✓ {data['title']} — {data['artist']}")

        # Transposição
        shift_raw = input("  Transposição em semitons (0 = sem transpor): ").strip()
        try:
            shift = int(shift_raw)
        except ValueError:
            shift = 0

        # Tablatura
        include_tab = ask_yn("  Incluir tablatura?", default=False)

        text = data["chord_text"]
        if not include_tab:
            text = strip_embedded_tabs(text)
        if shift:
            text = transpose_text(text, shift)

        cifras.append({
            "title": data["title"],
            "artist": data["artist"],
            "chord_text": text,
        })
        print(f"  ✓ Adicionado!\n")

    # Nome do EPUB
    if len(cifras) == 1:
        default_title = f"{cifras[0]['title']} — {cifras[0]['artist']}"
    else:
        default_title = input(f"Nome do EPUB [{len(cifras)} músicas]: ").strip() or "cifras"

    out_name = slugify(default_title) + ".epub"
    out_path = Path.home() / out_name

    print(f"\nGerando {out_name}…")
    build_epub(cifras, out_path, default_title)
    print(f"✓ Pronto: {out_path}  ({out_path.stat().st_size / 1024:.1f} KB)")

    # Copia para Downloads
    if DOWNLOADS_DIR.exists():
        dest = DOWNLOADS_DIR / out_name
        shutil.copy(out_path, dest)
        print(f"✓ Copiado para Downloads/{out_name}")

    # Enviar pro Kindle
    if ask_yn(f"\nAbrir email para enviar ao Kindle ({KINDLE_EMAIL})?", True):
        ok = open_email_with_attachment(
            out_path,
            to_email=KINDLE_EMAIL,
            subject=default_title,
            body=f"{len(cifras)} música(s) — gerado pelo cifraclub2epub.",
        )
        if ok:
            print("✓ Cliente de email aberto. Confere o destinatário e envia!")
        else:
            print("⚠ Não consegui abrir o email automaticamente.")
            print(f"  Anexe manualmente: {out_path}")
            print(f"  Destinatário: {KINDLE_EMAIL}")

    # Abrir localmente
    if ask_yn("Abrir o EPUB agora?", False):
        termux_open = shutil.which("termux-open")
        if termux_open:
            subprocess.Popen([termux_open, str(out_path)])
        else:
            print("⚠ termux-open não encontrado. Instale: pkg install termux-tools")

    return 0


if __name__ == "__main__":
    sys.exit(main())

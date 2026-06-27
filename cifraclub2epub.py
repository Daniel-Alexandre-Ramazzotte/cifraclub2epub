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

    # Metadados — prioriza o <title> da página, que tem o formato
    # "Música - Artista - Cifra Club" e é mais confiável que varrer h1/h2
    # (há h1 de seções como "Toque também" que confundem a heurística).
    title = artist = None
    title_tag_doc = soup.find("title")
    if title_tag_doc:
        parts = [p.strip() for p in title_tag_doc.get_text().split(" - ")]
        # Descarta o sufixo "Cifra Club"
        parts = [p for p in parts if p and p.lower() != "cifra club"]
        if len(parts) >= 2:
            title, artist = parts[0], parts[1]
        elif len(parts) == 1:
            title = parts[0]

    # Fallback: h1.t1 (título da cifra) ou primeiro h1/h2
    if not title:
        h1 = soup.find("h1", class_="t1") or soup.find("h1")
        title = h1.get_text(strip=True) if h1 else "Desconhecido"
    if not artist:
        h2 = soup.find("h2", class_=re.compile(r"artist|artista", re.I)) or soup.find("h2")
        artist = h2.get_text(strip=True) if h2 else "Desconhecido"

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


# ── Filtro de trechos sem letra ───────────────────────────────────────────────

_CHORD_RE = re.compile(
    r"\b([A-G][#b]?(?:m|maj|min|dim|aug|sus|add)?(?:\d+)?(?:[#b]\d+)?(?:/[A-G][#b]?)?)\b"
)


def _is_section(line: str) -> bool:
    """Cabeçalho de seção puro, ex.: '[Primeira Parte]'."""
    return bool(re.match(r"\s*\[.*\]\s*$", line))


def _strip_leading_tag(line: str) -> str:
    """Remove um rótulo de seção no início da linha (ex.: '[Intro] Am G' → 'Am G')."""
    return re.sub(r"^\s*\[[^\]]*\]\s*", "", line)


def _is_chord_line(line: str) -> bool:
    """Linha essencialmente de acordes — inclusive com rótulo inline (ex.: '[Intro] Em G').

    Conta apenas letras fora dos acordes (ignora dígitos e pontuação como 'x2', '(4)').
    """
    if not line.strip() or _is_section(line):
        return False
    rest = _strip_leading_tag(line)
    if not rest.strip():
        return False
    outside = re.sub(r"[^A-Za-z]", "", _CHORD_RE.sub("", rest))
    return len(outside) <= 4 and bool(_CHORD_RE.search(rest))


def _is_lyric_line(line: str) -> bool:
    return bool(line.strip()) and not _is_section(line) and not _is_chord_line(line)


def strip_lyricless_chords(text: str) -> str:
    """Remove trechos só de acordes, sem letra (intros, solos, finais instrumentais).

    Mantém uma linha de acorde apenas quando a próxima linha não-vazia é letra;
    e descarta cabeçalhos de seção (ex.: [Intro], [Solo]) que ficarem sem conteúdo.
    """
    lines = text.split("\n")
    n = len(lines)

    # 1) Mantém linha de acorde só se a próxima linha não-vazia for letra
    kept = []
    for i, line in enumerate(lines):
        if _is_chord_line(line):
            j = i + 1
            while j < n and not lines[j].strip():
                j += 1
            if j < n and _is_lyric_line(lines[j]):
                kept.append(line)
            # senão: trecho instrumental → descarta
        else:
            kept.append(line)

    # 2) Descarta cabeçalhos de seção que ficaram sem conteúdo
    out = []
    m = len(kept)
    for i, line in enumerate(kept):
        if _is_section(line):
            j = i + 1
            has_content = False
            while j < m and not _is_section(kept[j]):
                if kept[j].strip():
                    has_content = True
                    break
                j += 1
            if not has_content:
                continue
        out.append(line)

    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def strip_to_lyrics(text: str) -> str:
    """Versão só com a letra: remove todas as linhas de acorde, mantendo letra
    e cabeçalhos de seção com conteúdo (ex.: [Refrão])."""
    lines = [l for l in text.split("\n") if not _is_chord_line(l)]
    out = []
    m = len(lines)
    for i, line in enumerate(lines):
        if _is_section(line):
            j = i + 1
            has_content = False
            while j < m and not _is_section(lines[j]):
                if lines[j].strip():
                    has_content = True
                    break
                j += 1
            if not has_content:
                continue
        out.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


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

        # Remover trechos instrumentais (sem letra)
        only_lyrics = ask_yn("  Remover trechos sem letra (intro/solo/final)?", default=True)

        text = data["chord_text"]
        if not include_tab:
            text = strip_embedded_tabs(text)
        if only_lyrics:
            text = strip_lyricless_chords(text)
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

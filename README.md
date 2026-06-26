# cifraclub2epub 🎸📖

CLI para baixar cifras do [Cifra Club](https://www.cifraclub.com.br/), transpor tonalidade e gerar EPUB para leitura no Kindle — otimizado para rodar no **Termux (Android)**.

## Funcionalidades

- Aceita URL do Cifra Club ou entrada manual de artista/música
- Transposição de acordes por semitom (suporta voicings complexos: `F#m7b5`, `D/F#`, etc.)
- Opção de incluir ou remover tablatura
- Gera EPUB com fonte monoespaçada e formatação adequada para Kindle
- Copia automática para `~/storage/downloads/`
- Abre cliente de email pre-preenchido com seu endereço `@kindle.com`
- Fallback para `curl` quando o Cloudflare bloqueia o `requests`

## Instalação (Termux)

```bash
pkg install python curl
pip install requests beautifulsoup4 ebooklib

# Só na primeira vez:
termux-setup-storage
```

## Uso

```bash
python cifraclub2epub.py
```

O script é interativo — vai pedindo as músicas uma por uma. Cole a URL do Cifra Club ou informe artista/música manualmente. Ao final, gera o EPUB e oferece enviar ao Kindle.

## Configuração

Por padrão o email do Kindle é `alexandre.ramazzotte@kindle.com`. Para mudar:

```bash
export KINDLE_EMAIL="seu_email@kindle.com"
python cifraclub2epub.py
```

## Dependências

| Pacote | Uso |
|---|---|
| `requests` | Download das páginas |
| `beautifulsoup4` | Parser HTML |
| `ebooklib` | Geração do EPUB |

## Notas

- O Cifra Club usa Cloudflare; o script aquece a sessão e tenta desktop + mobile headers antes de cair no `curl`
- HTMLs de falha são salvos em `~/.cache/cifraclub2epub/` e em `Downloads/` para debug
- A transposição age apenas nas linhas de acordes (não nas letras)

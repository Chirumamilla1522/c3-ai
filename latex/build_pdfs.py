#!/usr/bin/env python3
"""Convert interview markdown guides to LaTeX + PDF with Mermaid rendered as images."""

from __future__ import annotations

import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LATEX_DIR = Path(__file__).resolve().parent
MMDC = LATEX_DIR / "node_modules" / ".bin" / "mmdc"

FILES = [
    ("dsa_patterns.md", "DSA Patterns — Concepts & Brute → Optimal"),
    ("text.md", "C3 AI Coding Prep — Worked Problems"),
    ("system_design.md", "C3 AI System Design Playbook"),
]

MERMAID_RE = re.compile(r"```mermaid\s*\n(.*?)```", re.DOTALL)


def strip_mermaid_init(src: str) -> str:
    """Remove %%{init: ...}%% directives that can confuse older mmdc."""
    return re.sub(r"%%\{init:.*?\}%%\s*", "", src, flags=re.DOTALL)


def render_mermaid(src: str, out_png: Path) -> bool:
    out_png.parent.mkdir(parents=True, exist_ok=True)
    mmd = out_png.with_suffix(".mmd")
    mmd.write_text(strip_mermaid_init(src).strip() + "\n", encoding="utf-8")
    # Scale up for readability in PDF
    cmd = [
        str(MMDC),
        "-i",
        str(mmd),
        "-o",
        str(out_png),
        "-b",
        "white",
        "-s",
        "2",
        "-w",
        "1400",
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if r.returncode != 0 or not out_png.exists():
            print(f"  WARN mermaid failed {out_png.name}: {r.stderr[-400:]}")
            return False
        return True
    except Exception as e:
        print(f"  WARN mermaid exception {out_png.name}: {e}")
        return False


def preprocess(md_path: Path, stem: str) -> Path:
    text = md_path.read_text(encoding="utf-8")
    img_dir = LATEX_DIR / "diagrams" / stem
    img_dir.mkdir(parents=True, exist_ok=True)

    matches = list(MERMAID_RE.finditer(text))
    jobs = []
    for i, m in enumerate(matches, start=1):
        png = img_dir / f"fig_{i:03d}.png"
        jobs.append((i, m.start(), m.end(), m.group(1), png, f"diagrams/{stem}/fig_{i:03d}.png"))

    results: dict[int, bool] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = {pool.submit(render_mermaid, src, png): i for i, _, _, src, png, _ in jobs}
        for fut in as_completed(futs):
            i = futs[fut]
            results[i] = fut.result()

    # Rebuild from end so indices stay valid
    pieces = []
    last = 0
    for i, start, end, src, png, rel in jobs:
        pieces.append(text[last:start])
        if results.get(i):
            pieces.append(f"\n\n![Diagram {i}]({rel}){{ width=95% }}\n\n")
        else:
            pieces.append(
                "\n> *[Diagram render failed — Mermaid source below]*\n\n"
                f"```\n{src.strip()}\n```\n"
            )
        last = end
    pieces.append(text[last:])
    processed = "".join(pieces)

    out = LATEX_DIR / f"{stem}_pre.md"
    out.write_text(processed, encoding="utf-8")
    ok = sum(1 for v in results.values() if v)
    print(f"  Preprocessed {len(jobs)} mermaid blocks ({ok} rendered) → {out.name}")
    return out


HEADER = r"""
\usepackage{fancyhdr}
\usepackage{booktabs}
\usepackage{longtable}
\usepackage{array}
\usepackage{float}
\usepackage{graphicx}
\usepackage{grffile}
\usepackage{microtype}
\usepackage{enumitem}
\usepackage{colortbl}
\usepackage{etoolbox}
\setlist{itemsep=0.25em,topsep=0.35em}
\pagestyle{fancy}
\fancyhf{}
\fancyhead[L]{\small\leftmark}
\fancyhead[R]{\small C3 AI Interview Prep}
\fancyfoot[C]{\thepage}
\renewcommand{\headrulewidth}{0.4pt}
\setlength{\headheight}{14pt}
\definecolor{codebg}{RGB}{245,245,245}
% --- nicer tables ---
\definecolor{TableHead}{RGB}{226,232,240}
\definecolor{TableRowAlt}{RGB}{241,245,249}
\definecolor{TableLine}{RGB}{71,85,105}
\arrayrulecolor{TableLine}
\setlength{\heavyrulewidth}{0.09em}
\setlength{\lightrulewidth}{0.05em}
\setlength{\tabcolsep}{8pt}
\renewcommand{\arraystretch}{1.65}
\setlength{\extrarowheight}{1.5pt}
% Make longtables use full text width
\setlength{\LTleft}{0pt}
\setlength{\LTright}{0pt}
\AtBeginEnvironment{longtable}{%
  \footnotesize
}
"""


def polish_tables(tex: Path) -> None:
    """Clean pandoc longtable markup for readable PDF tables."""
    s = tex.read_text(encoding="utf-8")

    # Replace bulky minipage header cells with bold text
    s = re.sub(
        r"\\begin\{minipage\}\[b\]\{\\linewidth\}\\raggedright\s*(.*?)\s*\\end\{minipage\}",
        lambda m: r"\textbf{" + m.group(1).strip() + "}",
        s,
        flags=re.DOTALL,
    )

    # Soft header-row tint after each toprule
    s = s.replace(
        "\\toprule\\noalign{}\n",
        "\\toprule\\noalign{}\n\\rowcolor{TableHead}\n",
    )

    # Zebra-stripe data rows (after \endlastfoot)
    s = _zebra_stripe_longtables(s)

    tex.write_text(s, encoding="utf-8")
    print(f"  Polished tables in {tex.name}")


def _zebra_stripe_longtables(s: str) -> str:
    def stripe_block(m: re.Match) -> str:
        block = m.group(0)
        if "\\endlastfoot" not in block:
            return block
        head, body = block.split("\\endlastfoot", 1)
        # body ends with \end{longtable}; split rows on \\
        if not body.rstrip().endswith("\\end{longtable}"):
            return block
        body_main, end = body.rsplit("\\end{longtable}", 1)
        # Split into rows; keep the trailing newline structure
        pieces = re.split(r"(\\\\\n)", body_main)
        # pieces alternate: content, separator, content, separator, ...
        row_idx = 0
        out = []
        i = 0
        while i < len(pieces):
            part = pieces[i]
            sep = pieces[i + 1] if i + 1 < len(pieces) else ""
            stripped = part.strip()
            is_row = bool(stripped) and not stripped.startswith("\\bottomrule") and not stripped.startswith("\\midrule")
            if is_row and ("&" in part or "\\texttt" in part or "\\textbf" in part or re.search(r"[A-Za-z0-9]", stripped)):
                row_idx += 1
                if row_idx % 2 == 1:
                    # insert rowcolor at first non-whitespace
                    part = re.sub(
                        r"^(\s*)",
                        r"\1\\rowcolor{TableRowAlt}",
                        part,
                        count=1,
                    )
            out.append(part)
            if sep:
                out.append(sep)
            i += 2 if sep else 1
        return head + "\\endlastfoot" + "".join(out) + "\\end{longtable}" + end

    return re.sub(
        r"\\begin\{longtable\}.*?\\end\{longtable\}",
        stripe_block,
        s,
        flags=re.DOTALL,
    )


def pandoc_to_tex(md: Path, title: str, stem: str, margin: str = "0.85in") -> Path:
    tex = LATEX_DIR / f"{stem}.tex"
    header_file = LATEX_DIR / "_header.tex"
    header_file.write_text(HEADER, encoding="utf-8")
    cmd = [
        "pandoc",
        str(md),
        "-f",
        "markdown+pipe_tables+fenced_code_blocks+backtick_code_blocks+raw_tex+link_attributes",
        "-t",
        "latex",
        "-o",
        str(tex),
        "--standalone",
        f"--metadata=title:{title}",
        "-V",
        "documentclass=article",
        "-V",
        f"geometry:margin={margin}",
        "-V",
        "fontsize=11pt",
        "-V",
        "colorlinks=true",
        "-V",
        "linkcolor=blue",
        "-V",
        "urlcolor=blue",
        "--toc",
        "--toc-depth=2",
        "--highlight-style=tango",
        f"--include-in-header={header_file}",
        "--resource-path",
        str(LATEX_DIR),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr)
        raise SystemExit(f"pandoc failed for {stem}")
    polish_tables(tex)
    print(f"  Wrote {tex.name}")
    return tex

def compile_pdf(tex: Path) -> Path:
    # Run from LATEX_DIR so relative diagram paths resolve
    r = subprocess.run(
        ["tectonic", "-X", "compile", "--outdir", str(LATEX_DIR), str(tex)],
        cwd=str(LATEX_DIR),
        capture_output=True,
        text=True,
    )
    # older tectonic CLI may not have -X compile
    if r.returncode != 0:
        r = subprocess.run(
            ["tectonic", str(tex), "--outdir", str(LATEX_DIR)],
            cwd=str(LATEX_DIR),
            capture_output=True,
            text=True,
        )
    pdf = LATEX_DIR / (tex.stem + ".pdf")
    if r.returncode != 0 or not pdf.exists():
        print(r.stdout[-2000:])
        print(r.stderr[-2000:])
        raise SystemExit(f"tectonic failed for {tex.name}")
    print(f"  Wrote {pdf.name} ({pdf.stat().st_size // 1024} KB)")
    return pdf


def main() -> None:
    if not MMDC.exists():
        print("mermaid-cli missing; run npm install in latex/", file=sys.stderr)
        raise SystemExit(1)

    for fname, title in FILES:
        stem = Path(fname).stem
        print(f"\n=== {fname} ===")
        md = ROOT / fname
        if not md.exists():
            print(f"  SKIP missing {md}")
            continue
        pre = preprocess(md, stem)
        tex = pandoc_to_tex(pre, title, stem)
        compile_pdf(tex)

    print("\nDone. Outputs in:", LATEX_DIR)


if __name__ == "__main__":
    main()

# LaTeX / PDF builds

Generated from:

- `../dsa_patterns.md`
- `../text.md`
- `../system_design.md`

## Outputs

| File | Description |
|------|-------------|
| `dsa_patterns.tex` / `dsa_patterns.pdf` | DSA patterns + diagrams |
| `text.tex` / `text.pdf` | Coding worked problems |
| `system_design.tex` / `system_design.pdf` | System design playbook |

PDFs are also copied to the parent `c3 ai/` folder.

## Rebuild

```bash
cd latex
npm install   # once — for mermaid-cli
python3 build_pdfs.py
```

Requires: `pandoc`, `tectonic` (Homebrew).

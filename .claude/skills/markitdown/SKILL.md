---
name: markitdown
disable-model-invocation: true
description: Convert a PDF, Word, PowerPoint, Excel, or Outlook .msg file to Markdown with Microsoft's markitdown CLI.
argument-hint: "<file path> [output .md path]"
---

Convert the file in $ARGUMENTS to Markdown with the `markitdown` CLI (v0.1.7, installed with `uv tool`, at `C:/Users/Blanco/.local/bin/markitdown.exe`).

1. No file path given: ask which file.
2. Run `markitdown "<input>" -o "<output>"`. Default output: same folder and base name as the input, `.md` extension. If that file already exists, ask before overwriting.
3. Report the output path and size, then show the first ~20 lines. Read the rest only if asked.

Notes:
- First run takes ~6 s (loads the file-type detector); later runs ~1 s.
- Installed formats are local only: PDF, DOCX, PPTX, XLSX, XLS, MSG. The audio, YouTube, and Azure extras are intentionally not installed.
- Don't pass an http(s) URL unless the user asks for one; markitdown downloads URLs.
- Don't use `-p`/`--use-plugins`, `-d`, or `--use-cu`.

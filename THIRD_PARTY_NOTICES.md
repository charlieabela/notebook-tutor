# Third-party notices

Notebook Tutor includes copies of the following libraries in `src/notebook_tutor/static/vendor/`, each with its
licence file next to it. They are unmodified.

| Library | Version | Licence | Use |
|---|---|---|---|
| [CodeMirror](https://codemirror.net/5/) (core, Python mode, matchbrackets add-on) | 5.65.16 | MIT | code editor in each cell |
| [marked](https://github.com/markedjs/marked) | 12.0.2 | MIT | Markdown rendering |
| [DOMPurify](https://github.com/cure53/DOMPurify) | 3.1.6 | Apache-2.0 or MPL-2.0 (Apache-2.0 chosen) | cleaning rendered HTML |
| [MathJax](https://www.mathjax.org/) (`es5/tex-svg-full.js`) | 3.2.2 | Apache-2.0 | rendering mathematics |

The page also requests three typefaces from Google Fonts when the computer is online (Bricolage Grotesque,
IBM Plex Sans and JetBrains Mono, all under the SIL Open Font License 1.1). They are not distributed with
Notebook Tutor; without a connection the page falls back to the system fonts.

Python dependencies (Jupyter, NumPy, pandas, Matplotlib, seaborn, scikit-learn, networkx, openpyxl,
ai-learning-kit and, with the `advanced` option, PyTorch and PyTorch Geometric) are installed by the package
manager from their own distributions under their own licences; Notebook Tutor does not include copies of them.

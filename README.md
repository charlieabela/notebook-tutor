# Notebook Tutor

A teaching assistant for Jupyter notebooks that runs on your own computer. Open a notebook from your lecturer, run
its cells, and the tutor explains each cell, asks you questions as you go, and checks the code you write. Python
runs in a normal Jupyter kernel in the notebook's folder, so files are read and saved next to the notebook, and
libraries such as pandas, scikit-learn and (optionally) PyTorch work as they do in Jupyter.

The explanations come from a language model that **you** choose: Google Gemini, Anthropic Claude or OpenAI with
your own API key, or an open-weight model on your own computer through Ollama. Your key stays on your computer.
Without a model, Python, your lecturer's own questions and the checks in
[ai-learning-kit](https://github.com/charlieabela/ai-learning-kit) still work.

Notebook Tutor was written for learning data science and AI at every level, from a first programming course to
doctoral research, and works with any `.ipynb` notebook.

## Install

You need [uv](https://docs.astral.sh/uv/), a small program that installs Python and the tutor's libraries for
you. You do not need to install Python yourself.

**1. Install uv** (once)

- Windows: open **PowerShell** and run
  `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
- macOS or Linux: open **Terminal** and run
  `curl -LsSf https://astral.sh/uv/install.sh | sh`

Close the window and open a new one, so that the `uv` command is found.

**2. Install Notebook Tutor**

```
uv tool install --python 3.12 https://github.com/charlieabela/notebook-tutor/archive/refs/tags/v0.3.3.zip
```

This takes a few minutes the first time. If the next step says `nt` is not found, run `uv tool update-shell`,
then open a new window.

**Which install do I need?**

| Your notebooks are about | Install | Adds |
|---|---|---|
| data formats, web data, cleaning, exploring data, modelling, text to graphs, graph embeddings | the standard install above | NumPy, pandas, Matplotlib, seaborn, scikit-learn, networkx, NLTK, the Neo4j driver, ai-learning-kit |
| graph neural networks, knowledge graphs, retrieval-augmented generation, transformers | the advanced install below | PyTorch, sentence-transformers, Hugging Face transformers, PyTorch Geometric, rdflib and owlrl |

Your lecturer says which install the course needs. On an Intel Mac, the advanced install uses PyTorch 2.2 with the versions of NumPy, transformers and sentence-transformers that work with it, because PyTorch is no longer built for Intel Macs; the notebooks run the same.

For the advanced install (about 1 GB more), use this instead:

```
uv tool install --python 3.12 "notebook-tutor[advanced] @ https://github.com/charlieabela/notebook-tutor/archive/refs/tags/v0.3.3.zip"
```

**You also need [Git](https://git-scm.com/downloads)**, because the tutor installs ai-learning-kit from its GitHub repository through git. On macOS, typing `git` in a terminal offers to install it.

**Alternative: work from a clone.** If you use git, clone the repository and start the tutor from its folder;
uv creates the environment on first use:

```
git clone https://github.com/charlieabela/notebook-tutor.git
cd notebook-tutor
uv run nt                       # or: uv run --extra advanced nt
```

## Start

```
nt                              # your notebooks (see below)
nt "path/to/my folder"          # notebooks in that folder
nt "path/to/notebook.ipynb"    # open that notebook
```

The tutor opens in your browser. Keep the window where you typed `nt` open while you work; press **Ctrl+C** in
it to stop the tutor. If the browser does not open, copy the address the window prints (it ends in `?t=…`).

**Your notebooks.** Take the notebook your lecturer gives you (from the VLE or Drive) and add it with
**Open notebook › Add a notebook from this computer**. The tutor keeps your copy and saves it as you work: your
code, outputs and progress are written into the `.ipynb` file. Next time, open it from the list, which shows the
five notebooks you used most recently (**Show all** lists the rest; nothing is deleted). A notebook built with
ai-learning-kit is kept in a folder for its topic (for example `graph-embeddings/`), together with the
files its code writes and the data files you add for it, so different topics never mix. Run from a clone
(`uv run nt`), the tutor keeps your notebooks in the clone's `notebooks/` folder, which git ignores, so
`git pull` never touches them; an installed tutor keeps them in `NotebookTutor` in your home folder. You can
open the same files in Jupyter, VS Code or Colab later.

If you add a notebook you already have, the tutor asks: **Open your saved copy (keeps your work)**, or
**Replace it with this file** (for example when your lecturer has updated it; your work in the old copy is
discarded). Either way there is only one copy. Notebooks you used with tutor 0.1.6 or earlier stay where they
were (`NotebookTutor` in your home folder); add the ones you still need, with your work in them, the same way.

**Your own cells, deleting cells and a fresh start.** Before the first cell, between any two cells and after the last one, **+ Code** and **+ Text** add a cell of your own there; text cells take Markdown and maths as in Jupyter, and **Edit** reopens a text cell you added. The bin beside a cell (shown when the pointer is over it) deletes it: a cell you added goes at once, while a cell from your lecturer's notebook first explains what you lose, including the later cells that use what it defines. Only your copy changes, and **Undo** brings a deleted cell back. Added and deleted cells are saved in the notebook file. **Clear notes**, at the top of *Ask the tutor*, removes every explanation, answer, checkpoint and *Quiz me* question and the conversation, after asking you to confirm; your code, outputs and added cells stay, and the tutor's questions are asked again as you run the cells. **Hide** folds the *Ask the tutor* panel away so the notebook takes the whole window; the **Ask the tutor** button brings it back.

**The topic reference.** For a notebook built with ai-learning-kit, **Topic reference** shows the page of its topic: what the topic covers and at which level, what you do yourself, what the kit does for you (and which of those steps you can look inside), and every helper of `T = kit.tools()` with what it takes and what it does. Links and the list at the top lead to the other topics. The pages are generated from the kit the tutor runs, so they always match the helpers your notebook calls; `kit.source(T.<name>)` in a cell prints a helper's code.

**Data.** Notebooks built with ai-learning-kit download the datasets they need the first time, from the
publisher's website, and check them. Run from a clone, the tutor keeps them in the clone's `data/` folder (git
ignores it), so your clone holds the datasets of the notebooks you opened and nothing else; an installed tutor
keeps them in your user cache folder. If the publisher's site does not answer, the kit takes the same file from a course copy, which it checks the same way. If that fails too, the tutor says which file is missing: add the copy
your lecturer provides (for example on the VLE) with **Data files › Add data file…** and run the cell again. The
kit checks that it is the right file and keeps it, so you add it once, for every notebook that needs it. A copy
elsewhere on your computer, or a link your lecturer shared, also works:

```python
kit.datasets.use("cora", "~/Downloads/cora.tgz")                     # a file on your computer
kit.datasets.use("cora", "https://drive.google.com/file/d/<id>/view") # a link your lecturer shared
```

Your own data, for your own experiments, goes next to your notebook with **Data files › Add data file…**;
read it by its file name.

## Working in VS Code

You can do everything from VS Code. Clone with **Git: Clone** in the Command Palette (Cmd+Shift+P on a Mac,
Ctrl+Shift+P on Windows), open the folder, and run `uv run nt` in VS Code's terminal (Terminal › New Terminal).
To keep the tutor inside VS Code rather than in your browser, run **Simple Browser: Show** from the Command
Palette and paste the address that `nt` prints. Do not open the same notebook in VS Code's own notebook editor
while the tutor has it open: both save the file, and the last save wins. Links in a notebook (a YouTube video, a paper) open in your
normal browser, because many sites, YouTube among them, do not work inside VS Code's built-in browser.

## Choose a language model

Open **Tutor settings › Language model › Change…** (or **Set up the tutor** when the tutor asks).

| Option | What you need | Notes |
|---|---|---|
| Google Gemini | an API key from [Google AI Studio](https://aistudio.google.com/apikey) | Usually the easiest to get. If AI Studio refuses with your university account, use a personal Google account or ask your lecturer. |
| Anthropic Claude | an API key from the [Claude Console](https://console.anthropic.com/settings/keys) | API use is billed separately from a Claude.ai subscription. |
| OpenAI | an API key from the [OpenAI platform](https://platform.openai.com/api-keys) | API use is billed separately from a ChatGPT subscription. |
| A model on this computer (Ollama) | [Ollama](https://ollama.com), then for example `ollama pull llama3.2` | Free and private; nothing leaves your computer. Small models are slower and less accurate. |
| Another OpenAI-compatible server | its address (LM Studio, vLLM, a course server) | |
| None | nothing | Python and the kit's checks still work. |

Use **Show available models** to pick a fast and a thorough model, and **Test the connection** before saving.

**Your key stays on your computer.** It is stored in the tutor's settings file (on Windows in
`%APPDATA%\notebook-tutor`, on macOS in `~/Library/Application Support/notebook-tutor`, on Linux in
`~/.config/notebook-tutor`), readable only by you on macOS and Linux. It is never written into notebooks or
answer books, the tutor's page never receives it back, and the notebook's Python does not see it: when a notebook
calls `kit.hint()` or `kit.ask()`, the request goes through the tutor, which adds the key itself. Prompts you send
go to the provider you chose, under that provider's terms; choose Ollama if nothing should leave your computer.

## For lecturers

- Any Jupyter or Colab notebook works as it is. [docs/PREPARING_NOTEBOOKS.md](docs/PREPARING_NOTEBOOKS.md)
  explains exercise cells, **plans from question to code** (steps that fade across a practice notebook, which
  the tutor's code checks and hints follow), and the optional `tutor` metadata for prediction questions, your own
  checkpoint questions and Try-it experiments. **About**, in the tutor, links to it.
- A notebook built with ai-learning-kit carries its topic, and optionally its level, in its metadata
  (`metadata.ai_learning_kit`). The tutor then sets the level (introductory, intermediate, advanced or research;
  the topic's own level when the notebook names none), follows the topic's scope (it explains the steps in focus,
  treats the kit's support helpers as support, and does not bring up what is out of scope) and never contradicts
  the kit's checks. Learners can change the level in the tutor at any time. The `%pip install` line for the kit is skipped, because the tutor provides the kit.
- **Notebooks keep working across kit releases.** A notebook runs on the kit version its first cell names. When that is an earlier major version than the tutor's (a notebook handed out before kit 1.0), the tutor downloads that version once, into `.tutor/kits/` in its notebooks folder, and runs the notebook with it, so a notebook behaves in the tutor exactly as in Colab or Jupyter. Within one major version the tutor's own kit runs every notebook, because released helpers never change.
- `nt --check` reports the installed libraries and tests the language-model settings, which helps when a student
  asks for help.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) describes how the parts fit together and the security model.

## Update

```
uv tool install --force --python 3.12 https://github.com/charlieabela/notebook-tutor/archive/refs/tags/vX.Y.Z.zip
```

with the version your lecturer gives you, or `git pull` in a clone.

## Troubleshooting

- **`nt` is not found:** run `uv tool update-shell` and open a new terminal window.
- **The page says it needs the session token:** use the full address printed by `nt`, or start `nt` again.
- **A cell runs for ever:** press **Stop**; if that does not help, **Restart Python**.
- **A notebook cannot download its data:** read the message under the cell; it lists the places the kit looked
  and the ways to give it a copy (see *Data* above). `kit.datasets.status()` shows what is where.
- **The tutor cannot reach the model:** open **Language model › Test the connection**; the message says whether
  the key, the model name or the connection is the problem. For Ollama, check that the Ollama app is running.

## Licence and acknowledgement

Copyright © 2026 Charlie Abela, University of Malta.

Notebook Tutor is free software: you can redistribute it and/or modify it under the terms of the GNU Affero
General Public License, version 3 (AGPL-3.0-only), as published by the Free Software Foundation; see
[LICENSE](LICENSE). It is distributed in the hope that it will be useful, but without any warranty; without even
the implied warranty of merchantability or fitness for a particular purpose.

In short: you may use, study, adapt and share Notebook Tutor, including in your own courses. If you distribute it
or a work based on it, or let people use a modified version over a network (for example as a hosted service),
you must make the complete source of that version available under the same licence, and keep the copyright
notices and [NOTICE](NOTICE). Releases up to v0.1.18 were published under the Apache License 2.0.

If you use or adapt Notebook Tutor in your teaching or research, please acknowledge the original work as
described in [NOTICE](NOTICE) and [CITATION.cff](CITATION.cff). Third-party components, and their own licences,
are listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

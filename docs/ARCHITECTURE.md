# How Notebook Tutor works

Notebook Tutor is a small web application that runs on the student's computer. Everything is local except the
calls to the language model the student chose.

```
 browser page (static/index.html + host.js)
      │  /api/... with the session token
      ▼
 local server (server.py, 127.0.0.1 only) ──────────────► language model
      │  settings.py: provider, models, API key            (Gemini, Claude, OpenAI,
      │  llm_bridge.py: prompts, JSON replies, errors        Ollama, any OpenAI-compatible)
      │                                                         ▲
      ▼                                                         │
 Jupyter kernel (kernel.py), started in the notebook's folder   │
      │  user code, ai-learning-kit, pandas, PyTorch ...        │
      └── kit.hint() / kit.ask() ── /v1/chat/completions ───────┘
                                    (proxy token, no API key)
```

## Parts

- **`server.py`** serves the page and its libraries, lists, opens and saves notebooks under one root folder,
  accepts uploads, starts one kernel per open notebook, and holds the language-model connection. The root folder
  is `notebooks/` in the tutor's git clone (ignored by git) or `~/NotebookTutor` for an installed tutor. An added
  notebook is kept once: a kit notebook in `<topic>/`, any other in the root; adding one the student
  already has returns `exists` (with whether it is the same file that was added, from the checksums in
  `.tutor/added.json`) and nothing is written until the student opens the saved copy or replaces it.
- **`kernel.py`** starts an ordinary IPython kernel with the same Python as the tutor, so every installed library
  is available. `run()` returns the outputs in the shape the page renders: text, HTML tables, figures (collected
  with matplotlib's Agg backend by `kernel_helpers.py`), and errors with the line that failed. `prepare()` skips
  `%pip` lines that would only reinstall ai-learning-kit.
- **`kits.py`** runs each notebook on the kit version it names. `requested()` reads the version from the notebook's
  metadata or install line; when it is of an earlier major version than the tutor's kit, `ensure()` installs that
  version once (`pip install --no-deps --target`, from the archive the install line names) into
  `<root>/.tutor/kits/<version>/`, the server starts that notebook's kernel with the folder first on `PYTHONPATH`, and
  `context()` asks that version, in a separate process, for the scope the tutor explains. The tutor itself keeps its
  own kit.
- **`llm_bridge.py`** builds the provider with `ai_learning_kit.llm.build()`, maps the page's "fast" and
  "thorough" tiers to the student's two models, extracts JSON replies (with one retry), and turns provider errors
  into the codes the page explains (`not_configured`, `bad_key`, `forbidden`, `model_not_found`,
  `rate_limited`, `offline`, `invalid_json`).
- **`static/index.html`** is the tutor's interface: guided walkthrough and practice modes, explanations,
  checkpoint questions, hints and experiments. When an exercise carries a plan from question to code (a *From question to code* label in its
  instructions and numbered comments in its starter code, see `docs/PREPARING_NOTEBOOKS.md`), its code check and
  hints follow the plan's steps. It is shared with the hosted version; **`static/host.js`** adapts
  it to this server (the page's `NBT_HOST` and `window.claude` interfaces).

## The kit and the tutor

A notebook built with ai-learning-kit stores its topic (and optionally its level) in `metadata.ai_learning_kit`.
The server asks the kit for `registry.tutor_context(topic, level=...)`: the level's description, the topics it
builds on, the case, the tasks with their guidance, and the topic's **scope**, which says which steps are in focus (explain in depth), which are black boxes (say what goes
in and out, and where the method is taught) and which are out of scope. The page adds the scope to every prompt,
adds a task's guidance when a cell refers to that task, and instructs the model never to contradict the kit's
checks or reveal the values they check. The kit decides what is correct; the model only explains.

**Topic reference** (`GET /api/kit/reference?topic=<name>`, from kit 1.1.0): the server asks its own kit for `ai_learning_kit.dev.reference.page(name)`, the topic's page as Markdown (the index without a name), and keeps each page once generated, because a topic's page imports its helpers. The page shows it in a dialog that opens on the notebook's topic and follows the links between topics. A topic whose extra is not installed still has its page, without the list of helpers.

## Security model

- The server listens on 127.0.0.1 only. Every `/api` request needs a random session token, created at start and
  passed to the page in the address. Host and Origin headers must name the server, which blocks other web pages
  and DNS rebinding.
- Paths from the page are resolved inside the root folder; anything outside is refused. Uploads are limited to
  data and notebook file types.
- The API key is stored in the user's configuration folder (mode 0600 on macOS and Linux), never in the
  repository, notebooks or answer books. The page receives only whether a key is stored and its last four
  characters.
- The kernel's environment has no API keys. The kit inside the kernel is pointed at the server's
  `/v1/chat/completions`, which accepts a separate proxy token and adds the real key itself.
- The kernel runs the notebook's code with the student's own permissions, exactly as Jupyter does. Open notebooks
  only from sources you trust.

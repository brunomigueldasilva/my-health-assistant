# 🏥 Personal Health Assistant — Agno + LLM + Telegram + Gradio

A multi-agent personal health assistant with RAG, powered by the [Agno](https://github.com/agno-agi/agno) framework.
Supports **5 LLM providers** and runs two interfaces side by side: a **Telegram Bot** and a **Gradio Web UI**.

---

## 🧠 Architecture

| Component | Description |
|-----------|-------------|
| 🎯 **Coordinator** | Routes messages to the right specialist (mode="route") |
| 🥗 **Nutritionist** | Meal plans, calories, macros, nutritional goals |
| 🏋️ **Personal Trainer** | Workouts, exercises, routines, fitness plans |
| 👨‍🍳 **Chef** | Personalised recipes based on food preferences |
| 🗄️ **RAG Knowledge Base** | ChromaDB with preferences, goals, and history |
| 👤 **User Profile** | SQLite with personal data and weight history |
| 💬 **Session Storage** | SQLite with per-user conversation history |
| 🔍 **Explainability (XAI)** | Transparent tracking of tool calls and RAG queries per message |

---

## ⚙️ Prerequisites

- Python 3.11+
- A Telegram account (Bot Token via [@BotFather](https://t.me/BotFather))
- One of the supported LLM providers (see below)

---

## 🚀 Setup

### 1. Choose your LLM provider

> 💡 **Recommended local model: `qwen2.5:32b`** (Ollama or LM Studio)
> Best-performing model for this project — no thinking overhead, reliable tool calling, and consistent agent routing.
> Requires a GPU with at least 32 GB VRAM (e.g. NVIDIA RTX 5090).
> On 24 GB VRAM (e.g. RTX 4090) the model loads but may produce slower or inconsistent responses.

<details>
<summary>🖥️ <b>Option A — Ollama (local, free)</b></summary>

**Windows** — Download and run the installer from [ollama.com/download/windows](https://ollama.com/download/windows), then:
```powershell
ollama serve
ollama pull qwen2.5:32b
```

**macOS / Linux**
```bash
# macOS
brew install ollama

# Linux
curl -fsSL https://ollama.com/install.sh | sh

ollama serve
ollama pull qwen2.5:32b
```

`.env`:
```env
LLM_PROVIDER=ollama
OLLAMA_MODEL=qwen2.5:32b
```
</details>

<details>
<summary>🖥️ <b>Option B — LM Studio (local, free)</b></summary>

1. Download [LM Studio](https://lmstudio.ai/) and install it
2. Download `qwen2.5:32b` (or any model) inside LM Studio
3. Go to **Local Server** tab → click **Start Server**
4. Copy the model identifier shown in the UI

`.env`:
```env
LLM_PROVIDER=lmstudio
LMSTUDIO_HOST=http://localhost:1234/v1
LMSTUDIO_MODEL=qwen2.5-32b-instruct
```
</details>

<details>
<summary>☁️ <b>Option C — Gemini (Google)</b></summary>

Get an API key from [Google AI Studio](https://aistudio.google.com/).

`.env`:
```env
LLM_PROVIDER=gemini
GOOGLE_API_KEY=AIza...
GEMINI_MODEL=gemini-2.5-flash
```
</details>

<details>
<summary>☁️ <b>Option D — OpenAI</b></summary>

Get an API key from [platform.openai.com](https://platform.openai.com/).

`.env`:
```env
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
```
</details>

<details>
<summary>☁️ <b>Option E — Anthropic (Claude)</b></summary>

Get an API key from [console.anthropic.com](https://console.anthropic.com/).

`.env`:
```env
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-sonnet-4-6
```
</details>

---

### 2. Create a Telegram Bot

1. Open Telegram and search for [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the instructions
3. Copy the **Bot Token**

---

### 3. Install dependencies

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
```

---

### 4. Configure

```bash
cp .env.example .env
```

Edit `.env` and set at minimum:
- `LLM_PROVIDER` — which provider to use
- The matching API key / model (see step 1)
- `TELEGRAM_BOT_TOKEN` — from @BotFather

---

### 5. Run

```bash
python main.py
```

Starts both the **Telegram Bot** and the **Gradio Web UI** at `http://localhost:7860`.
On first run the knowledge base is automatically seeded with nutritional and exercise data.

---

## 📱 Telegram

### Onboarding

When a new user sends `/start`, a guided 4-step onboarding flow is launched using inline keyboards — no manual typing required for structured choices:

```
/start
 ├─ New user → interactive onboarding (4 steps, ~1 minute)
 │    ├─ Step 1 — Personal data
 │    │    ├─ Gender       → buttons (Male / Female)
 │    │    ├─ Age          → free text input  (ex: 35)   [skippable]
 │    │    ├─ Height       → free text input  (ex: 175)  [skippable]
 │    │    └─ Weight       → free text input  (ex: 78.5) [skippable]
 │    ├─ Step 2 — Activity level  → 5 buttons (Sedentary → Very active)
 │    ├─ Step 3 — Health goal     → 8 buttons
 │    │    └─ "Target weight" → extra text input for target kg [skippable]
 │    └─ Step 4 — Allergies       → multi-select toggle buttons + confirm
 │         → Profile summary shown on completion
 │
 └─ Returning user → welcome-back message (onboarding skipped)
```

After onboarding the assistant immediately uses the profile to personalise all advice.

### 💬 Conversational examples

- **Nutrition**: "Quero um plano alimentar para perder gordura visceral"
- **Workout**: "Sugere um treino HIIT de 30 minutos"
- **Recipes**: "Dá-me uma receita saudável com frango e brócolos"
- **Goals**: "Quero chegar aos 75 kg em 3 meses"
- **Preferences**: "Não gosto de beterraba nem fígado"

### 📋 Commands

| Command         | Description                                                   |
|-----------------|---------------------------------------------------------------|
| `/start`        | Welcome message — launches onboarding for new users           |
| `/cancel`       | Cancel onboarding at any step                                 |
| `/perfil`       | View full profile                                             |
| `/preferencias` | Manage food likes/dislikes, allergies, restrictions and goals |
| `/peso <kg>`    | Log current weight                                            |
| `/historico`    | View weight history and trend                                 |
| `/reset`        | Clear conversation history (new session)                      |
| `/help`         | Show available commands                                       |

---

## 🌐 Gradio Web UI

A full web interface with **4 tabs**:

| Tab | Description |
|-----|-------------|
| 💬 **Conversa** | Chat with the agents in real time + XAI panel |
| 👤 **O Meu Perfil** | Edit personal data and log weight (chart included) |
| 🥗 **Preferências** | Manage likes, dislikes, allergies, restrictions and goals |
| ⚙️ **Administração** | Sub-tabs: Explicabilidade · Sessões · Logs · Base de Conhecimento |

> The **User ID** is shared across all tabs. Use your Telegram user ID to access existing profile data in the web UI.

---

## 🗂️ Project Structure

```
health-assistant/
├── main.py                       # Entry point — starts Telegram bot + Gradio UI
├── requirements.txt
├── .env
├── config/
│   └── __init__.py               # Configuration and LLM model factory
├── agents/
│   ├── coordinator.py            # Team router (mode="route")
│   ├── nutritionist.py           # Nutritionist agent
│   ├── trainer.py                # Personal trainer agent
│   └── chef.py                   # Chef agent
├── interfaces/
│   ├── telegram_bot.py           # Telegram interface + onboarding flow
│   └── gradio_app.py             # Gradio Web UI (4 tabs)
├── knowledge/
│   ├── __init__.py               # RAG with ChromaDB
│   └── seed_data.py              # Initial seed data (nutrition + exercises)
├── tools/
│   ├── nutrition_tools.py        # Calories, macros, food lookup
│   ├── exercise_tools.py         # Exercises and workout plans
│   └── profile_tools.py          # Profile, preferences, weight, allergies
├── xai/
│   └── __init__.py               # Explainability tracker (@xai_tool decorator)
├── data/
│   ├── chromadb/                 # Vector store (preferences, nutrition, exercises)
│   ├── user_profiles.db          # SQLite — profiles and weight history
│   └── sessions.db               # SQLite — conversation sessions (Agno)
└── logs/
    └── health-assistant.log      # Rotating log (5 MB × 3 files, append across runs)
```

---

## 🗄️ Data Storage

The project uses **three persistent stores**, each with a distinct role:

### SQLite — `data/user_profiles.db`

Relational store for structured personal data.

| Table | Fields |
|-------|--------|
| `user_profiles` | `user_id`, `name`, `age`, `gender`, `height_cm`, `weight_kg`, `activity_level`, `goal`, `created_at`, `updated_at` |
| `weight_history` | `user_id`, `weight_kg`, `recorded_at` |

### SQLite — `data/sessions.db`

Managed automatically by Agno. Stores the full conversation history (messages, tool calls, agent responses) per user session. Not accessed directly by the application code.

### ChromaDB — `data/chromadb/` (vector store)

Three collections, all using **cosine similarity** with `all-MiniLM-L6-v2` embeddings (ChromaDB default):

| Collection | What is stored | How it is used |
|------------|---------------|----------------|
| `preferences` | Short texts per user: food likes/dislikes, allergies, dietary restrictions, health goals | **Filter by metadata** (`user_id`, `category`) to build profile summaries; **semantic search** when agents query "what can this user not eat?" |
| `nutrition_knowledge` | Paragraphs of nutritional information (foods, calories, macros) seeded from `knowledge/seed_data.py` | **Semantic RAG** — retrieved by the Nutritionist and Chef agents when answering nutrition questions |
| `exercise_knowledge` | Paragraphs of exercise descriptions, muscle groups, calories burned | **Semantic RAG** — retrieved by the Personal Trainer agent when building workout plans |

#### When vector search adds value vs. metadata filtering

- **`preferences`** — items like `"frango"` or `"lactose"` are very short; the main retrieval path uses metadata filters (`user_id` + `category`). Vector similarity kicks in when the agent issues a free-text query (e.g. _"foods to avoid"_).
- **`nutrition_knowledge` / `exercise_knowledge`** — longer paragraphs; semantic search is the primary retrieval mechanism here, matching the intent of the agent's query against the knowledge base.

---

## 🔧 Design Notes

### Language

All **code** (agent instructions, tool docstrings, module/class docstrings) is in **English** — English yields better results with smaller local models for routing and tool-calling decisions.

**User-facing responses** and **knowledge base content** are in **Portuguese** — the model receives the instruction _"ALWAYS respond in European Portuguese"_ and generates output accordingly.

### Switching LLM providers

Just change `LLM_PROVIDER` in `.env` — no code changes required. The `get_model()` factory in `config/__init__.py` instantiates the correct Agno model object for all agents automatically.

### Session persistence

Agno automatically persists each session's history in `data/sessions.db`. Each user has one active session. `/reset` (Telegram) or "Nova Sessão" (Gradio) creates a new session without deleting previous history.

### Log persistence

Logs are written in **append mode** across restarts — each run appends to `logs/health-assistant.log` with a `── new run ──` separator. The file rotates at 5 MB (up to 3 backup files kept).

---

## 🛠️ Customisation

### Add your own initial preferences

Edit `knowledge/seed_data.py` — update the `FOOD_LIKES`, `FOOD_DISLIKES`, `ALLERGIES`, and `RESTRICTIONS` lists. Then reset the vector store:

```bash
# Windows
Remove-Item -Recurse -Force data\chromadb

# macOS / Linux
rm -rf data/chromadb

python main.py
```

### Add new agents

1. Create a file in `agents/` following the existing pattern
2. Add it as a `member` in `coordinator.py`
3. Create specific tools in `tools/` if needed

---

## 🤝 Contributing

Contributions are welcome! Here's how you can help:

### How to Contribute

1. **Fork the repository**
2. **Create a feature branch**:
   ```bash
   git checkout -b feature/YourFeature
   ```
3. **Make your changes**
4. **Commit your changes**:
   ```bash
   git commit -m "Add YourFeature"
   ```
5. **Push to the branch**:
   ```bash
   git push origin feature/YourFeature
   ```
6. **Open a Pull Request**

### Guidelines

- Follow [PEP 8](https://peps.python.org/pep-0008/) style guide for Python code
- Add docstrings to all new functions
- Include comments for complex logic
- Update `README.md` if adding new features
- Test your changes thoroughly before submitting

---

## 🆘 Support

If you encounter any issues or have questions:

1. **Read the docs** — check this README thoroughly
2. **Search issues** — look for similar problems in the [issue tracker](https://github.com/brunomigueldasilva/my-health-assistant/issues)
3. **Ask a question** — open a new issue with the `question` label
4. **Report a bug** — open an issue with:
   - Python version
   - Operating system
   - Error messages
   - Steps to reproduce

**Community:**
- 💬 [GitHub Discussions](https://github.com/brunomigueldasilva/my-health-assistant/discussions)
- 📧 [bruno_m_c_silva@proton.me](mailto:bruno_m_c_silva@proton.me)

---

## ⭐ Star History

If you find this project useful, please consider giving it a ⭐ on GitHub — it helps others discover it!

[![GitHub stars](https://img.shields.io/github/stars/brunomigueldasilva/my-health-assistant?style=social)](https://github.com/brunomigueldasilva/my-health-assistant/stargazers)

# Personal Health Assistant — Agno + LLM + Telegram + Gradio

A multi-agent personal health assistant with RAG, powered by the Agno framework.
Supports **5 LLM providers** — Ollama, Gemini, OpenAI, Anthropic (Claude), and LM Studio —
with two interfaces: Telegram Bot and Gradio Web UI.

## Architecture

- **Coordinator (Team route)** — Receives messages and routes them to the right specialist
- **Nutritionist Agent** — Meal plans, calories, macros, nutritional goals
- **Personal Trainer Agent** — Workouts, exercises, routines, fitness plans
- **Chef Agent** — Personalised recipes based on food preferences
- **RAG Knowledge Base** — ChromaDB with preferences, goals, and history
- **User Profile** — SQLite with personal data and weight history
- **Session Storage** — SQLite with per-user conversation history
- **Explainability (XAI)** — Transparent tracking of tool calls and RAG queries per message

## Prerequisites

- Python 3.11+
- A Telegram account (Bot Token via @BotFather)
- One of the supported LLM providers (see below)

## Setup

### 1. Choose your LLM provider

> **Recommended local model: `qwen2.5:32b`** (Ollama and LM Studio)
> This is the best-performing model for this project — it has no thinking overhead, reliably
> follows agent instructions, and consistently invokes tools (function calling).
> Requires a GPU with at least 32 GB VRAM (e.g. NVIDIA RTX 5090 or equivalent).
> On 24 GB VRAM (e.g. RTX 4090) the model loads but leaves little room for the KV cache,
> which may result in slower responses or inconsistent tool calling.

#### Option A — Ollama (local, free)

**Windows**
```powershell
# Download and run the installer from https://ollama.com/download/windows
# Then open a terminal and start Ollama:
ollama serve

# Pull the recommended model
ollama pull qwen2.5:32b
```

**macOS**
```bash
brew install ollama
ollama serve
ollama pull qwen2.5:32b
```

**Linux**
```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama serve
ollama pull qwen2.5:32b
```

Set in `.env`:
```env
LLM_PROVIDER=ollama
OLLAMA_MODEL=qwen2.5:32b
```

#### Option B — LM Studio (local, free)

1. Download [LM Studio](https://lmstudio.ai/) and install it
2. Download `qwen2.5:32b` (or any model) inside LM Studio
3. Go to **Local Server** tab and click **Start Server**
4. Copy the model identifier shown in the UI

Set in `.env`:
```env
LLM_PROVIDER=lmstudio
LMSTUDIO_HOST=http://localhost:1234/v1
LMSTUDIO_MODEL=qwen2.5-32b-instruct   # use the exact model ID shown in LM Studio
```

LM Studio exposes an OpenAI-compatible API — no API key required.

#### Option C — Gemini API (Google)

Get an API key from [Google AI Studio](https://aistudio.google.com/).

Set in `.env`:
```env
LLM_PROVIDER=gemini
GOOGLE_API_KEY=AIza...
GEMINI_MODEL=gemini-2.5-flash
```

#### Option D — OpenAI API (GPT-4, GPT-3.5, etc.)

Get an API key from [platform.openai.com](https://platform.openai.com/).

Set in `.env`:
```env
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
```

#### Option E — Anthropic API (Claude)

Get an API key from [console.anthropic.com](https://console.anthropic.com/).

Set in `.env`:
```env
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-sonnet-4-6
```

### 2. Create a Telegram Bot

1. Open Telegram and search for `@BotFather`
2. Send `/newbot` and follow the instructions
3. Copy the **Bot Token**

### 3. Install Python dependencies

**Windows**
```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

**macOS / Linux**
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 4. Configure

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

Then edit `.env` and set at minimum:

- `LLM_PROVIDER` — which provider to use
- The matching API key / model for that provider (see steps 1 above)
- `TELEGRAM_BOT_TOKEN` — from @BotFather

### 5. Run

```bash
python main.py
```

This starts both the **Telegram Bot** and the **Gradio Web UI** (`http://localhost:7860`).

On the first run, the knowledge base is automatically seeded with
nutritional and exercise data.

## Usage

### Telegram

#### Onboarding

When a new user sends `/start`, a guided onboarding flow is launched using
Telegram inline keyboards — no manual typing required for profile setup:

```
/start
 ├─ New user → interactive onboarding (4 steps, ~1 minute)
 │    ├─ Step 1 — Personal data: gender (buttons), age range (buttons),
 │    │           height and weight (text input with skip option)
 │    ├─ Step 2 — Activity level (5 buttons)
 │    ├─ Step 3 — Health goal (4 buttons)
 │    └─ Step 4 — Allergies (multi-select toggle buttons)
 │         → Profile summary shown on completion
 │
 └─ Returning user → welcome-back message (onboarding skipped)
```

After onboarding the assistant immediately uses the profile to personalise
all advice. Send any message in natural language to start.

#### Conversational examples

- **Nutrition**: "Quero um plano alimentar para perder gordura visceral"
- **Workout**: "Sugere um treino HIIT de 30 minutos"
- **Recipes**: "Dá-me uma receita saudável com frango e brócolos"
- **Goals**: "Quero chegar aos 75 kg em 3 meses"
- **Preferences**: "Não gosto de beterraba nem fígado"

#### Telegram Commands

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

### Gradio Web UI

A full web interface with **4 tabs** (the last tab groups admin tools into sub-tabs):

| Tab                        | Description                                             |
|----------------------------|---------------------------------------------------------|
| 💬 Conversa                | Chat with the agents in real time + XAI panel           |
| 👤 O Meu Perfil            | Edit personal data and log weight (chart included)      |
| 🥗 Preferências            | Manage likes, dislikes, allergies, restrictions, goals  |
| ⚙️ Administração           | Sub-tabs: Explicabilidade · Sessões · Logs · Base de Conhecimento |

The **User ID** is shared across all tabs. Use your Telegram user ID to access
existing profile data from the bot in the web UI.

## Project Structure

```
health-assistant/
├── main.py                       # Entry point (Telegram bot + Gradio UI)
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
│   ├── telegram_bot.py           # Telegram interface + onboarding ConversationHandler
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

## Design Notes

### Language in instructions vs. responses

**All code** (agent instructions, descriptions, tool docstrings, module and class
docstrings) is in **English** — the LLM interprets instructions internally for
routing and tool-calling decisions, and English yields better results with smaller
local models. Code documentation follows the same convention for consistency.

**User-facing responses** and **knowledge base content** are in **Portuguese**
because they are output — the model receives the instruction
"ALWAYS respond in European Portuguese" and generates text in the right language.

### Onboarding design

The Telegram onboarding uses a `ConversationHandler` (python-telegram-bot v21) with
8 states. Each step uses `InlineKeyboardMarkup` for structured choices (gender, age
range, activity level, goal) and free-text input with a skip button for numeric fields
(height, weight). Allergies use a toggle-button pattern — buttons update their label
with ✅ to reflect the current selection without leaving the step.

`/start` detects whether the user already has a complete profile (`age`, `gender`,
`weight_kg` set) and skips onboarding for returning users.

### Switching LLM providers

Just change `LLM_PROVIDER` in `.env` — no code changes required:

```env
# Ollama (local, free)
LLM_PROVIDER=ollama
OLLAMA_MODEL=qwen2.5:32b

# Gemini (Google)
LLM_PROVIDER=gemini
GOOGLE_API_KEY=AIza...

# OpenAI
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o

# Anthropic (Claude)
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-sonnet-4-6

# LM Studio (local, free)
LLM_PROVIDER=lmstudio
LMSTUDIO_MODEL=meta-llama-3.1-8b-instruct
```

The `get_model()` factory in [config/__init__.py](config/__init__.py) instantiates
the correct Agno model object for all agents automatically.

### Session persistence

Agno automatically persists each session's history in `data/sessions.db`.
Each user has one active session. `/reset` (Telegram) or "Nova Sessão" (Gradio)
creates a new session without deleting the previous history.

### Log persistence

Logs are written in **append mode** across restarts — each run appends to
`logs/health-assistant.log` with a `── new run ──` separator line.
When the file reaches 5 MB it rotates automatically (up to 3 backup files kept).

## Customisation

### Add your own initial preferences

Edit `knowledge/seed_data.py` — update the `FOOD_LIKES`, `FOOD_DISLIKES`,
`ALLERGIES`, and `RESTRICTIONS` lists with your data. Then:

**Windows**
```powershell
Remove-Item -Recurse -Force data\chromadb
python main.py
```

**macOS / Linux**
```bash
rm -rf data/chromadb
python main.py
```

### Add new agents

1. Create a file in `agents/` following the existing pattern
2. Add it as a `member` in `coordinator.py`
3. Create specific tools in `tools/` if needed

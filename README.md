# 🏥 Personal Health Assistant — Agno + LLM + Telegram + Gradio

A multi-agent personal health assistant with RAG, powered by the [Agno](https://github.com/agno-agi/agno) framework.
Supports **5 LLM providers** and runs two interfaces side by side: a **Telegram Bot** and a **Gradio Web UI**.

---

## 🧠 Architecture

| Component | Description |
|---|---|
| 🎯 **Coordinator** | Routes messages to the right specialist (`mode="route"`) — governance, ethics, and context management |
| 🥗 **Nutritionist** | Meal plans, calories, macros, nutritional goals |
| 🏋️ **Personal Trainer** | Workouts, exercises, routines, fitness plans |
| 👨‍🍳 **Chef** | Personalised recipes respecting food preferences and allergies |
| 📊 **Body Composition Analyst** | Syncs Tanita scale data, interprets body fat, visceral fat, muscle mass, BMR, metabolic age |
| 🗄️ **RAG Knowledge Base** | ChromaDB with nutrition knowledge, exercise knowledge, and per-user preferences (food likes/dislikes, allergies, dietary restrictions, and health goals) |
| 👤 **User Profile** | SQLite with personal data, weight history, and body composition history |
| 💬 **Session Storage** | SQLite with per-user conversation history (managed by Agno) |
| 🔍 **Explainability (XAI)** | Transparent tracking of tool calls and RAG queries per message |

> See [ARCHITECTURE.md](ARCHITECTURE.md) for detailed flow diagrams and architecture decisions.

---

## ⚙️ Prerequisites

- Python 3.11+
- A Telegram account (Bot Token via [@BotFather](https://t.me/BotFather))
- One of the supported LLM providers (see below)
- *(Optional)* A [MyTanita](https://mytanita.eu) account for body composition sync

---

## 🚀 Setup

### 1. Choose your LLM provider

> 💡 **Recommended local model: `qwen2.5:32b`** (Ollama or LM Studio)
> Best-performing model for this project — reliable tool calling and consistent agent routing.
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

# Required for Tanita sync (browser automation)
playwright install chromium
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
- *(Optional)* `USER_TANITA` + `PASS_TANITA` — for Tanita scale sync

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

When a new user sends `/start`, a guided onboarding flow is launched using inline keyboards — no manual typing required for structured choices:

```
/start
 ├─ New user → interactive onboarding (~1 minute)
 │    ├─ Step 1 — Personal data
 │    │    ├─ Gender         → 3 buttons (Male / Female / (Other / Prefer not to say))
 │    │    ├─ Date of birth  → free text input  (ex: 15/01/1990)  [skippable]
 │    │    ├─ Height         → free text input  (ex: 175)          [skippable]
 │    │    └─ Weight         → free text input  (ex: 78.5)         [skippable]
 │    ├─ Step 2 — Activity level  → 5 buttons (Sedentary → Very active)
 │    ├─ Step 3 — Health goal     → 13 buttons
 │    │    ├─ Perder peso / Ganhar massa muscular / Perder massa gorda
 │    │    ├─ Perder gordura visceral / Manter peso / Melhorar condição física
 │    │    ├─ Melhorar saúde em geral / Melhores hábitos alimentares
 │    │    ├─ Definir abdominais
 │    │    └─ Target goals → extra text input for the specific target value [skippable]:
 │    │         ├─ Atingir peso específico        (ex: 75 kg)
 │    │         ├─ Atingir massa muscular específica (ex: 65 kg ou 60%)
 │    │         ├─ Atingir gordura corporal específica (ex: 15%)
 │    │         └─ Atingir gordura visceral específica (ex: 6)
 │    └─ Step 4 — Allergies  → 6 multi-select toggle buttons + "None" + Confirm
 │         (Glúten · Lactose · Frutos secos · Marisco · Ovos · Amendoins)
 │         → Profile summary shown on completion
 │
 └─ Returning user → welcome-back message (onboarding skipped)
```

After onboarding the assistant immediately uses the profile to personalise all advice.

### 💬 Conversational examples

- **Nutrition**: "Quero um plano alimentar para perder gordura visceral"
- **Workout**: "Sugere um treino HIIT de 30 minutos"
- **Recipes**: "Dá-me uma receita saudável com frango e brócolos"
- **Body composition**: "Sincroniza as minhas medições da Tanita"
- **Goals**: "Quero chegar aos 75 kg em 3 meses"
- **Preferences**: "Não gosto de beterraba nem fígado"

### 📋 Commands

| Command | Description |
|---|---|
| `/start` | Welcome message — launches onboarding for new users |
| `/perfil` | View current profile summary |
| `/editar` | Edit profile fields (name, birth date, gender, height, weight, activity level, goal) |
| `/preferencias` | Manage food likes/dislikes, allergies, dietary restrictions and health goals |
| `/peso <kg>` | Log current weight |
| `/historico` | View weight history and trend |
| `/reset` | Clear conversation history (new session) |
| `/help` | Show available commands |

---

## 🌐 Gradio Web UI

A full web interface with **4 tabs**:

| Tab | Description |
|---|---|
| 💬 **Conversa** | Chat with the agents in real time + XAI panel |
| 👤 **O Meu Perfil** | Edit personal data and log weight (chart included) |
| 🥗 **Preferências** | Manage likes, dislikes, allergies, restrictions and goals |
| ⚙️ **Administração** | Sub-tabs: Explicabilidade · Sessões · Logs · Base de Conhecimento |

> The **User ID** is shared across all tabs. Use your Telegram user ID to access existing profile data in the web UI.

---

## 📊 Tanita Body Composition Sync

The **Body Composition Analyst** agent connects to [MyTanita.eu](https://mytanita.eu) and automatically downloads your scale measurements using browser automation (Playwright). No manual export needed.

**Metrics tracked** (13 fields per measurement):

| Metric | Description |
|---|---|
| `weight_kg` | Body weight in kg |
| `bmi` | Body Mass Index |
| `body_fat_pct` | Body fat percentage |
| `visceral_fat` | Visceral fat level (1–59) |
| `muscle_mass_kg` | Skeletal muscle mass in kg |
| `muscle_quality` | Muscle quality score |
| `bone_mass_kg` | Bone mass in kg |
| `bmr_kcal` | Basal Metabolic Rate (kcal/day) |
| `metabolic_age` | Metabolic age (years) |
| `body_water_pct` | Body water percentage |
| `physique_rating` | Physique rating (1–9) |

**Example prompts:**
- "Sincroniza as minhas medições da Tanita"
- "Qual era a minha gordura corporal em 15/03/2026?"
- "Mostra a evolução da minha gordura visceral nos últimos 3 meses"

---

## 🗂️ Project Structure

```
MyHealthAssistant/
├── main.py                           # Entry point — starts Telegram bot + Gradio UI
├── requirements.txt
├── .env / .env.example
├── ARCHITECTURE.md                   # Flow diagrams and architecture decisions
├── config/
│   └── __init__.py                   # Configuration constants + LLM model factory
├── agents/
│   ├── coordinator.py                # Team router (mode="route") + governance
│   ├── nutritionist.py               # Nutritionist agent
│   ├── trainer.py                    # Personal Trainer agent
│   ├── chef.py                       # Chef agent
│   └── body_composition_analyst.py   # Body Composition Analyst agent (Tanita)
├── interfaces/
│   ├── telegram_bot.py               # Telegram interface + onboarding flow
│   └── gradio_app.py                 # Gradio Web UI (4 tabs)
├── knowledge/
│   ├── __init__.py                   # KnowledgeBase class — ChromaDB wrapper
│   └── seed_data.py                  # Initial seed data (nutrition + exercises)
├── tools/
│   ├── nutrition_tools.py            # Calories, macros, food lookup (Open Food Facts fallback)
│   ├── exercise_tools.py             # Exercises, workout plans, calorie burn (MET)
│   ├── profile_tools.py              # Profile, preferences, weight history
│   └── tanita_tools.py               # Tanita portal sync via Playwright
├── xai/
│   └── __init__.py                   # ExplainabilityTracker + @xai_tool decorator
├── eval/
│   └── run_eval.py                   # Automated evaluation — 20 pre-defined queries
├── tests/
│   ├── conftest.py                   # Shared pytest fixtures
│   ├── test_knowledge.py
│   ├── test_tools_nutrition.py
│   ├── test_tools_exercise.py
│   ├── test_tools_profile.py
│   ├── test_tools_tanita.py
│   └── test_xai.py
├── data/
│   ├── chromadb/                     # Vector store (preferences, nutrition, exercises)
│   ├── user_profiles.db              # SQLite — profiles, weight history, body composition
│   └── sessions.db                   # SQLite — conversation sessions (Agno)
└── logs/
    └── health-assistant.log          # Rotating log (5 MB × 3 files, append across runs)
```

---

## 🗄️ Data Storage

The project uses **three persistent stores**, each with a distinct role:

### SQLite — `data/user_profiles.db`

| Table | Fields |
|---|---|
| `user_profiles` | `user_id`, `name`, `birth_date`, `gender`, `height_cm`, `weight_kg`, `activity_level`, `goal`, `created_at`, `updated_at` |
| `weight_history` | `user_id`, `weight_kg`, `recorded_at` |
| `body_composition_history` | `user_id`, `measured_at`, `weight_kg`, `bmi`, `body_fat_pct`, `visceral_fat`, `muscle_mass_kg`, `muscle_quality`, `bone_mass_kg`, `bmr_kcal`, `metabolic_age`, `body_water_pct`, `physique_rating` |

### SQLite — `data/sessions.db`

Managed automatically by Agno. Stores the full conversation history (messages, tool calls, agent responses) per user session. Not accessed directly by the application code.

### ChromaDB — `data/chromadb/` (vector store)

Three collections, all using **cosine similarity** with `all-MiniLM-L6-v2` embeddings (ChromaDB default):

| Collection | What is stored | How it is used |
|---|---|---|
| `user_preferences` | Short texts per user: food likes/dislikes, allergies, dietary restrictions, health goals | Filtered by `user_id` + `category` metadata; semantic search for free-text preference queries |
| `nutrition_knowledge` | Nutritional information: foods, calories, macros, diet guidance | Semantic RAG — retrieved by the Nutritionist and Chef agents |
| `exercise_knowledge` | Exercise descriptions, muscle groups, workout plans, calorie burn estimates | Semantic RAG — retrieved by the Personal Trainer agent |

---

## 🛡️ Ethics & Safety

The Coordinator enforces non-negotiable guardrails on every message before routing:

- **Refuses** extreme caloric restriction (< 800 kcal/day without medical supervision)
- **Refuses** promotion of disordered eating (purging, multi-day fasting, etc.)
- **Refuses** medical diagnoses, prescriptions, or treatment of diseases
- **Refuses** dangerous supplements or unproven treatments
- **Refuses** requests outside the health domain (political, discriminatory, illegal content)
- **Recommends** certified professionals for medical conditions, pregnancy, or chronic illness
- **GDPR-aware** — only uses data explicitly provided by the user; never cross-references users

---

## 🔍 Explainability (XAI)

Every agent response is accompanied by a detailed XAI report available in the **Explicabilidade** tab (Gradio):

- **Specialist activated** — which agent handled the request
- **Tools called** — function name, arguments, and result summary
- **RAG queries** — which ChromaDB collection was searched, with what query, and how many documents were retrieved
- **Formula notes** — mathematical foundations shown for caloric calculations (Mifflin-St Jeor) and calorie burn estimates (MET)

---

## 🧪 Automated Evaluation

The project includes an evaluation suite with **20 pre-defined queries** covering routing correctness, content quality, ethics guardrails, and edge cases:

```bash
# Run all 20 tests
python -X utf8 eval/run_eval.py

# Run a single test
python -X utf8 eval/run_eval.py --test-id Q15

# Show full agent responses
python -X utf8 eval/run_eval.py --verbose

# Export JSON report
python -X utf8 eval/run_eval.py --output eval/report.json
```

| Category | Tests | What is verified |
|---|---|---|
| Routing | Q01–Q09 | Each agent receives the correct message type |
| Quality | Q10–Q14 | Responses include expected content (macros, recipe steps, formulas) |
| Ethics | Q15–Q17 | Refusals triggered for extreme diets, diagnoses, off-topic requests |
| Edge cases | Q18–Q20 | Informal language, English input replied in PT, allergen substitution |

---

## 🔧 Design Notes

### Language

All **code** (agent instructions, tool docstrings, module docstrings) is in **English** — English yields better results with smaller local models for routing and tool-calling decisions.

**User-facing responses** are in **European Portuguese** — the Coordinator enforces this regardless of the language the user writes in.

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
3. Create specific tools in `tools/` if needed, decorated with `@xai_tool`

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/YourFeature`
3. Commit your changes: `git commit -m "Add YourFeature"`
4. Push to the branch: `git push origin feature/YourFeature`
5. Open a Pull Request

Follow [PEP 8](https://peps.python.org/pep-0008/), add docstrings to new functions, and update this README if adding new features.

---

## 🆘 Support

- **Issues**: [github.com/brunomigueldasilva/my-health-assistant/issues](https://github.com/brunomigueldasilva/my-health-assistant/issues)
- **Discussions**: [github.com/brunomigueldasilva/my-health-assistant/discussions](https://github.com/brunomigueldasilva/my-health-assistant/discussions)
- **Email**: [bruno_m_c_silva@proton.me](mailto:bruno_m_c_silva@proton.me)

When reporting a bug, include: Python version, OS, error message, and steps to reproduce.

---

[![GitHub stars](https://img.shields.io/github/stars/brunomigueldasilva/my-health-assistant?style=social)](https://github.com/brunomigueldasilva/my-health-assistant/stargazers)

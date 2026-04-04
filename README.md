# MyHealthAssistant — Personal Health Coach powered by AI

> **Your personal nutritionist, personal trainer, and chef, available 24/7 on your phone, with full data privacy.**

A multi-agent personal health assistant with RAG, powered by the [Agno](https://github.com/agno-agi/agno) framework.
Supports **5 LLM providers** and runs two interfaces side by side: a **Telegram Bot** and a **Gradio Web UI**.

---

## 💡 Why MyHealthAssistant?

| Equivalent service | Typical cost | With MyHealthAssistant |
|---|---|---|
| Nutritionist consultation | €60–120 / session | Unlimited plans included |
| Personal trainer | €40–80 / session | Unlimited workouts included |
| Premium tracking app | €10–15 / month | Free (open-source) |
| **Estimated savings** | **€200–400 / month** | **€0 with local Ollama** |

**Time saved:** reduces ~3 hours/week of research and planning to under 5 minutes.

**Full privacy:** with Ollama or LM Studio, no data ever leaves your computer.

---

## 🧠 Architecture

| Component | Description |
|---|---|
| 🎯 **Coordinator** | Routes messages to the right specialist (`mode="route"`) — governance, ethics, and context management |
| 🥗 **Nutritionist** | Meal plans, calories, macros, nutritional goals |
| 🏋️ **Personal Trainer** | Workouts, exercises, routines, fitness plans |
| 👨‍🍳 **Chef** | Personalised recipes respecting food preferences and allergies |
| 📊 **Body Composition Analyst** | Syncs Tanita scale data, interprets body fat, visceral fat, muscle mass, BMR, metabolic age |
| 🏃 **Activity Analyst** | Syncs Garmin Connect data — steps, calories, sleep, body battery, heart rate, VO2 max, training streak |
| 🗄️ **RAG Knowledge Base** | ChromaDB with nutrition knowledge, exercise knowledge, and per-user preferences (food likes/dislikes, allergies, dietary restrictions, and health goals) |
| 👤 **User Profile** | SQLite with personal data, weight history, and body composition history |
| 💬 **Session Storage** | SQLite with per-user conversation history (managed by Agno) |
| 🔍 **Explainability (XAI)** | Transparent tracking of tool calls and RAG queries per message |

> See [ARCHITECTURE.md](ARCHITECTURE.md) for detailed flow diagrams and architecture decisions.

---

## 🚀 Getting Started

### Prerequisites

- Python 3.11+
- A Telegram account + bot token (via [@BotFather](https://t.me/BotFather))
- One of the supported LLM providers (Ollama is free and local)
- *(Optional)* A [MyTanita](https://mytanita.eu) account for body composition sync
- *(Optional)* A [Garmin Connect](https://connect.garmin.com) account for activity and sleep data

---

### 1. Install dependencies

> Run the following commands from the **root of the project folder** (where `main.py` is located).

```bash
# macOS / Linux
bash scripts/setup.sh

# Windows
scripts\setup.bat
```

Creates the virtual environment, installs dependencies, installs Playwright, copies `.env.example` → `.env`, and auto-generates `SECRET_KEY`.

> If `.env` already exists the script keeps it — no values are overwritten.

---

### 2. Choose your LLM provider

> 💡 **Recommended local model: `qwen2.5:32b`** (Ollama or LM Studio)
> Best-performing model for this project — reliable tool calling and consistent agent routing.
> Requires a GPU with at least 32 GB VRAM (e.g. NVIDIA RTX 5090).
> On 24 GB VRAM (e.g. RTX 4090) the model loads but may produce slower or inconsistent responses.

Edit `.env` and set `LLM_PROVIDER` and the matching key:

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

### 3. Save the Telegram bot token

> ⚠️ Required **before** starting — the assistant will not launch without a configured token.

1. Open Telegram and search for [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the instructions
3. Copy the **Bot Token**

```bash
# Activate the virtual environment first:
source .venv/bin/activate     # macOS / Linux
.venv\Scripts\activate        # Windows

python scripts/setup_telegram.py
```

The script prompts for the token from [@BotFather](https://t.me/BotFather) and stores it **encrypted** in the SQLite database — never as plain text in `.env`.

---

### 4. Start the assistant

```bash
python main.py
```

Starts the **Telegram Bot** and the **Gradio Web UI** at `http://localhost:7860`.
On first run the knowledge base is automatically seeded with nutritional and exercise data.

---

### 5. Onboarding

Choose your preferred interface:

#### Via Telegram

1. Open Telegram and search for your bot by name
2. Send `/start`
3. Follow the guided wizard (~1 minute):
   - Personal data (gender, date of birth, height, weight)
   - Activity level
   - Health goals (lose weight, gain muscle, etc.)
   - Food allergies

#### Via Gradio (browser)

1. Open `http://localhost:7860`
2. Click **➕ Create new account** in the sidebar
3. Follow the same wizard steps in the browser

> The **User ID** is shared across both interfaces. Use your Telegram numeric ID in the Gradio UI to access the same profile.

---

### 6. Optional integrations

Configure after creating your profile — your `user_id` is shown with `/profile` in Telegram.

#### Tanita — body composition

```bash
python scripts/setup_credentials.py
# → choose "tanita" → enter your MyTanita email and password
```

Then ask the assistant: *"Sync my Tanita measurements"*

#### Garmin Connect — activity and sleep

```bash
python scripts/garmin_browser_auth.py --user <user_id>
```

Opens a Chromium window — log in with your Garmin account. OAuth tokens (~6 months validity) are saved to `data/garmin_tokens/<user_id>/`. **No password is stored after the flow completes.**

Then ask: *"How many steps did I take this week?"* or *"How was my sleep last night?"*

---

## 💬 What you can ask

| Area | Examples |
|---|---|
| **Nutrition** | "Give me a meal plan to lose visceral fat" |
| **Workout** | "Suggest a 30-minute HIIT workout" |
| **Recipes** | "Give me a healthy recipe with chicken and broccoli" |
| **Body composition** | "Sync my Tanita measurements" / "What was my body fat in March?" |
| **Activity** | "How many steps did I take this week?" / "How was my sleep last night?" |
| **Goals** | "I want to reach 75 kg in 3 months" |
| **Preferences** | "I don't like beetroot or liver" |

---

## 📋 Telegram Commands

| Command | Description |
|---|---|
| `/start` | Launch onboarding (new users) |
| `/profile` | View profile summary |
| `/edit` | Edit profile fields |
| `/preferences` | Manage food likes/dislikes, allergies, restrictions |
| `/weight <kg>` | Log current weight |
| `/history` | View weight history |
| `/reset` | Start a new conversation session |
| `/help` | List available commands |

---

## 🌐 Gradio Web UI Tabs

| Tab | Description |
|---|---|
| 🚀 **Onboarding** | New account wizard |
| 👤 **Profile** | Edit personal data and log weight |
| 🎯 **Goals** | Dashboard — KPIs, progress charts and goal tracking |
| 🏃 **Activity** | Garmin Connect dashboard (steps, calories, sleep, body battery, VO2 max) |
| 🥗 **Nutrition & Preferences** | Manage likes, dislikes, allergies and restrictions |
| 💬 **Conversation** | Chat with the agents + XAI panel |
| ⚙️ **Administration** | Explainability · Sessions · Logs · Knowledge Base |

---

<details>
<summary>🗂️ <b>Project Structure</b></summary>

```
MyHealthAssistant/
├── main.py                           # Entry point — Telegram bot + Gradio UI
├── requirements.txt
├── .env / .env.example
├── ARCHITECTURE.md                   # Flow diagrams and architecture decisions
├── scripts/
│   ├── setup.sh / setup.bat          # Dependency installation
│   ├── setup_telegram.py             # Save Telegram token encrypted (required, once)
│   ├── setup_credentials.py          # Tanita credentials
│   └── garmin_browser_auth.py        # Garmin OAuth browser flow
├── config/
│   └── __init__.py                   # Configuration constants + LLM model factory
├── agents/
│   ├── coordinator.py                # Team router (mode="route") + governance
│   ├── nutritionist.py               # Nutritionist agent
│   ├── trainer.py                    # Personal Trainer agent
│   ├── chef.py                       # Chef agent
│   ├── body_composition_analyst.py   # Body Composition Analyst agent (Tanita)
│   └── activity_analyst.py           # Activity Analyst agent (Garmin Connect)
├── interfaces/
│   ├── telegram_bot.py               # Telegram interface + onboarding flow
│   └── gradio/
│       ├── app.py                    # Entry point — Blocks layout + all event handlers
│       ├── shared.py                 # Shared utilities (agent team, session mgmt, DB helpers)
│       ├── styles.py                 # CSS styles
│       └── tabs/
│           ├── onboarding_tab.py     # 🚀 Onboarding wizard (new user creation)
│           ├── profile_tab.py        # 👤 Profile
│           ├── goals_tab.py          # 🎯 Goals dashboard
│           ├── activity_tab.py       # 🏃 Activity dashboard (Garmin — steps, sleep, VO2 max…)
│           ├── nutrition_tab.py      # 🥗 Nutrition & Preferences
│           ├── chat_tab.py           # 💬 Conversation + XAI panel
│           └── admin_tab.py          # ⚙️ Administration
├── tools/
│   ├── credential_store.py           # Encrypted credential store (Fernet/SQLite)
│   ├── tanita_tools.py               # Tanita sync via Playwright
│   ├── garmin_tools.py               # Garmin Connect API
│   ├── profile_tools.py              # Profile, weight, goals
│   ├── nutrition_tools.py            # Calories, macros, food lookup
│   └── exercise_tools.py             # Exercises, workouts, MET
├── knowledge/
│   ├── __init__.py                   # KnowledgeBase class — ChromaDB wrapper
│   └── seed_data.py                  # Initial seed data (nutrition + exercises)
├── xai/
│   └── __init__.py                   # ExplainabilityTracker + @xai_tool decorator
├── eval/
│   └── run_eval.py                   # Automated evaluation — 20 pre-defined queries
├── tests/
│   ├── conftest.py
│   ├── test_knowledge.py
│   ├── test_tools_nutrition.py
│   ├── test_tools_exercise.py
│   ├── test_tools_profile.py
│   ├── test_tools_tanita.py
│   └── test_xai.py
├── data/
│   ├── user_profiles.db              # SQLite — profiles, weight, body composition, credentials
│   ├── sessions.db                   # SQLite — conversation history (Agno)
│   ├── chromadb/                     # Vector store
│   └── garmin_tokens/                # Per-user Garmin OAuth tokens
└── logs/health-assistant.log         # Rotating log (5 MB × 3 files)
```

</details>

<details>
<summary>🗄️ <b>Data Storage</b></summary>

**SQLite `user_profiles.db`**

| Table | Contents |
|---|---|
| `user_profiles` | Personal data, activity level, goal |
| `weight_history` | Weight log |
| `body_composition_history` | Tanita measurements (11 metrics) |
| `user_credentials` | Encrypted credentials: Telegram token (`_system_`), Tanita (per user) |

**SQLite `sessions.db`** — conversation history managed by Agno. Not accessed directly by the application code.

**ChromaDB `data/chromadb/`** — three collections, all using cosine similarity with `all-MiniLM-L6-v2` embeddings:

| Collection | What is stored | How it is used |
|---|---|---|
| `user_preferences` | Food likes/dislikes, allergies, dietary restrictions, health goals | Filtered by `user_id` + `category`; semantic search for free-text preference queries |
| `nutrition_knowledge` | Foods, calories, macros, diet guidance | Semantic RAG — retrieved by the Nutritionist and Chef agents |
| `exercise_knowledge` | Exercise descriptions, muscle groups, workout plans, calorie burn estimates | Semantic RAG — retrieved by the Personal Trainer agent |

> **Goals sync:** when a goal is added or updated it is written to both ChromaDB (for semantic search) and SQLite (for the dashboard's target computation and agent context).

**`data/garmin_tokens/<user_id>/`** — Garmin OAuth tokens (JSON files, ~6 months validity).

</details>

<details>
<summary>🔍 <b>Explainability (XAI)</b></summary>

Every agent response is accompanied by a detailed XAI report available in the **Explainability** tab (Gradio):

- **Specialist activated** — which agent handled the request
- **Tools called** — function name, arguments, and result summary
- **RAG queries** — which ChromaDB collection was searched, with what query, and how many documents were retrieved
- **Formula notes** — mathematical foundations shown for caloric calculations (Mifflin-St Jeor) and calorie burn estimates (MET)

</details>

<details>
<summary>📊 <b>Tanita — Body Composition Metrics</b></summary>

The **Body Composition Analyst** agent connects to [MyTanita.eu](https://mytanita.eu) and automatically downloads scale measurements via browser automation (Playwright). No manual export needed.

| Metric | Description |
|---|---|
| `weight_kg` | Body weight (kg) |
| `bmi` | Body Mass Index |
| `body_fat_pct` | Body fat percentage |
| `visceral_fat` | Visceral fat level (1–59) |
| `muscle_mass_kg` | Skeletal muscle mass (kg) |
| `muscle_quality` | Muscle quality score |
| `bone_mass_kg` | Bone mass (kg) |
| `bmr_kcal` | Basal Metabolic Rate (kcal/day) |
| `metabolic_age` | Metabolic age (years) |
| `body_water_pct` | Body water percentage |
| `physique_rating` | Physique rating (1–9) |

**Example prompts:**
- "Sync my Tanita measurements"
- "What was my body fat on 15/03/2026?"
- "Show my visceral fat trend over the last 3 months"

</details>

<details>
<summary>🏃 <b>Garmin Connect — Available Metrics</b></summary>

The **Activity Analyst** agent retrieves training and wellness data from [Garmin Connect](https://connect.garmin.com) via the `garminconnect` library. Since Garmin's SSO rate-limits programmatic login, a **one-time browser authentication** is required per user (see step 7).

| Metric | Description |
|---|---|
| `steps` | Daily step count and goal |
| `calories_active` / `calories_total` | Active and total calories burned |
| `sleep_duration_h` / `sleep_score` | Sleep duration and quality score |
| `body_battery_start` / `body_battery_end` | Body Battery energy level |
| `resting_heart_rate` | Resting HR (bpm) |
| `vo2max` | VO2 max estimate |
| `training_streak_days` | Consecutive active days |
| Activities list | Type, duration, distance, calories, average HR |

**Example prompts:**
- "How many steps did I take this week?"
- "How was my sleep last night?"
- "Show my body battery trend over the last 2 weeks"
- "What activities did I do this month?"
- "What's my VO2 max?"

</details>

<details>
<summary>🛡️ <b>Ethics & Safety</b></summary>

The Coordinator enforces non-negotiable guardrails on every message:

- **Refuses** extreme caloric restriction (< 800 kcal/day without medical supervision)
- **Refuses** promotion of disordered eating (purging, multi-day fasting, etc.)
- **Refuses** medical diagnoses, prescriptions, or treatment of diseases
- **Refuses** dangerous supplements or unproven treatments
- **Refuses** requests outside the health domain (political, discriminatory, illegal content)
- **Recommends** certified professionals for medical conditions, pregnancy, or chronic illness
- **GDPR-aware** — only uses data explicitly provided by the user; never cross-references users

</details>

<details>
<summary>🧪 <b>Automated Evaluation</b></summary>

Evaluation suite with **20 pre-defined queries** covering routing, quality, ethics guardrails and edge cases:

```bash
python -X utf8 eval/run_eval.py                          # run all tests
python -X utf8 eval/run_eval.py --verbose                # show full agent responses
python -X utf8 eval/run_eval.py --output eval/report.json
```

</details>

<details>
<summary>🔧 <b>Design Notes</b></summary>

**Language**
All **code** (agent instructions, tool docstrings) is in **English** — English yields better results with smaller local models for routing and tool-calling decisions.
**User-facing responses** are in **European Portuguese** — the Coordinator enforces this regardless of the language the user writes in.

**Switching LLM providers**
Change `LLM_PROVIDER` in `.env` — no code changes required. The `get_model()` factory in `config/__init__.py` instantiates the correct Agno model for all agents automatically.

**Session persistence**
Agno automatically persists each session's history in `data/sessions.db`. Each user has one active session. `/reset` (Telegram) or "New Session" (Gradio) creates a new session without deleting previous history.

**Log persistence**
Logs are written in **append mode** across restarts — each run appends to `logs/health-assistant.log` with a `── new run ──` separator. Rotates at 5 MB (up to 3 backup files).

**User ID forwarding**
Every message arriving at the Coordinator is prefixed with `[Today's date: DD/MM/YYYY] [User ID: <UID>]`. The Coordinator includes the UID at the top of every task routed to a specialist, ensuring all tool calls use the correct user account regardless of routing depth.

</details>

<details>
<summary>🛠️ <b>Customisation</b></summary>

**Add initial preferences:** edit `knowledge/seed_data.py` and reset the vector store:
```bash
rm -rf data/chromadb   # macOS / Linux
python main.py
```

**Add new agents:**
1. Create a file in `agents/` following the existing pattern
2. Add it as a `member` in `coordinator.py`
3. Create tools in `tools/` decorated with `@xai_tool`

</details>

---

## 🤝 Contributing

1. Fork the repository
2. Create a branch: `git checkout -b feature/YourFeature`
3. Commit: `git commit -m "Add YourFeature"`
4. Push: `git push origin feature/YourFeature`
5. Open a Pull Request

Follow [PEP 8](https://peps.python.org/pep-0008/), add docstrings to new functions, and update this README if adding new features.

---

## 🆘 Support

- **Issues**: [github.com/brunomigueldasilva/my-health-assistant/issues](https://github.com/brunomigueldasilva/my-health-assistant/issues)
- **Email**: [bruno_m_c_silva@proton.me](mailto:bruno_m_c_silva@proton.me)

When reporting a bug, include: Python version, OS, error message and steps to reproduce.

---

[![GitHub stars](https://img.shields.io/github/stars/brunomigueldasilva/my-health-assistant?style=social)](https://github.com/brunomigueldasilva/my-health-assistant/stargazers)

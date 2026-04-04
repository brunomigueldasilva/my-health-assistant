# Architecture — MyHealthAssistant

Multi-agent personal health system built with [Agno](https://github.com/agno-agi/agno), ChromaDB, and support for 5 LLM providers.

---

## 1. Component overview

```mermaid
graph TB
    subgraph Interfaces
        TG["Telegram Bot\n(onboarding · commands · chat)"]
        GR["Gradio Web UI\n(7 tabs — Onboarding · Perfil · Objectivo\n· Actividade · Nutrição · Conversa · Admin)"]
    end

    subgraph agnoTeam["Agno Team — mode=route"]
        CO["Coordinator\n(Router + Governance)"]
        NU["Nutritionist\nAgent"]
        TR["Personal Trainer\nAgent"]
        CH["Chef\nAgent"]
        BC["Body Composition\nAnalyst Agent"]
        AA["Activity Analyst\nAgent"]
    end

    subgraph tools["Tools & Data"]
        PT["Profile Tools\n(SQLite)"]
        NT["Nutrition Tools"]
        ET["Exercise Tools"]
        TT["Tanita Tools\n(Playwright)"]
        GT["Garmin Tools\n(garminconnect)"]
        CS["Credential Store\n(Fernet/SQLite)"]
        KB["ChromaDB\n(RAG Vector Store)"]
        DB["SQLite\nuser_profiles · sessions · credentials"]
    end

    subgraph llmProviders["LLM Providers"]
        OL["Ollama\n(local)"]
        LS["LM Studio\n(local)"]
        GM["Gemini"]
        OA["OpenAI"]
        AN["Anthropic"]
    end

    TG -->|arun + session_id| CO
    GR -->|arun + session_id| CO

    CO -->|route| NU
    CO -->|route| TR
    CO -->|route| CH
    CO -->|route| BC
    CO -->|route| AA
    CO -->|direct tools| PT

    NU --> NT & PT
    TR --> ET & PT
    CH --> NT & PT
    BC --> TT & PT
    AA --> GT & PT

    NT & ET --> KB
    PT --> DB
    TT --> CS
    GT --> CS
    CS --> DB

    GR -.->|direct SQLite read| DB
    GR -.->|direct ChromaDB read| KB

    CO -.->|get_model| OL
    CO -.->|get_model| LS
    CO -.->|get_model| GM
    CO -.->|get_model| OA
    CO -.->|get_model| AN
```

---

## 2. Routing by the Coordinator

The Coordinator uses Agno's `mode="route"`: it analyses the message, selects **one** specialist, and passes the full context to it.

```mermaid
flowchart TD
    MSG["Mensagem do utilizador\n+ prefixo [Data: DD/MM/AAAA] [ID: uid]"]
    CO{"Coordinator\nanalisa intenção"}

    MSG --> CO

    CO -->|"food · calories · macros\nmeal plan · diet"| NU["Nutricionista"]
    CO -->|"exercise · workout\nHIIT · strength · cardio"| TR["Personal Trainer"]
    CO -->|"recipe · meal idea\nbreakfast · dinner"| CH["Chef"]
    CO -->|"Tanita · body fat\nvisceral fat · muscle mass\nBMI · metabolic age"| BC["Analista Composição Corporal"]
    CO -->|"Garmin · steps · sleep\nbody battery · activities\nVO2 max · heart rate"| AA["Analista de Actividade"]
    CO -->|"profile · preferences\ngoals · delete data"| TOOLS["Profile Tools\n(resposta directa)"]

    NU & TR & CH & BC & TOOLS --> RESP["Resposta em\nPortuguês de Portugal"]

    style CO fill:#059669,color:#fff
    style RESP fill:#0284c7,color:#fff
```

**Governance rules enforced by the Coordinator before routing:**
- Refuses extreme caloric restrictions (`< 800 kcal/day`)
- Refuses medical diagnoses or prescriptions
- Refuses requests outside the health domain
- Injects previous message context into follow-ups
- **Forwards user ID:** every routed task begins with `[Data de hoje: DD/MM/AAAA] [ID do utilizador: <UID>]` so specialists always call tools with the correct user account

---

## 3. RAG query (ChromaDB)

Each specialist agent queries the vector knowledge base before responding.

```mermaid
sequenceDiagram
    participant A as Specialist Agent
    participant T as Tool (@xai_tool)
    participant C as ChromaDB
    participant XAI as XAI Tracker

    A->>T: search_food_nutrition("proteína frango")
    T->>C: collection.query(query_texts=[...], n_results=5)
    C-->>T: top-5 documents by cosine similarity
    T->>XAI: log_rag(collection, query, hits)
    T-->>A: JSON with relevant results

    Note over C: 3 collections:<br/>nutrition_knowledge<br/>exercise_knowledge<br/>user_preferences
    Note over XAI: Visible in the<br/>Explainability tab (Gradio)
```

**ChromaDB collections:**

| Collection | Content | Filter |
|---|---|---|
| `nutrition_knowledge` | Foods, macros, diets, supplements | `type = "nutrition"` |
| `exercise_knowledge` | Exercises, muscle groups, plans | `type = "exercise"` |
| `user_preferences` | Preferences, allergies, restrictions, goals | `user_id + category` |

---

## 4. Sequence diagram — typical conversation

```mermaid
sequenceDiagram
    actor U as Utilizador
    participant I as Interface\n(Telegram / Gradio)
    participant CO as Coordinator
    participant NU as Nutricionista
    participant PT as Profile Tools
    participant NT as Nutrition Tools
    participant KB as ChromaDB

    U->>I: "Quero um plano alimentar para perder peso"
    I->>I: Injeta [Data: DD/MM/YYYY] [ID: user_123]
    I->>CO: team.arun(enriched_message, session_id)

    CO->>CO: Analisa intenção → "meal plan · weight loss"
    CO->>NU: Roteia com contexto completo + [ID: user_123]

    NU->>PT: get_user_profile(user_id)
    PT-->>NU: {peso: 80kg, altura: 175cm, objectivo: perder peso}

    NU->>PT: search_user_food_preferences(user_id)
    PT->>KB: user_preferences.query(user_id)
    KB-->>PT: {dislikes: ["fígado"], allergies: ["glúten"]}
    PT-->>NU: preferências do utilizador

    NU->>NT: calculate_daily_calories(user_id, peso, altura, idade, actividade, objectivo)
    NT-->>NU: {bmr: 1820 kcal, tdee: 2821 kcal, meta: 2421 kcal}

    NU->>NT: search_food_nutrition("refeições défice calórico")
    NT->>KB: nutrition_knowledge.query(...)
    KB-->>NT: documentos relevantes
    NT-->>NU: sugestões nutricionais

    NU-->>CO: Plano alimentar semanal (Markdown)
    CO-->>I: Resposta final
    I-->>U: Plano apresentado na interface
```

---

## 5. Data persistence

```mermaid
graph LR
    subgraph sqliteProfiles["SQLite — user_profiles.db"]
        UP["user_profiles\nuser_id · nome · idade · peso · objectivo"]
        WH["weight_history\nuser_id · peso_kg · data"]
        BC["body_composition_history\nuser_id · gordura · músculo · IMC · ..."]
    end

    subgraph sqliteSessions["SQLite — sessions.db"]
        SS["sessions\nsession_id · messages · timestamps"]
    end

    subgraph chromadb["ChromaDB — data/chromadb/"]
        NK["nutrition_knowledge"]
        EK["exercise_knowledge"]
        UP2["user_preferences\n(goals · allergies · likes · dislikes)"]
    end

    PT["Profile Tools"] --> UP & WH
    PT --> UP2
    TT["Tanita Tools"] --> BC
    AG["Agno Framework"] --> SS
    NT["Nutrition Tools"] --> NK
    ET["Exercise Tools"] --> EK

    GR["Gradio Dashboard"] -.->|read KPIs + charts| UP & WH & BC
    GR -.->|read goals for target inference| UP2
```

**Goals sync:** when a goal is saved via Telegram or Gradio it is written to both ChromaDB (`user_preferences`, category `goals`) and to the `goal` column in `user_profiles`. This ensures agents have full context via RAG and the Objectivo dashboard can compute personalised numeric targets without an LLM call.

---

## 6. Objectivo Dashboard (Gradio)

The **🎯 Objectivo** tab provides a real-time health progress view by reading directly from SQLite and ChromaDB — no agent call required.

```mermaid
flowchart TD
    UID["User ID"]

    UID --> KPI["load_dashboard_kpis()\nLatest body fat · visceral fat\nmuscle mass · weight"]
    UID --> TGT["_compute_targets()\nParse goal text → numeric targets\n(regex + BMI/lean-mass fallback)"]
    UID --> CHARTS["load_dashboard_charts()\n4 time-series charts\n(fat % · visceral · weight · muscle)"]
    UID --> PROG["load_dashboard_progress()\nNatural-language progress summary\nvs. computed targets"]

    KPI & TGT --> DISPLAY["Dashboard HTML\nKPI cards + progress bars\n+ 4 interactive charts"]
    CHARTS --> DISPLAY
    PROG --> DISPLAY

    style DISPLAY fill:#0284c7,color:#fff
```

**Target inference logic (`_compute_targets`):**
1. Read all goals from ChromaDB (`user_preferences`, category `goals`) — supports users with multiple simultaneous goals
2. Extract numeric targets via regex patterns (weight kg, fat %, visceral level)
3. Infer missing targets from defined ones using the user's current muscle-to-lean-mass ratio
4. BMI formula fallback for weight if no explicit target is found

---

## 7. Onboarding wizard flow (Gradio)

The **🚀 Onboarding** tab guides new users through account creation without any manual typing beyond free-text fields. It is displayed automatically when no user account is selected and hidden after completion.

```mermaid
flowchart TD
    START["Sidebar — ➕ Criar nova conta\nOR first load with no UID"]
    START --> S1["Step 1 — Create account\nName (required) · custom ID (optional, else auto UUID)"]
    S1 -->|onb_create_user| S2["Step 2 — Personal data\nGender · Birth date · Height · Weight"]
    S2 -->|onb_step2_next| S3["Step 3 — Activity level\n(5 options)"]
    S3 -->|onb_step3_next| S4["Step 4 — Health goals\n(multi-select, up to 3)\n+ numeric targets if applicable"]
    S4 -->|onb_step4_next| S5["Step 5 — Allergies & intolerances\n(multi-select toggles)"]
    S5 -->|onb_finish| DONE["Done — Profile summary\n+ success message"]
    DONE -->|go_to_chat_btn| PROFILE["Navigate to Perfil tab\nOnboarding tab hidden"]

    S2 --> S1
    S3 --> S2
    S4 --> S3
    S5 --> S4

    style DONE fill:#059669,color:#fff
    style PROFILE fill:#0284c7,color:#fff
```

**Account deletion flow (sidebar):**
```
🗑️ Remover Conta → confirmation group visible
  ├─ Confirmar → delete_user_fn → delete_all_user_data(uid) → reload sidebar + tabs
  └─ Cancelar  → confirmation group hidden
```

---

## 8. Credential store & Garmin authentication

Per-user credentials (Tanita and Garmin) are **never stored in `.env`**. They are encrypted with Fernet (AES-128-CBC + HMAC) and kept in the `user_credentials` table in `user_profiles.db`.

```mermaid
flowchart LR
    SCRIPT["scripts/setup_credentials.py\n(interactive CLI)"]
    STORE["tools/credential_store.py\nset_credential / get_credential"]
    DB["SQLite\nuser_credentials\n(username_enc · password_enc)"]
    KEY["SECRET_KEY (.env)\nFernet master key"]

    SCRIPT -->|set_credential| STORE
    STORE -->|encrypt + INSERT| DB
    STORE <-->|decrypt on read| KEY
```

**Garmin OAuth browser flow** (`scripts/garmin_browser_auth.py`):

Garmin blocks programmatic SSO login with 429 rate-limits. The browser script uses Playwright (Chromium) to complete the login interactively, exchanges the resulting SSO ticket for garth-compatible OAuth1 + OAuth2 tokens, and saves them to `data/garmin_tokens/<user_id>/`. The `garmin_tools.py` module resumes the session from this token cache — no password is stored after the flow.

```
scripts/garmin_browser_auth.py --user <uid>
  └─ Playwright opens Chromium
       └─ User logs in at connect.garmin.com
            └─ SSO ticket → OAuth1 + OAuth2 exchange
                 └─ Tokens saved to data/garmin_tokens/<uid>/
                      └─ garmin_tools.py loads tokens on first call
                           └─ Garmin session cached in memory for the run
```

---

## 9. Architecture decisions

| Decision | Choice | Rationale |
|---|---|---|
| Agent framework | Agno | Native `mode="route"`, SQLite session management, automatic tool calling |
| Vector store | ChromaDB | Local persistence, no external server, default embedding sufficient for this domain |
| Database | SQLite | Zero configuration, WAL mode for Gradio/Telegram concurrency |
| LLM | Configurable (5 providers) | Avoids vendor lock-in; allows local execution (privacy) or cloud (performance) |
| Interfaces | Telegram + Gradio | Telegram for mobile/daily use; Gradio for demo, dashboard and administration |
| Onboarding (Gradio) | Dedicated wizard tab | Shown only when no account is selected; hides itself after completion and navigates to Profile |
| Account management | Sidebar buttons | "➕ Criar nova conta" → Onboarding wizard; "🗑️ Remover Conta" → confirmed deletion via `delete_all_user_data` |
| Telegram commands | English names | Commands renamed (`/profile`, `/edit`, `/preferences`, `/weight`, `/history`) for broader accessibility |
| Tanita automation | Playwright | MyTanita portal has no public API; controlled scraping encapsulated in a tool |
| Garmin auth | Browser OAuth (Playwright) | Garmin SSO rate-limits programmatic login (HTTP 429); one-time browser flow issues long-lived tokens |
| Credential storage | Fernet-encrypted SQLite | Per-user secrets never in `.env`; encrypted at rest with a single master key; reuses existing DB |
| Setup scripts | `scripts/` directory | Keeps root clean; scripts use `cd ..` so they work from either the root or the `scripts/` folder |
| Output language | European Portuguese | Target audience; enforced in the Coordinator's system prompt |
| Dashboard reads | Direct SQLite/ChromaDB | Avoids LLM latency for purely data-driven views; keeps agent calls for natural-language tasks |
| Goals storage | ChromaDB + SQLite sync | ChromaDB for semantic agent queries; SQLite for fast dashboard target inference |
| User ID forwarding | Coordinator instruction | Guarantees all specialist tool calls use the correct account regardless of routing depth |

# Architecture — MyHealthAssistant

Multi-agent personal health system built with [Agno](https://github.com/agno-agi/agno), ChromaDB, and support for 5 LLM providers.

---

## 1. Component overview

```mermaid
graph TB
    subgraph Interfaces
        TG["Telegram Bot\n(onboarding · commands · chat)"]
        GR["Gradio Web UI\n(5 tabs — incl. Objectivo dashboard)"]
    end

    subgraph agnoTeam["Agno Team — mode=route"]
        CO["Coordinator\n(Router + Governance)"]
        NU["Nutritionist\nAgent"]
        TR["Personal Trainer\nAgent"]
        CH["Chef\nAgent"]
        BC["Body Composition\nAnalyst Agent"]
    end

    subgraph tools["Tools & Data"]
        PT["Profile Tools\n(SQLite)"]
        NT["Nutrition Tools"]
        ET["Exercise Tools"]
        TT["Tanita Tools\n(Playwright)"]
        KB["ChromaDB\n(RAG Vector Store)"]
        DB["SQLite\nuser_profiles · sessions"]
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
    CO -->|direct tools| PT

    NU --> NT & PT
    TR --> ET & PT
    CH --> NT & PT
    BC --> TT & PT

    NT & ET --> KB
    PT --> DB

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

## 7. Architecture decisions

| Decision | Choice | Rationale |
|---|---|---|
| Agent framework | Agno | Native `mode="route"`, SQLite session management, automatic tool calling |
| Vector store | ChromaDB | Local persistence, no external server, default embedding sufficient for this domain |
| Database | SQLite | Zero configuration, WAL mode for Gradio/Telegram concurrency |
| LLM | Configurable (5 providers) | Avoids vendor lock-in; allows local execution (privacy) or cloud (performance) |
| Interfaces | Telegram + Gradio | Telegram for mobile/daily use; Gradio for demo, dashboard and administration |
| Tanita automation | Playwright | MyTanita portal has no public API; controlled scraping encapsulated in a tool |
| Output language | European Portuguese | Target audience; enforced in the Coordinator's system prompt |
| Dashboard reads | Direct SQLite/ChromaDB | Avoids LLM latency for purely data-driven views; keeps agent calls for natural-language tasks |
| Goals storage | ChromaDB + SQLite sync | ChromaDB for semantic agent queries; SQLite for fast dashboard target inference |
| User ID forwarding | Coordinator instruction | Guarantees all specialist tool calls use the correct account regardless of routing depth |

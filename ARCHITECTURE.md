# Architecture — MyHealthAssistant

Multi-agent personal health system built with [Agno](https://github.com/agno-agi/agno), ChromaDB, and support for 5 LLM providers.

---

## 1. Component overview

```mermaid
graph TB
    subgraph Interfaces
        TG["Telegram Bot"]
        GR["Gradio Web UI"]
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
    MSG["Mensagem do utilizador\n+ prefixo [data] [user_id]"]
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
    CO->>NU: Roteia com contexto completo

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
        UP2["user_preferences"]
    end

    PT["Profile Tools"] --> UP & WH
    TT["Tanita Tools"] --> BC
    AG["Agno Framework"] --> SS
    NT["Nutrition Tools"] --> NK
    ET["Exercise Tools"] --> EK
    PT2["Profile Tools"] --> UP2
```

---

## 6. Architecture decisions

| Decision | Choice | Rationale |
|---|---|---|
| Agent framework | Agno | Native `mode="route"`, SQLite session management, automatic tool calling |
| Vector store | ChromaDB | Local persistence, no external server, default embedding sufficient for this domain |
| Database | SQLite | Zero configuration, WAL mode for Gradio/Telegram concurrency |
| LLM | Configurable (5 providers) | Avoids vendor lock-in; allows local execution (privacy) or cloud (performance) |
| Interfaces | Telegram + Gradio | Telegram for mobile/daily use; Gradio for demo and administration |
| Tanita automation | Playwright | MyTanita portal has no public API; controlled scraping encapsulated in a tool |
| Output language | European Portuguese | Target audience; enforced in the Coordinator's system prompt |

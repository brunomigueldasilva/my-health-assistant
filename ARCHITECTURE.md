# Arquitectura — MyHealthAssistant

Sistema multi-agente de saúde pessoal construído com [Agno](https://github.com/agno-agi/agno), ChromaDB e suporte a 5 LLM providers.

---

## 1. Visão geral dos componentes

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

    subgraph Ferramentas & Dados
        PT["Profile Tools\n(SQLite)"]
        NT["Nutrition Tools"]
        ET["Exercise Tools"]
        TT["Tanita Tools\n(Playwright)"]
        KB["ChromaDB\n(RAG Vector Store)"]
        DB["SQLite\nuser_profiles · sessions"]
    end

    subgraph LLM Providers
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

    CO -.->|get_model()| OL & LS & GM & OA & AN
```

---

## 2. Routing pelo Coordinator

O Coordinator usa `mode="route"` do Agno: analisa a mensagem, selecciona **um** especialista e passa-lhe o contexto completo.

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

**Regras de governance aplicadas pelo Coordinator antes de rotear:**
- Recusa restrições calóricas extremas (`< 800 kcal/dia`)
- Recusa diagnósticos médicos ou prescrições
- Recusa pedidos fora do âmbito de saúde
- Injeta contexto de mensagens anteriores em follow-ups

---

## 3. Consulta RAG (ChromaDB)

Cada agente especialista consulta a base de conhecimento vectorial antes de responder.

```mermaid
sequenceDiagram
    participant A as Agente Especialista
    participant T as Tool (@xai_tool)
    participant C as ChromaDB
    participant XAI as XAI Tracker

    A->>T: search_food_nutrition("proteína frango")
    T->>C: collection.query(query_texts=[...], n_results=5)
    C-->>T: top-5 documentos por cosine similarity
    T->>XAI: log_rag(collection, query, hits)
    T-->>A: JSON com resultados relevantes

    Note over C: 3 colecções:<br/>nutrition_knowledge<br/>exercise_knowledge<br/>user_preferences
    Note over XAI: Registo visível no<br/>tab Explicabilidade (Gradio)
```

**Colecções ChromaDB:**

| Colecção | Conteúdo | Filtro |
|---|---|---|
| `nutrition_knowledge` | Alimentos, macros, dietas, suplementos | `type = "nutrition"` |
| `exercise_knowledge` | Exercícios, grupos musculares, planos | `type = "exercise"` |
| `user_preferences` | Gostos, alergias, restrições, objectivos | `user_id + category` |

---

## 4. Diagrama de sequência — conversa típica

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

## 5. Persistência de dados

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

## 6. Decisões de arquitectura

| Decisão | Escolha | Justificação |
|---|---|---|
| Framework de agentes | Agno | `mode="route"` nativo, session management com SQLite, tool calling automático |
| Vector store | ChromaDB | Persistência local, sem servidor externo, embedding por defeito suficiente para este domínio |
| Base de dados | SQLite | Zero configuração, WAL mode para concorrência Gradio/Telegram |
| LLM | Configurável (5 providers) | Evita vendor lock-in; permite execução local (privacidade) ou cloud (desempenho) |
| Interfaces | Telegram + Gradio | Telegram para uso móvel/quotidiano; Gradio para demo e administração |
| Automação Tanita | Playwright | Portal MyTanita não tem API pública; scraping controlado e encapsulado numa tool |
| Linguagem de output | Português de Portugal | Público-alvo; enforced no system prompt do Coordinator |

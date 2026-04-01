"""CSS styles for the Gradio interface."""

CSS = """
/* Food preference lists — one item per line */
.vertical-list .wrap {
    flex-direction: column !important;
    gap: 2px !important;
}
.vertical-list .wrap label {
    width: 100% !important;
    padding: 5px 10px !important;
    border-radius: 6px !important;
    margin: 0 !important;
    transition: background 0.15s;
}
.vertical-list .wrap label:hover {
    background: rgba(255,255,255,0.06) !important;
}

/* Dashboard Cards */
.health-card {
    transition: transform 0.2s;
}
.health-card:hover {
    transform: translateY(-2px);
}

/* Compact weight registration row */
.weight-row {
    max-width: 420px !important;
    align-items: center !important;
}
"""

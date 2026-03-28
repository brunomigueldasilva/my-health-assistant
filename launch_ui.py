import gradio as gr
from interfaces.gradio_app import demo as gradio_demo, _CSS as gradio_css

if __name__ == "__main__":
    gradio_demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        theme=gr.themes.Soft(primary_hue="emerald", secondary_hue="teal"),
        css=gradio_css,
    )

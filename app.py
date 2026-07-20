import streamlit as st

# 1. Configuración de la interfaz (Estilo moderno y expandido)
st.set_page_config(
    page_title="KiroDocs ☁️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Estilo personalizado rápido para darle un toque "Premium/Dark"
st.markdown("""
    <style>
    .main { background-color: #0f172a; color: #f8fafc; }
    h1 { color: #38bdf8 !important; }
    div.stButton > button:first-child {
        background-color: #0284c7;
        color: white;
        border-radius: 8px;
        border: none;
        padding: 10px 24px;
    }
    div.stButton > button:first-child:hover {
        background-color: #0369a1;
    }
    </style>
""", unsafe_allow_html=True)

# 2. Encabezado principal de la aplicación
st.title("☁️ KiroDocs")
st.subheader("Generador Inteligente de Arquitecturas de AWS con Kiro")
st.write("Crea diagramas interactivos y documentación en segundos gracias a la IA.")

st.write("---")

# 3. Distribución de la pantalla en dos columnas
col_izq, col_der = st.columns([1, 1])

with col_izq:
    st.write("### 📝 ¿Qué infraestructura necesitas?")
    # Entrada de texto del usuario
    prompt_usuario = st.text_area(
        label="Describe tu arquitectura de AWS:",
        placeholder="Ej: Necesito una arquitectura web serverless con una API Gateway, una Lambda y una DynamoDB...",
        height=150
    )
    
    boton_generar = st.button("Generar Solución ⚡")

with col_der:
    st.write("### 📊 Resultado e Infraestructura")
    
    if boton_generar and prompt_usuario:
        # Simulamos la carga para darle un efecto visual hermoso
        with st.spinner("Kiro e IA procesando la solicitud... 🤖"):
            
            # --- RESPUESTA SIMULADA (MOCKUP) PARA NO CONSUMIR TU CUOTA ---
            # Aquí definimos un diagrama rápido en formato Mermaid.js
            diagrama_ejemplo = """
            graph TD
                Usuario[Usuario Web] -->|HTTP Request| API[API Gateway]
                API -->|Trigger| Lambda[AWS Lambda]
                Lambda -->|CRUD| DB[(DynamoDB)]
                
                style API fill:#ff9900,stroke:#333,stroke-width:2px,color:#fff
                style Lambda fill:#ff9900,stroke:#333,stroke-width:2px,color:#fff
                style DB fill:#3f51b5,stroke:#333,stroke-width:2px,color:#fff
            """
            
            # Pestañas para organizar la información "linda"
            tab_diagrama, tab_docs, tab_codigo = st.tabs(["📊 Diagrama", "📄 Documentación (README)", "⚙️ Terraform"])
            
            with tab_diagrama:
                st.write("#### Diagrama de Arquitectura")
                # Renderiza el diagrama de manera interactiva
                st.mermaid(diagrama_ejemplo)
                
            with tab_docs:
                st.write("#### Documentación Técnica Generada")
                st.markdown("""
                ### Arquitectura Serverless Básica
                Este proyecto despliega una API REST serverless utilizando los servicios gestionados de AWS.
                * **API Gateway**: Expone los endpoints HTTP.
                * **AWS Lambda**: Ejecuta la lógica de cómputo de manera escalable.
                * **Amazon DynamoDB**: Almacenamiento de datos NoSQL clave-valor.
                """)
                
            with tab_codigo:
                st.write("#### Código de Infraestructura (IaC)")
                st.code("""
resource "aws_dynamodb_table" "basic-dynamodb-table" {
  name           = "GameScores"
  billing_mode   = "PAY_PER_REQUEST"
  hash_key       = "UserId"
  # ... (resto del código Terraform)
}
                """, language="terraform")
    else:
        st.info("💡 Escribe tu requerimiento en el panel izquierdo y haz clic en 'Generar Solución' para ver cómo se dibuja tu arquitectura.")
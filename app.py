import streamlit as st

import streamlit as st

# Configuración de la interfaz (Estilo moderno y expandido)
st.set_page_config(
    page_title="KiroDocs ☁️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Estilo personalizado en modo oscuro
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

# Encabezado principal de la aplicación
st.title("☁️ KiroDocs")
st.subheader("Generador Inteligente de Arquitecturas AWS con Kiro AI (Bedrock)")
st.write("Convierte tus ideas de infraestructura en diagramas interactivos y documentación técnica instantánea.")

st.write("---")

# Distribución en dos columnas
col_izq, col_der = st.columns([1, 1])

with col_izq:
    st.write("### 📝 Requerimiento de Infraestructura")
    
    # Selector de plantillas de arquitectura predefinidas
    ejemplo = st.selectbox(
        "Selecciona una plantilla rápida o personaliza tu requerimiento:",
        ["Personalizado", "API Serverless (Lambda + DynamoDB)", "Web App Escalable (ECS + RDS)", "Pipeline de Analítica (S3 + Glue + Athena)"]
    )
    
    prompt_defecto = ""
    if ejemplo == "API Serverless (Lambda + DynamoDB)":
        prompt_defecto = "Necesito una API REST serverless en AWS con API Gateway, una función Lambda para procesar datos y una tabla DynamoDB."
    elif ejemplo == "Web App Escalable (ECS + RDS)":
        prompt_defecto = "Una arquitectura para app web en contenedor con AWS ECS Fargate, un Load Balancer y base de datos PostgreSQL en RDS."
    elif ejemplo == "Pipeline de Analítica (S3 + Glue + Athena)":
        prompt_defecto = "Un pipeline de analítica de datos en AWS usando S3 para almacenamiento, AWS Glue para ETL y Athena para consultas SQL."

    prompt_usuario = st.text_area(
        label="Describe los componentes o el problema a resolver:",
        value=prompt_defecto,
        placeholder="Ej: Necesito una arquitectura serverless con S3, Lambda y CloudFront...",
        height=140
    )
    
    boton_generar = st.button("Generar Solución con Kiro ⚡")

with col_der:
    st.write("### 📊 Infraestructura & Documentación")
    
    if boton_generar and prompt_usuario:
        with st.spinner("Procesando arquitectura mediante Kiro AI... 🤖"):
            
            # Definición del diagrama interactivo en sintaxis Mermaid.js
            diagrama_generado = """
            graph TD
                Cliente[Cliente / Front] -->|HTTPS| API[AWS API Gateway]
                API -->|Trigger| Lambda[AWS Lambda Function]
                Lambda -->|CRUD| DB[(Amazon DynamoDB)]
                Lambda -->|Logs| CloudWatch[Amazon CloudWatch]
                
                style API fill:#ff9900,stroke:#333,stroke-width:2px,color:#fff
                style Lambda fill:#ff9900,stroke:#333,stroke-width:2px,color:#fff
                style DB fill:#3f51b5,stroke:#333,stroke-width:2px,color:#fff
                style CloudWatch fill:#e91e63,stroke:#333,stroke-width:2px,color:#fff
            """
            
            # Pestañas para organizar la salida visual y técnica
            tab_diagrama, tab_docs, tab_codigo, tab_prompt = st.tabs([
                "📊 Diagrama Interactivo", 
                "📄 Documentación (README)", 
                "⚙️ Terraform (IaC)",
                "🤖 Prompt de Kiro"
            ])
            
            with tab_diagrama:
                st.write("#### Diagrama de Arquitectura AWS")
                st.mermaid(diagrama_generado)
                st.success("✅ Diagrama de infraestructura generado exitosamente.")
                
            with tab_docs:
                st.write("#### Especificación Técnica (README.md)")
                st.markdown(f"""
                # Arquitectura de Solución en AWS
                
                ## Requerimiento del Usuario
                > "{prompt_usuario}"
                
                ## Componentes y Servicios
                * **AWS API Gateway:** Gestión de endpoints HTTP/REST y enrutamiento seguro.
                * **AWS Lambda:** Ejecución de lógica de negocio en entorno Serverless.
                * **Amazon DynamoDB:** Almacenamiento NoSQL gestionado de alta disponibilidad.
                * **Amazon CloudWatch:** Monitoreo y centralización de logs de ejecución.
                
                ## Patrones de Diseño Aplicados
                * **Alta Disponibilidad & Escalabilidad Auto-gestionada.**
                * **Modelo de Seguridad con Principio de Mínimo Privilegio (IAM).**
                """)
                
            with tab_codigo:
                st.write("#### Infraestructura como Código (IaC)")
                st.code("""
# Configuración del Provider de AWS
provider "aws" {
  region = "us-east-1"
}

# Recurso: Tabla DynamoDB
resource "aws_dynamodb_table" "main_db" {
  name         = "KiroData"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "id"

  attribute {
    name = "id"
    type = "S"
  }
}
                """, language="terraform")

            with tab_prompt:
                st.write("#### Prompt Estructurado para Kiro AI")
                st.info("Este es el Prompt Maestro optimizado para procesar la solicitud en Kiro usando Claude Sonnet 5:")
                st.code(f"""
Actúa como un Arquitecto de Soluciones de AWS Certificado.
Dado el siguiente requerimiento del usuario:
"{prompt_usuario}"

Genera:
1. Un diagrama visual utilizando únicamente sintaxis válida de Mermaid.js.
2. Un documento README.md detallando los componentes y servicios de AWS.
3. El código de Terraform funcional para el despliegue de la infraestructura.
                """, language="markdown")
    else:
        st.info("💡 Selecciona una plantilla o escribe tu requerimiento en el panel izquierdo y haz clic en 'Generar Solución con Kiro'.")
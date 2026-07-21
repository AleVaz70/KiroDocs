"""
KiroDocs v1.0 - Generador Inteligente de Arquitecturas AWS
Hackathon IA Masivo Online AWS

Usa Amazon Bedrock (Claude Sonnet 5) mediante la Converse API con "tool use"
forzado para garantizar una salida estructurada y consistente: diagrama
Mermaid.js, documentación README y código Terraform.
"""

import textwrap

import boto3
import streamlit as st
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    EndpointConnectionError,
    NoCredentialsError,
)

# ---------------------------------------------------------------------------
# Configuración de la interfaz
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="KiroDocs ☁️",
    page_icon="☁️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Estilo personalizado en modo oscuro
st.markdown(
    """
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
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Configuración de modelos y plantillas
# ---------------------------------------------------------------------------
MODELOS_DISPONIBLES = {
    "Amazon Nova Lite (⚡ Instantáneo / Recomendado)": "amazon.nova-lite-v1:0",
    "Amazon Nova Pro": "amazon.nova-pro-v1:0",
    "Claude 3.5 Sonnet (Directo)": "anthropic.claude-3-5-sonnet-20240620-v1:0",
    "Claude 3 Haiku (Rápido)": "anthropic.claude-3-haiku-20240307-v1:0"
}

REGIONES_DISPONIBLES = ["us-east-1", "us-west-2", "eu-west-1", "ap-southeast-1"]

PLANTILLAS = {
    "Personalizado": "",
    "API Serverless (Lambda + DynamoDB)": (
        "Necesito una API REST serverless en AWS con API Gateway, una función "
        "Lambda para procesar datos y una tabla DynamoDB."
    ),
    "Web App Escalable (ECS + RDS)": (
        "Una arquitectura para app web en contenedor con AWS ECS Fargate, un "
        "Load Balancer y base de datos PostgreSQL en RDS."
    ),
    "Pipeline de Analítica (S3 + Glue + Athena)": (
        "Un pipeline de analítica de datos en AWS usando S3 para almacenamiento, "
        "AWS Glue para ETL y Athena para consultas SQL."
    ),
}

MAX_CARACTERES_PROMPT = 2000

# ---------------------------------------------------------------------------
# Definición de la herramienta (tool use) para forzar salida estructurada
# ---------------------------------------------------------------------------
TOOL_NAME = "generar_documentacion_arquitectura"

TOOL_SPEC = {
    "toolSpec": {
        "name": TOOL_NAME,
        "description": (
            "Entrega la propuesta completa de arquitectura AWS: resumen "
            "ejecutivo, diagrama Mermaid.js, lista de servicios, README en "
            "Markdown, código Terraform y consideraciones de seguridad."
        ),
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {
                    "resumen_ejecutivo": {
                        "type": "string",
                        "description": (
                            "Resumen breve (3-5 líneas) de la solución propuesta "
                            "y de cualquier decisión de arquitecto tomada ante "
                            "ambigüedad del requerimiento."
                        ),
                    },
                    "diagrama_mermaid": {
                        "type": "string",
                        "description": (
                            "Diagrama en sintaxis válida de Mermaid.js (graph TD "
                            "o graph LR), sin bloques ``` y sin tildes ni "
                            "espacios en los IDs de los nodos."
                        ),
                    },
                    "servicios_aws": {
                        "type": "array",
                        "description": "Lista de servicios de AWS utilizados.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "nombre": {"type": "string"},
                                "descripcion": {"type": "string"},
                            },
                            "required": ["nombre", "descripcion"],
                        },
                    },
                    "readme_markdown": {
                        "type": "string",
                        "description": (
                            "Documentación técnica completa en formato Markdown "
                            "válido (sin indentación artificial en los párrafos)."
                        ),
                    },
                    "terraform_code": {
                        "type": "string",
                        "description": (
                            "Código Terraform funcional (provider aws ~> 5.0) "
                            "para desplegar la infraestructura propuesta."
                        ),
                    },
                    "consideraciones_seguridad": {
                        "type": "array",
                        "description": (
                            "Lista de buenas prácticas de seguridad aplicadas "
                            "(IAM, cifrado, redes, etc.)."
                        ),
                        "items": {"type": "string"},
                    },
                },
                "required": [
                    "resumen_ejecutivo",
                    "diagrama_mermaid",
                    "servicios_aws",
                    "readme_markdown",
                    "terraform_code",
                    "consideraciones_seguridad",
                ],
            }
        },
    }
}

SYSTEM_PROMPT = textwrap.dedent(
    """
    Actúas como un Arquitecto de Soluciones de AWS certificado (nivel
    Professional), especializado en diseñar arquitecturas seguras, escalables
    y alineadas al AWS Well-Architected Framework.

    Reglas estrictas de salida:
    - SIEMPRE debes responder ÚNICAMENTE invocando la herramienta
      "generar_documentacion_arquitectura" con TODOS los campos completos.
      No respondas con texto libre fuera de la herramienta.
    - El diagrama debe usar sintaxis 100% válida de Mermaid.js, sin bloques de
      código Markdown (sin ```), y usando IDs de nodo sin espacios ni tildes.
    - El código Terraform debe ser funcional, usar el provider "aws" (~> 5.0),
      incluir nombres de recursos descriptivos, variables cuando aplique y
      etiquetas (tags) básicas.
    - El README debe estar en formato Markdown válido, con encabezados,
      listas y bloques de código correctamente delimitados, sin indentación
      artificial que rompa el renderizado.
    - Prioriza siempre buenas prácticas de seguridad (IAM de mínimo
      privilegio, cifrado en reposo y en tránsito, segmentación de red) y alta
      disponibilidad.
    - Si el requerimiento del usuario es ambiguo, toma decisiones de
      arquitecto senior razonables y documenta esas decisiones en
      'resumen_ejecutivo'.
    """
).strip()


def construir_prompt_usuario(descripcion: str) -> str:
    return textwrap.dedent(
        f"""
        Requerimiento de infraestructura del cliente:
        "{descripcion}"

        Genera la propuesta de arquitectura AWS completa siguiendo las reglas
        del sistema, usando obligatoriamente la herramienta disponible.
        """
    ).strip()


@st.cache_resource(show_spinner=False)
def obtener_cliente_bedrock(region: str):
    return boto3.client("bedrock-runtime", region_name=region)


def generar_arquitectura(
    descripcion: str,
    model_id: str,
    region: str,
    temperatura: float,
    max_tokens: int,
) -> dict:
    """Invoca Amazon Bedrock (Converse API) y devuelve el JSON estructurado."""
    cliente = obtener_cliente_bedrock(region)

    respuesta = cliente.converse(
        modelId=model_id,
        system=[{"text": SYSTEM_PROMPT}],
        messages=[
            {
                "role": "user",
                "content": [{"text": construir_prompt_usuario(descripcion)}],
            }
        ],
        toolConfig={
            "tools": [TOOL_SPEC],
            "toolChoice": {"tool": {"name": TOOL_NAME}},
        },
        inferenceConfig={"temperature": temperatura, "maxTokens": max_tokens},
    )

    bloques_contenido = respuesta["output"]["message"]["content"]
    for bloque in bloques_contenido:
        if "toolUse" in bloque and bloque["toolUse"]["name"] == TOOL_NAME:
            return bloque["toolUse"]["input"]

    raise ValueError(
        "El modelo no devolvió una respuesta estructurada válida. "
        "Intenta reformular el requerimiento."
    )


# ---------------------------------------------------------------------------
# Barra lateral: configuración de Bedrock
# ---------------------------------------------------------------------------
with st.sidebar:
    st.write("### ⚙️ Configuración de Bedrock")
    modelo_seleccionado = st.selectbox(
        "Modelo de Amazon Bedrock",
        options=list(MODELOS_DISPONIBLES.keys()),
        index=0,
    )
    region_seleccionada = st.selectbox(
        "Región de AWS", options=REGIONES_DISPONIBLES, index=0
    )
    with st.expander("Parámetros avanzados"):
        temperatura = st.slider("Temperatura", 0.0, 1.0, 0.4, 0.1)
        max_tokens = st.slider("Máximo de tokens de salida", 512, 8192, 4096, 512)
    st.caption(
        "Requiere credenciales de AWS válidas (variables de entorno, perfil "
        "de AWS CLI o rol de IAM) con permiso `bedrock:InvokeModel` sobre el "
        "modelo seleccionado."
    )

# ---------------------------------------------------------------------------
# Encabezado principal
# ---------------------------------------------------------------------------
st.title("☁️ KiroDocs v1.0")
st.subheader("Generador Inteligente de Arquitecturas AWS con Kiro AI (Bedrock)")
st.write(
    "Convierte tus ideas de infraestructura en diagramas interactivos y "
    "documentación técnica instantánea."
)

st.write("---")

col_izq, col_der = st.columns([1, 1])

with col_izq:
    st.write("### 📝 Requerimiento de Infraestructura")

    ejemplo = st.selectbox(
        "Selecciona una plantilla rápida o personaliza tu requerimiento:",
        list(PLANTILLAS.keys()),
    )

    prompt_usuario = st.text_area(
        label="Describe los componentes o el problema a resolver:",
        value=PLANTILLAS[ejemplo],
        placeholder="Ej: Necesito una arquitectura serverless con S3, Lambda y CloudFront...",
        height=140,
        max_chars=MAX_CARACTERES_PROMPT,
    )

    boton_generar = st.button("Generar Solución con Kiro ⚡", type="primary")

with col_der:
    st.write("### 📊 Infraestructura & Documentación")

    if boton_generar:
        descripcion_limpia = prompt_usuario.strip()
        if not descripcion_limpia:
            st.warning("⚠️ Escribe o selecciona un requerimiento antes de generar.")
        else:
            with st.spinner("Procesando arquitectura mediante Kiro AI (Bedrock)... 🤖"):
                try:
                    resultado = generar_arquitectura(
                        descripcion=descripcion_limpia,
                        model_id=MODELOS_DISPONIBLES[modelo_seleccionado],
                        region=region_seleccionada,
                        temperatura=temperatura,
                        max_tokens=max_tokens,
                    )
                    st.session_state["kirodocs_resultado"] = resultado
                    st.session_state["kirodocs_prompt"] = descripcion_limpia
                except NoCredentialsError:
                    st.error(
                        "❌ No se encontraron credenciales de AWS. Configura "
                        "`aws configure` o variables de entorno "
                        "(AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY) antes de continuar."
                    )
                except EndpointConnectionError:
                    st.error(
                        "❌ No se pudo conectar con el endpoint de Bedrock. "
                        "Verifica tu conexión a internet y la región seleccionada."
                    )
                except ClientError as error:
                    codigo = error.response.get("Error", {}).get("Code", "Desconocido")
                    mensaje = error.response.get("Error", {}).get("Message", str(error))
                    if codigo == "AccessDeniedException":
                        st.error(
                            "❌ Acceso denegado. Tu usuario/rol de IAM no tiene "
                            "permiso para invocar este modelo en Bedrock, o el "
                            "modelo no está habilitado en 'Model access'."
                        )
                    else:
                        st.error(f"❌ Error de AWS ({codigo}): {mensaje}")
                except (BotoCoreError, ValueError) as error:
                    st.error(f"❌ No se pudo generar la arquitectura: {error}")

    resultado = st.session_state.get("kirodocs_resultado")
    prompt_usado = st.session_state.get("kirodocs_prompt", "")

    if resultado:
        tab_diagrama, tab_docs, tab_codigo, tab_prompt = st.tabs(
            [
                "📊 Diagrama Interactivo",
                "📄 Documentación (README)",
                "⚙️ Terraform (IaC)",
                "🤖 Prompt de Kiro",
            ]
        )

        with tab_diagrama:
            st.write("#### Diagrama de Arquitectura AWS")
            st.info(resultado.get("resumen_ejecutivo", ""))
    
            diagrama = resultado.get("diagrama_mermaid", "")
    
            try:
                # Intenta usar la función nativa de Streamlit
                st.mermaid_chart(diagrama)
                st.success("✅ Diagrama de infraestructura generado exitosamente.")
            except Exception:
                # Fallback 1: Renderizar con JavaScript/HTML embebido si falla la función nativa
                try:
                    st.components.v1.html(
                        f"""
                        <div style="background-color: #0e1117; padding: 10px; border-radius: 8px;">
                        <pre class="mermaid">
                        {diagrama}
                        </pre>
                        </div>
                        <script type="module">
                            import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
                            mermaid.initialize({{ startOnLoad: true, theme: 'dark' }});
                        </script>
                        """,
                        height=450,
                        scrolling=True
                    )
                    st.success("✅ Diagrama renderizado con el motor Mermaid JS.")
                except Exception as e:
                    # Fallback 2: Si el código Mermaid vino corrupto, muestra el código en texto plano
                    st.error("⚠️ No se pudo renderizar el gráfico dinámico. A continuación se muestra la estructura en código:")
                    st.code(diagrama, language="mermaid")

            if resultado.get("servicios_aws"):
                st.write("#### Servicios utilizados")
                for servicio in resultado["servicios_aws"]:
                    st.markdown(
                        f"- **{servicio.get('nombre', '')}:** "
                        f"{servicio.get('descripcion', '')}"
                    )

        with tab_docs:
            st.write("#### Especificación Técnica (README.md)")
            st.markdown(resultado.get("readme_markdown", ""))
            if resultado.get("consideraciones_seguridad"):
                st.write("#### 🔒 Consideraciones de seguridad")
                for item in resultado["consideraciones_seguridad"]:
                    st.markdown(f"- {item}")
            st.download_button(
                "⬇️ Descargar README.md",
                data=resultado.get("readme_markdown", ""),
                file_name="README.md",
                mime="text/markdown",
            )

        with tab_codigo:
            st.write("#### Infraestructura como Código (IaC)")
            st.code(resultado.get("terraform_code", ""), language="terraform")
            st.download_button(
                "⬇️ Descargar main.tf",
                data=resultado.get("terraform_code", ""),
                file_name="main.tf",
                mime="text/plain",
            )

        with tab_prompt:
            st.write("#### Prompt Estructurado enviado a Kiro AI")
            st.info(
                f"Modelo utilizado: **{modelo_seleccionado}** "
                f"(`{MODELOS_DISPONIBLES[modelo_seleccionado]}`) vía Amazon Bedrock."
            )
            st.code(SYSTEM_PROMPT, language="markdown")
            st.code(construir_prompt_usuario(prompt_usado), language="markdown")
    else:
        st.info(
            "💡 Selecciona una plantilla o escribe tu requerimiento en el "
            "panel izquierdo y haz clic en 'Generar Solución con Kiro'."
        )

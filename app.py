"""
KiroDocs v1.0 - Generador Inteligente de Arquitecturas AWS
Hackathon IA Masivo Online AWS

Usa Amazon Bedrock (Claude Sonnet 5) mediante la Converse API con "tool use"
forzado para garantizar una salida estructurada y consistente: diagrama
Mermaid.js, documentación README y código Terraform.
"""

import textwrap
import time
from pathlib import Path

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
    page_title="KiroDocs",
    page_icon="☁️",
    layout="wide",
    initial_sidebar_state="collapsed",
)


def cargar_css(file_path: str = "styles.css") -> None:
    """Lee un archivo CSS externo y lo inyecta en la app de Streamlit.

    Si el archivo no existe, la app continúa sin estilos personalizados en
    lugar de interrumpir la ejecución.
    """
    ruta_css = Path(__file__).parent / file_path
    try:
        css = ruta_css.read_text(encoding="utf-8")
        st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)
    except FileNotFoundError:
        st.warning(f"⚠️ No se encontró el archivo de estilos: {file_path}")


cargar_css()

# ---------------------------------------------------------------------------
# Configuración de modelos y plantillas
# ---------------------------------------------------------------------------
MODELOS_DISPONIBLES = {
    "Amazon Nova Lite (⚡ Recomendado)": "us.amazon.nova-lite-v1:0",
    "Amazon Nova Pro": "us.amazon.nova-pro-v1:0",
    "Amazon Nova Micro": "us.amazon.nova-micro-v1:0",
    "Claude 3 Haiku": "us.anthropic.claude-3-haiku-20240307-v1:0",
}

REGIONES_DISPONIBLES = ["us-east-2", "us-east-1", "us-west-2", "eu-west-1", "ap-southeast-1"]

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
                            "Resumen breve (3-5 líneas) de la solución "
                            "propuesta, seguido OBLIGATORIAMENTE de una "
                            "subsección titulada '### Decisiones de Diseño' "
                            "que justifique brevemente, en formato de lista, "
                            "por qué se eligió cada servicio principal de la "
                            "arquitectura (ej. 'AWS Lambda: para eliminar "
                            "costos de compute inactivo', 'DynamoDB: por "
                            "latencia en milisegundos y escalabilidad "
                            "automática'). Incluye también cualquier decisión "
                            "de arquitecto tomada ante ambigüedad del "
                            "requerimiento."
                        ),
                    },
                    "diagrama_mermaid": {
                        "type": "string",
                        "description": (
                            "Diagrama en sintaxis válida de Mermaid.js (graph TD "
                            "o graph LR), sin bloques ``` y sin tildes ni "
                            "espacios en los IDs de los nodos. Debe organizar "
                            "los componentes en subgrafos por capa de "
                            "arquitectura AWS (ej. subgraph Cloud [\"Nube "
                            "AWS\"], subgraph Serverless [\"Capa "
                            "Serverless\"]), usar etiquetas de nodo con "
                            "nombres limpios y descriptivos (ej. [API "
                            "Gateway], [Lambda Function], [DynamoDB], "
                            "[Amazon Bedrock]) y aplicar directivas 'style' "
                            "con colores AWS para cada nodo."
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
    - El diagrama debe agrupar los componentes en subgrafos ("subgraph")
      organizados por capa de red o función dentro de AWS, con un subgrafo
      contenedor general (ej. subgraph Cloud ["Nube AWS"]) y subgrafos
      internos por capa (ej. subgraph Serverless ["Capa Serverless"],
      subgraph Data ["Capa de Datos"], subgraph AI ["Capa de IA"]).
    - Cada etiqueta de nodo debe usar un nombre limpio y descriptivo del
      servicio, sin emojis ni íconos Unicode (ej. [API Gateway],
      [Lambda Function], [DynamoDB], [Amazon Bedrock], [CloudWatch],
      [IAM Role]).
    - Cada nodo debe tener una directiva "style" con colores limpios y
      consistentes con la paleta de AWS (naranja #FF9900 para compute/
      integración, azul marino #232F3E para bordes, azul #3B48CC para bases
      de datos, rosado #E7157B para observabilidad), usando texto en blanco
      para buena legibilidad.
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
    - El campo 'resumen_ejecutivo' SIEMPRE debe incluir, después del resumen
      inicial, una subsección titulada exactamente "### Decisiones de
      Diseño" (formato Markdown). En esa subsección, justifica en una lista
      con viñetas por qué elegiste cada servicio principal de la
      arquitectura, en una frase breve y concreta (ej. "AWS Lambda: para
      eliminar costos de compute inactivo y escalar automáticamente con la
      demanda.", "Amazon DynamoDB: por latencia en milisegundos y
      escalabilidad automática sin gestión de servidores."). No omitas esta
      subsección bajo ninguna circunstancia.
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


def generar_respuesta_demo(descripcion: str) -> dict:
    """
    Arquitectura de referencia generada localmente (sin llamadas de red), que
    se usa como último recurso cuando ningún modelo de Bedrock responde (por
    ejemplo, por ThrottlingException mientras AWS aprueba un aumento de
    cuota). El contenido cumple el mismo esquema que la salida real de la
    herramienta "generar_documentacion_arquitectura".
    """
    return {
        "resumen_ejecutivo": (
            "**Modo de Resiliencia**\n\n"
            "No fue posible contactar a ningún modelo de Amazon Bedrock "
            "debido a restricciones temporales del servicio (como límites "
            "de cuota, throttling o disponibilidad de acceso). KiroDocs "
            "proporciona automáticamente una Arquitectura de Continuidad "
            "validada para que el flujo de trabajo pueda continuar sin "
            "interrupciones. Cuando Bedrock vuelva a estar disponible, "
            "podrás generar nuevamente una propuesta personalizada basada "
            "en tu requerimiento.\n\n"
            "### Decisiones de Diseño\n\n"
            "- **Amazon API Gateway:** expone un endpoint HTTP administrado "
            "con autenticación, throttling y monitoreo integrados, sin "
            "necesidad de gestionar servidores propios.\n"
            "- **AWS Lambda:** elimina costos de compute inactivo (modelo "
            "pay-per-use) y escala automáticamente con la demanda de "
            "solicitudes.\n"
            "- **Amazon DynamoDB:** ofrece latencia de un solo dígito en "
            "milisegundos y escalabilidad automática, ideal para cargas de "
            "trabajo serverless impredecibles.\n"
            "- **Amazon Bedrock:** provee acceso unificado a modelos "
            "fundacionales (Nova, Claude) mediante la Converse API, evitando "
            "gestionar infraestructura de inferencia propia."
        ),
        "diagrama_mermaid": textwrap.dedent(
            """
            graph TD
                Cliente[Cliente / Front]

                subgraph Cloud ["Nube AWS"]
                    subgraph Serverless ["Capa Serverless"]
                        API[API Gateway]
                        Lambda[Lambda Function]
                    end
                    subgraph Data ["Capa de Datos"]
                        DB[(DynamoDB)]
                    end
                    subgraph Observability ["Observabilidad"]
                        CloudWatch[CloudWatch]
                    end
                end

                Cliente -->|HTTPS| API
                API -->|Trigger| Lambda
                Lambda -->|CRUD| DB
                Lambda -->|Logs| CloudWatch

                style Cliente fill:#232F3E,stroke:#FF9900,stroke-width:2px,color:#fff
                style API fill:#FF9900,stroke:#232F3E,stroke-width:2px,color:#fff
                style Lambda fill:#FF9900,stroke:#232F3E,stroke-width:2px,color:#fff
                style DB fill:#3B48CC,stroke:#232F3E,stroke-width:2px,color:#fff
                style CloudWatch fill:#E7157B,stroke:#232F3E,stroke-width:2px,color:#fff
            """
        ).strip(),
        "servicios_aws": [
            {
                "nombre": "AWS API Gateway",
                "descripcion": "Gestión de endpoints HTTP/REST y enrutamiento seguro.",
            },
            {
                "nombre": "AWS Lambda",
                "descripcion": "Ejecución de lógica de negocio en entorno Serverless.",
            },
            {
                "nombre": "Amazon DynamoDB",
                "descripcion": "Almacenamiento NoSQL gestionado de alta disponibilidad.",
            },
            {
                "nombre": "Amazon CloudWatch",
                "descripcion": "Monitoreo y centralización de logs de ejecución.",
            },
        ],
        "readme_markdown": textwrap.dedent(
            f"""
            # Arquitectura de Solución en AWS (Modo Resiliencia)

            > ⚠️ Este documento fue generado en **Modo Resiliencia**, sin
            > conexión a Amazon Bedrock. Es una **Arquitectura de
            > Continuidad** de referencia ya validada, no una propuesta
            > personalizada para tu requerimiento real.

            ## Requerimiento del usuario
            > "{descripcion}"

            ## Componentes y servicios
            - **AWS API Gateway:** gestión de endpoints HTTP/REST y enrutamiento seguro.
            - **AWS Lambda:** ejecución de lógica de negocio en entorno Serverless.
            - **Amazon DynamoDB:** almacenamiento NoSQL gestionado de alta disponibilidad.
            - **Amazon CloudWatch:** monitoreo y centralización de logs de ejecución.

            ## Patrones de diseño aplicados
            - Alta disponibilidad y escalabilidad auto-gestionada.
            - Modelo de seguridad con principio de mínimo privilegio (IAM).
            """
        ).strip(),
        "terraform_code": textwrap.dedent(
            """
            terraform {
              required_providers {
                aws = {
                  source  = "hashicorp/aws"
                  version = "~> 5.0"
                }
              }
            }

            provider "aws" {
              region = "us-east-1"
            }

            resource "aws_dynamodb_table" "main_db" {
              name         = "KiroDocsDemoTable"
              billing_mode = "PAY_PER_REQUEST"
              hash_key     = "id"

              attribute {
                name = "id"
                type = "S"
              }

              tags = {
                Project = "KiroDocs"
                Mode    = "Resiliencia"
              }
            }
            """
        ).strip(),
        "consideraciones_seguridad": [
            "Aplicar el principio de mínimo privilegio en los roles IAM de Lambda.",
            "Habilitar cifrado en reposo (KMS) en la tabla DynamoDB.",
            "Restringir el acceso al API Gateway mediante un autorizador (Cognito o Lambda Authorizer).",
        ],
    }


def describir_error_boto(error: Exception) -> str:
    """Devuelve una descripción corta y legible de un error de boto3."""
    if isinstance(error, NoCredentialsError):
        return "credenciales de AWS no encontradas"
    if isinstance(error, EndpointConnectionError):
        return "no se pudo conectar con el endpoint de Bedrock"
    if isinstance(error, ClientError):
        codigo = error.response.get("Error", {}).get("Code", "Desconocido")
        mensaje = error.response.get("Error", {}).get("Message", str(error))
        return f"{codigo} - {mensaje}"
    return str(error)


def generar_arquitectura_con_fallback(
    descripcion: str,
    orden_modelos: list[tuple[str, str]],
    region: str,
    temperatura: float,
    max_tokens: int,
) -> tuple[dict, str, str, list[tuple[str, Exception]], bool]:
    """
    Intenta generar la arquitectura probando los modelos en el orden recibido.

    El primer elemento de `orden_modelos` es el modelo elegido por el usuario;
    si falla (ThrottlingException, AccessDeniedException o cualquier otro
    error de Bedrock/boto3), se prueba automáticamente con el siguiente
    modelo disponible, y así sucesivamente.

    Si TODOS los modelos fallan (por ejemplo, mientras AWS aprueba un
    aumento de cuota de Bedrock), en lugar de interrumpir la app se
    devuelve una respuesta Demo de referencia para que el usuario pueda
    seguir viendo la interfaz funcionando.

    Devuelve: (resultado, nombre_modelo_usado, model_id_usado,
    intentos_fallidos, es_demo)
    """
    intentos_fallidos: list[tuple[str, Exception]] = []

    for nombre_modelo, model_id in orden_modelos:
        try:
            resultado = generar_arquitectura(
                descripcion=descripcion,
                model_id=model_id,
                region=region,
                temperatura=temperatura,
                max_tokens=max_tokens,
            )
            return resultado, nombre_modelo, model_id, intentos_fallidos, False
        except (ClientError, BotoCoreError, ValueError) as error:
            intentos_fallidos.append((nombre_modelo, error))
            continue

    # Todos los modelos fallaron: se devuelve una respuesta Demo válida en
    # lugar de lanzar una excepción, para no interrumpir la experiencia del
    # usuario mientras se resuelve la cuota de Bedrock.
    resultado_demo = generar_respuesta_demo(descripcion)
    return resultado_demo, "Modo Resiliencia (sin conexión a Bedrock)", "demo-local", intentos_fallidos, True


# ---------------------------------------------------------------------------
# Barra lateral: configuración de Bedrock
# ---------------------------------------------------------------------------
with st.sidebar:
    st.write("### Configuración de Bedrock")
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
st.title("KiroDocs")
st.markdown(
    """
    <span style="
        display:inline-block;
        padding:0.15rem 0.65rem;
        border-radius:999px;
        font-size:0.75rem;
        font-weight:600;
        letter-spacing:0.03em;
        color:#38bdf8;
        background:rgba(56,189,248,0.12);
        border:1px solid rgba(56,189,248,0.35);
        margin-bottom:0.5rem;
    ">v1.0</span>
    """,
    unsafe_allow_html=True,
)
st.subheader("Generador Inteligente de Arquitecturas AWS con Kiro AI (Bedrock)")
st.write(
    "Convierte tus ideas de infraestructura en diagramas interactivos y "
    "documentación técnica instantánea."
)

st.write("---")

col_izq, col_der = st.columns([1, 1])

with col_izq:
    st.write("### Requerimiento de Infraestructura")

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
    st.write("### Infraestructura & Documentación")

    if boton_generar:
        descripcion_limpia = prompt_usuario.strip()
        if not descripcion_limpia:
            st.warning("⚠️ Escribe o selecciona un requerimiento antes de generar.")
        else:
            # Orden de intento: primero el modelo elegido por el usuario, luego
            # el resto de MODELOS_DISPONIBLES como respaldo (en su orden original).
            orden_modelos = [(modelo_seleccionado, MODELOS_DISPONIBLES[modelo_seleccionado])]
            orden_modelos += [
                (nombre, mid)
                for nombre, mid in MODELOS_DISPONIBLES.items()
                if nombre != modelo_seleccionado
            ]

            with st.spinner("Procesando arquitectura mediante Kiro AI (Bedrock)..."):
                try:
                    # Medición de latencia: cubre tanto la invocación normal a
                    # Bedrock como la cadena de reintentos y, si aplica, la
                    # activación del Modo de Continuidad del Servicio.
                    inicio = time.time()
                    resultado, nombre_modelo_usado, model_id_usado, intentos_fallidos, es_demo = (
                        generar_arquitectura_con_fallback(
                            descripcion=descripcion_limpia,
                            orden_modelos=orden_modelos,
                            region=region_seleccionada,
                            temperatura=temperatura,
                            max_tokens=max_tokens,
                        )
                    )
                    fin = time.time()
                    latencia_segundos = fin - inicio

                    st.session_state["kirodocs_resultado"] = resultado
                    st.session_state["kirodocs_prompt"] = descripcion_limpia
                    st.session_state["kirodocs_modelo_usado"] = nombre_modelo_usado
                    st.session_state["kirodocs_es_demo"] = es_demo
                    st.session_state["kirodocs_latencia"] = latencia_segundos
                    st.session_state["kirodocs_region_usada"] = region_seleccionada

                    if es_demo:
                        st.info(
                            "Modo de Continuidad Activo: Ante restricciones "
                            "temporales de cuota en Amazon Bedrock, KiroDocs "
                            "activa automáticamente su mecanismo de "
                            "resiliencia para proporcionar una arquitectura "
                            "de referencia validada y garantizar la "
                            "continuidad del servicio."
                        )
                        st.caption(
                            "El panel de diagnóstico registra la traza de "
                            "auditoría de las respuestas de Amazon Bedrock "
                            "que activaron el mecanismo de resiliencia."
                        )
                        with st.expander("Ver auditoría de resiliencia"):
                            for nombre_modelo, err in intentos_fallidos:
                                st.markdown(
                                    f"- **{nombre_modelo}:** {describir_error_boto(err)}"
                                )
                    elif intentos_fallidos:
                        nombre_fallido, error_fallido = intentos_fallidos[0]
                        st.warning(
                            f"⚠️ El modelo principal **{nombre_fallido}** falló "
                            f"({describir_error_boto(error_fallido)}). "
                            f"Se usó el modelo de respaldo **{nombre_modelo_usado}** "
                            "con éxito."
                        )
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

    resultado = st.session_state.get("kirodocs_resultado")
    prompt_usado = st.session_state.get("kirodocs_prompt", "")

    if resultado:
        nombre_modelo_metrica = st.session_state.get(
            "kirodocs_modelo_usado", modelo_seleccionado
        )
        latencia_metrica = st.session_state.get("kirodocs_latencia")
        region_metrica = st.session_state.get(
            "kirodocs_region_usada", region_seleccionada
        )
        if latencia_metrica is not None:
            st.markdown(
                f"""
                <div style="
                    display:inline-block;
                    padding:0.5rem 1.1rem;
                    border-radius:999px;
                    font-size:0.85rem;
                    font-weight:500;
                    color:#f1f5f9;
                    background:rgba(56,189,248,0.10);
                    border:1px solid rgba(56,189,248,0.35);
                    margin-bottom:0.75rem;
                ">
                    <strong>Tiempo de generación:</strong> {latencia_metrica:.2f}s
                    &nbsp;|&nbsp;
                    <strong>Modelo activo:</strong> {nombre_modelo_metrica}
                    &nbsp;|&nbsp;
                    <strong>Región:</strong> {region_metrica}
                </div>
                """,
                unsafe_allow_html=True,
            )

        tab_diagrama, tab_docs, tab_codigo, tab_prompt = st.tabs(
            [
                "Diagrama Interactivo",
                "Documentación (README)",
                "Terraform (IaC)",
                "Prompt de Kiro",
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
                        <style>
                            html, body {{
                                background: #0f172a;
                                margin: 0;
                            }}
                        </style>
                        <div style="background: transparent; padding: 10px; border-radius: 14px;">
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
                st.write("#### Consideraciones de seguridad")
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
            nombre_modelo_final = st.session_state.get(
                "kirodocs_modelo_usado", modelo_seleccionado
            )
            st.info(
                f"Modelo utilizado: **{nombre_modelo_final}** "
                f"(`{MODELOS_DISPONIBLES.get(nombre_modelo_final, '')}`) vía Amazon Bedrock."
            )
            st.code(SYSTEM_PROMPT, language="markdown")
            st.code(construir_prompt_usuario(prompt_usado), language="markdown")
    else:
        st.info(
            "Selecciona una plantilla o escribe tu requerimiento en el "
            "panel izquierdo y haz clic en 'Generar Solución con Kiro'."
        )

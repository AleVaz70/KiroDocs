"""
KiroDocs v1.0 - Generador Inteligente de Arquitecturas AWS
Hackathon IA Masivo Online AWS

Usa Amazon Bedrock (Claude Sonnet 5) mediante la Converse API con "tool use"
forzado para garantizar una salida estructurada y consistente: diagrama
Mermaid.js, documentación README y código Terraform.
"""

import re
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

try:
    import hcl2

    HCL2_DISPONIBLE = True
except ImportError:
    hcl2 = None
    HCL2_DISPONIBLE = False

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
# Tarifas estimadas de Amazon Bedrock (on-demand, tier estándar, USD por
# cada 1.000 tokens). Son valores de referencia públicos y pueden variar
# según la región o cambios de precio de AWS; se usan únicamente para
# mostrar un costo estimado orientativo, no una factura real.
# ---------------------------------------------------------------------------
PRECIOS_POR_MODELO = {
    "us.amazon.nova-micro-v1:0": (0.000035, 0.00014),
    "us.amazon.nova-lite-v1:0": (0.00006, 0.00024),
    "us.amazon.nova-pro-v1:0": (0.0008, 0.0032),
    "us.anthropic.claude-3-haiku-20240307-v1:0": (0.00025, 0.00125),
}


def calcular_costo_estimado(model_id: str, input_tokens: int, output_tokens: int) -> float:
    """Calcula el costo estimado en USD de una invocación a Bedrock.

    Usa las tarifas de referencia de `PRECIOS_POR_MODELO`. Si el modelo no
    está en la tabla (por ejemplo, "demo-local" del Modo de Continuidad),
    devuelve 0.0 en lugar de fallar.
    """
    precio_input, precio_output = PRECIOS_POR_MODELO.get(model_id, (0.0, 0.0))
    return (input_tokens / 1000) * precio_input + (output_tokens / 1000) * precio_output

# ---------------------------------------------------------------------------
# Análisis estático de Terraform: sintaxis HCL y auditoría de seguridad
# (estilo Checkov / AWS Well-Architected) sobre el código generado, tanto
# en llamadas reales a Bedrock como en el Modo de Resiliencia.
# ---------------------------------------------------------------------------


def _validar_sintaxis_hcl_basica(codigo_tf: str) -> tuple[bool, str]:
    """Parser estático de respaldo cuando la librería `hcl2` no está
    disponible: verifica balance de llaves y presencia de al menos un
    bloque `resource` bien formado.
    """
    abiertas = codigo_tf.count("{")
    cerradas = codigo_tf.count("}")
    if abiertas != cerradas:
        return False, (
            f"Llaves desbalanceadas: {abiertas} '{{' frente a {cerradas} '}}' "
            "(validación básica de bloques, librería 'hcl2' no disponible)."
        )
    if not re.search(r'resource\s+"[\w-]+"\s+"[\w-]+"\s*\{', codigo_tf):
        return False, (
            "No se encontró ningún bloque 'resource' válido "
            "(validación básica de bloques, librería 'hcl2' no disponible)."
        )
    return True, "Correcta (validación básica de bloques, librería 'hcl2' no disponible)."


def _extraer_bloques_resource(codigo_tf: str, tipo_recurso: str) -> list[str]:
    """Extrae el cuerpo (texto entre llaves) de cada bloque `resource` del
    tipo indicado, respetando llaves anidadas mediante conteo de
    profundidad en lugar de una expresión regular ingenua.
    """
    bloques: list[str] = []
    patron_inicio = re.compile(rf'resource\s+"{re.escape(tipo_recurso)}"\s+"[\w-]+"\s*\{{')
    for coincidencia in patron_inicio.finditer(codigo_tf):
        inicio = coincidencia.end()
        profundidad = 1
        posicion = inicio
        while posicion < len(codigo_tf) and profundidad > 0:
            if codigo_tf[posicion] == "{":
                profundidad += 1
            elif codigo_tf[posicion] == "}":
                profundidad -= 1
            posicion += 1
        bloques.append(codigo_tf[inicio : posicion - 1])
    return bloques


def _chequear_cifrado_dynamodb(codigo_tf: str) -> dict:
    """Checkov-style: `aws_dynamodb_table` debe tener cifrado en reposo
    (`server_side_encryption { enabled = true }`)."""
    nombre_corto = "Cifrado DynamoDB"
    bloques = _extraer_bloques_resource(codigo_tf, "aws_dynamodb_table")
    if not bloques:
        return {
            "nombre_corto": nombre_corto,
            "nombre": "Cifrado de DynamoDB en reposo",
            "pasado": True,
            "detalle": "No se detectaron tablas DynamoDB en el código (chequeo no aplicable).",
        }
    for bloque in bloques:
        tiene_cifrado = bool(
            re.search(r"server_side_encryption\s*\{[^}]*enabled\s*=\s*true", bloque, re.DOTALL)
        )
        if not tiene_cifrado:
            return {
                "nombre_corto": nombre_corto,
                "nombre": "Cifrado de DynamoDB en reposo",
                "pasado": False,
                "detalle": (
                    "Al menos una tabla DynamoDB no define "
                    "'server_side_encryption { enabled = true }'."
                ),
            }
    return {
        "nombre_corto": nombre_corto,
        "nombre": "Cifrado de DynamoDB en reposo",
        "pasado": True,
        "detalle": "Todas las tablas DynamoDB tienen cifrado en reposo habilitado.",
    }


def _chequear_retencion_logs_cloudwatch(codigo_tf: str) -> dict:
    """Checkov-style: los grupos de logs `aws_cloudwatch_log_group` deben
    definir una política de retención (`retention_in_days`)."""
    nombre_corto = "Logs CloudWatch"
    bloques = _extraer_bloques_resource(codigo_tf, "aws_cloudwatch_log_group")
    if not bloques:
        return {
            "nombre_corto": nombre_corto,
            "nombre": "Retención de logs en CloudWatch",
            "pasado": False,
            "detalle": (
                "No se encontró ningún 'aws_cloudwatch_log_group' con "
                "política de retención de logs definida."
            ),
        }
    for bloque in bloques:
        coincidencia = re.search(r"retention_in_days\s*=\s*(\d+)", bloque)
        if not coincidencia or int(coincidencia.group(1)) <= 0:
            return {
                "nombre_corto": nombre_corto,
                "nombre": "Retención de logs en CloudWatch",
                "pasado": False,
                "detalle": (
                    "Al menos un grupo de logs de CloudWatch no define "
                    "'retention_in_days' con un valor mayor a 0."
                ),
            }
    return {
        "nombre_corto": nombre_corto,
        "nombre": "Retención de logs en CloudWatch",
        "pasado": True,
        "detalle": "Los grupos de logs de CloudWatch definen un período de retención explícito.",
    }


def _chequear_iam_minimo_privilegio(codigo_tf: str) -> dict:
    """Checkov-style: las políticas IAM (`aws_iam_role_policy` /
    `aws_iam_policy`) no deben usar comodines ('*') en Action o Resource."""
    nombre_corto = "IAM Menor Privilegio"
    bloques = _extraer_bloques_resource(codigo_tf, "aws_iam_role_policy")
    bloques += _extraer_bloques_resource(codigo_tf, "aws_iam_policy")
    if not bloques:
        return {
            "nombre_corto": nombre_corto,
            "nombre": "IAM de mínimo privilegio",
            "pasado": False,
            "detalle": (
                "No se encontró ninguna política IAM (aws_iam_role_policy / "
                "aws_iam_policy) asociada a los roles de la arquitectura."
            ),
        }
    for bloque in bloques:
        if re.search(r'Action\s*=\s*"\*"', bloque) or re.search(r'Resource\s*=\s*"\*"', bloque):
            return {
                "nombre_corto": nombre_corto,
                "nombre": "IAM de mínimo privilegio",
                "pasado": False,
                "detalle": (
                    "Se detectó una política IAM con permisos comodín ('*') "
                    "en Action o Resource, lo cual viola el mínimo privilegio."
                ),
            }
    return {
        "nombre_corto": nombre_corto,
        "nombre": "IAM de mínimo privilegio",
        "pasado": True,
        "detalle": "Las políticas IAM definen acciones y recursos específicos (sin comodines '*').",
    }


def analizar_terraform(codigo_tf: str) -> dict:
    """Analiza el código Terraform generado (ya sea por una llamada real a
    Bedrock o por el Modo de Resiliencia): valida su sintaxis HCL y ejecuta
    una auditoría de seguridad estilo Checkov / AWS Well-Architected sobre
    puntos críticos (cifrado en reposo de DynamoDB, retención de logs de
    CloudWatch e IAM de mínimo privilegio).

    Devuelve un diccionario con 'sintaxis_valida', 'sintaxis_detalle' y
    'chequeos' (lista de dicts con 'nombre_corto', 'nombre', 'pasado' y
    'detalle').
    """
    if HCL2_DISPONIBLE:
        try:
            hcl2.loads(codigo_tf)
            sintaxis_valida, sintaxis_detalle = True, "Correcta (validada con la librería 'hcl2')."
        except Exception as error:  # noqa: BLE001 - cualquier error de parseo debe reportarse
            sintaxis_valida, sintaxis_detalle = False, f"Error de sintaxis HCL: {error}"
    else:
        sintaxis_valida, sintaxis_detalle = _validar_sintaxis_hcl_basica(codigo_tf)

    chequeos = [
        _chequear_cifrado_dynamodb(codigo_tf),
        _chequear_retencion_logs_cloudwatch(codigo_tf),
        _chequear_iam_minimo_privilegio(codigo_tf),
    ]

    return {
        "sintaxis_valida": sintaxis_valida,
        "sintaxis_detalle": sintaxis_detalle,
        "chequeos": chequeos,
    }

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
                            "propuesta, seguido OBLIGATORIAMENTE de dos "
                            "subsecciones en este orden: "
                            "(1) '### Decisiones de Diseño', que justifique "
                            "brevemente, en formato de lista, por qué se "
                            "eligió cada servicio principal de la "
                            "arquitectura (ej. 'AWS Lambda: para eliminar "
                            "costos de compute inactivo', 'DynamoDB: por "
                            "latencia en milisegundos y escalabilidad "
                            "automática'); y (2) '### Alternativas "
                            "Descartadas y Justificación', que explique "
                            "brevemente, en "
                            "formato de lista, por qué NO se eligieron otras "
                            "opciones tradicionales relevantes para este caso "
                            "(ej. 'Amazon RDS: descartado frente a DynamoDB "
                            "por no requerir un esquema relacional ni joins "
                            "complejos', 'Amazon EC2: descartado frente a "
                            "AWS Lambda por no justificar el costo y la "
                            "gestión de servidores para esta carga de "
                            "trabajo'). Incluye también cualquier decisión de "
                            "arquitecto tomada ante ambigüedad del "
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
                        "description": (
                            "Lista de servicios de AWS utilizados en la "
                            "arquitectura. Cada 'nombre' debe usar el nombre "
                            "oficial del servicio (ej. 'Amazon API Gateway', "
                            "'AWS Lambda', 'Amazon DynamoDB', 'Amazon "
                            "CloudWatch') y cada 'descripcion' debe ser una "
                            "frase breve y concreta que explique su rol en "
                            "la solución (se renderiza como '- **nombre** — "
                            "descripcion')."
                        ),
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
    - Si la arquitectura incluye una o más funciones AWS Lambda, el código
      Terraform SIEMPRE debe declarar explícitamente un recurso
      "aws_cloudwatch_log_group" por cada función (o uno compartido, según
      corresponda), con la propiedad "retention_in_days" configurada con un
      valor mayor a 0 (ej. 14 o 30). No dependas del log group implícito
      que Lambda crea automáticamente sin gestión de retención.
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
      inicial, dos subsecciones en este orden exacto:
      1. "### Decisiones de Diseño" (formato Markdown): justifica en una
         lista con viñetas por qué elegiste cada servicio principal de la
         arquitectura, en una frase breve y concreta (ej. "AWS Lambda: para
         eliminar costos de compute inactivo y escalar automáticamente con
         la demanda.", "Amazon DynamoDB: por latencia en milisegundos y
         escalabilidad automática sin gestión de servidores.").
      2. "### Alternativas Descartadas y Justificación" (formato Markdown):
         explica en una lista con viñetas por qué NO elegiste otras opciones tradicionales
         relevantes para este caso de uso, en una frase breve y concreta
         (ej. "Amazon RDS: descartado frente a DynamoDB porque el modelo de
         datos no requiere un esquema relacional ni consultas con joins
         complejos.", "Amazon EC2: descartado frente a AWS Lambda porque no
         justifica el costo ni la gestión operativa de servidores para esta
         carga de trabajo.").
      No omitas ninguna de estas dos subsecciones bajo ninguna
      circunstancia.
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
) -> tuple[dict, dict]:
    """Invoca Amazon Bedrock (Converse API) y devuelve el JSON estructurado
    junto con el uso de tokens reportado por la API (`usage`).

    Devuelve: (resultado, uso_tokens), donde uso_tokens tiene las claves
    'inputTokens', 'outputTokens' y 'totalTokens'.
    """
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

    uso = respuesta.get("usage", {})
    uso_tokens = {
        "inputTokens": uso.get("inputTokens", 0),
        "outputTokens": uso.get("outputTokens", 0),
        "totalTokens": uso.get("totalTokens", 0),
    }

    bloques_contenido = respuesta["output"]["message"]["content"]
    for bloque in bloques_contenido:
        if "toolUse" in bloque and bloque["toolUse"]["name"] == TOOL_NAME:
            return bloque["toolUse"]["input"], uso_tokens

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
            "No fue posible establecer una conexión con Amazon Bedrock "
            "(credenciales, acceso o restricciones temporales). KiroDocs "
            "activó automáticamente su mecanismo de resiliencia para "
            "mantener la continuidad del servicio y proporcionar una "
            "arquitectura de referencia validada.\n\n"
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
            "- **Amazon CloudWatch:** centraliza métricas y logs de "
            "ejecución de Lambda, permitiendo monitorear la salud de la "
            "arquitectura sin infraestructura de observabilidad adicional.\n\n"
            "### Alternativas Descartadas y Justificación\n\n"
            "- **Amazon EC2:** descartado frente a AWS Lambda porque no "
            "justifica el costo ni la gestión operativa de servidores para "
            "una carga de trabajo serverless con tráfico variable.\n"
            "- **Amazon RDS:** descartado frente a DynamoDB porque el "
            "modelo de datos no requiere un esquema relacional ni consultas "
            "con joins complejos.\n"
            "- **Application Load Balancer + contenedores:** descartado "
            "frente a API Gateway + Lambda por añadir complejidad "
            "operativa innecesaria para un endpoint HTTP de baja a media "
            "complejidad."
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
                "nombre": "Amazon API Gateway",
                "descripcion": (
                    "Expone de forma segura los endpoints HTTP/REST, "
                    "gestionando autenticación, control de tráfico y "
                    "enrutamiento."
                ),
            },
            {
                "nombre": "AWS Lambda",
                "descripcion": (
                    "Ejecuta la lógica de negocio bajo un modelo serverless "
                    "con escalado automático y pago por uso."
                ),
            },
            {
                "nombre": "Amazon DynamoDB",
                "descripcion": (
                    "Proporciona almacenamiento NoSQL administrado, "
                    "altamente disponible y de baja latencia."
                ),
            },
            {
                "nombre": "Amazon CloudWatch",
                "descripcion": (
                    "Centraliza métricas, registros y monitoreo operativo "
                    "para facilitar la observabilidad de la solución."
                ),
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

              server_side_encryption {
                enabled = true
              }

              tags = {
                Project = "KiroDocs"
                Mode    = "Resiliencia"
              }
            }

            resource "aws_cloudwatch_log_group" "lambda_logs" {
              name              = "/aws/lambda/kirodocs-demo"
              retention_in_days = 30

              tags = {
                Project = "KiroDocs"
                Mode    = "Resiliencia"
              }
            }

            resource "aws_iam_role" "lambda_exec_role" {
              name = "kirodocs-demo-lambda-role"

              assume_role_policy = jsonencode({
                Version = "2012-10-17"
                Statement = [{
                  Action    = "sts:AssumeRole"
                  Effect    = "Allow"
                  Principal = { Service = "lambda.amazonaws.com" }
                }]
              })
            }

            resource "aws_iam_role_policy" "lambda_least_privilege" {
              name = "kirodocs-demo-least-privilege"
              role = aws_iam_role.lambda_exec_role.id

              policy = jsonencode({
                Version = "2012-10-17"
                Statement = [
                  {
                    Effect   = "Allow"
                    Action   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Query"]
                    Resource = aws_dynamodb_table.main_db.arn
                  },
                  {
                    Effect   = "Allow"
                    Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
                    Resource = "${aws_cloudwatch_log_group.lambda_logs.arn}:*"
                  }
                ]
              })
            }
            """
        ).strip(),
        "consideraciones_seguridad": [
            "Aplicar el principio de mínimo privilegio en los roles IAM de Lambda.",
            "Habilitar cifrado en reposo (KMS) en la tabla DynamoDB.",
            "Restringir el acceso al API Gateway mediante un autorizador (Cognito o Lambda Authorizer).",
        ],
        # Valores simulados de uso de tokens, ya que el Modo de Continuidad
        # no realiza ninguna llamada real a Amazon Bedrock. Se usan solo
        # para que el badge de métricas muestre un dato de referencia
        # consistente en lugar de quedar vacío.
        "_uso_tokens_simulado": {
            "inputTokens": 450,
            "outputTokens": 1200,
            "totalTokens": 1650,
        },
    }


def describir_error_boto(error: Exception) -> str:
    """Devuelve una descripción corta y legible de un error de boto3."""
    if isinstance(error, NoCredentialsError):
        return "Sin conexión a Amazon Bedrock"
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
) -> tuple[dict, str, str, list[tuple[str, Exception]], bool, dict]:
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
    intentos_fallidos, es_demo, uso_tokens)
    """
    intentos_fallidos: list[tuple[str, Exception]] = []

    for nombre_modelo, model_id in orden_modelos:
        try:
            resultado, uso_tokens = generar_arquitectura(
                descripcion=descripcion,
                model_id=model_id,
                region=region,
                temperatura=temperatura,
                max_tokens=max_tokens,
            )
            return resultado, nombre_modelo, model_id, intentos_fallidos, False, uso_tokens
        except (ClientError, BotoCoreError, ValueError) as error:
            intentos_fallidos.append((nombre_modelo, error))
            continue

    # Todos los modelos fallaron: se devuelve una respuesta Demo válida en
    # lugar de lanzar una excepción, para no interrumpir la experiencia del
    # usuario mientras se resuelve la cuota de Bedrock.
    resultado_demo = generar_respuesta_demo(descripcion)
    uso_tokens_demo = resultado_demo.pop(
        "_uso_tokens_simulado", {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0}
    )
    return (
        resultado_demo,
        "Modo Resiliencia (sin conexión a Bedrock)",
        "demo-local",
        intentos_fallidos,
        True,
        uso_tokens_demo,
    )


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
st.subheader("Agente Inteligente de Arquitectura AWS con Kiro AI (Amazon Bedrock)")
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
                    resultado, nombre_modelo_usado, model_id_usado, intentos_fallidos, es_demo, uso_tokens = (
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

                    tokens_totales = uso_tokens.get("totalTokens", 0)
                    costo_estimado = calcular_costo_estimado(
                        model_id_usado,
                        uso_tokens.get("inputTokens", 0),
                        uso_tokens.get("outputTokens", 0),
                    )

                    st.session_state["kirodocs_resultado"] = resultado
                    st.session_state["kirodocs_prompt"] = descripcion_limpia
                    st.session_state["kirodocs_modelo_usado"] = nombre_modelo_usado
                    st.session_state["kirodocs_es_demo"] = es_demo
                    st.session_state["kirodocs_latencia"] = latencia_segundos
                    st.session_state["kirodocs_region_usada"] = region_seleccionada
                    st.session_state["kirodocs_tokens_totales"] = tokens_totales
                    st.session_state["kirodocs_costo_estimado"] = costo_estimado

                    if es_demo:
                        st.info(
                            "Modo de Continuidad Activo: No fue posible "
                            "establecer una conexión con Amazon Bedrock "
                            "(credenciales, acceso o restricciones "
                            "temporales). KiroDocs activó automáticamente su "
                            "mecanismo de resiliencia para mantener la "
                            "continuidad del servicio y proporcionar una "
                            "arquitectura de referencia validada."
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
        tokens_metrica = st.session_state.get("kirodocs_tokens_totales", 0)
        costo_metrica = st.session_state.get("kirodocs_costo_estimado", 0.0)
        es_demo_metrica = st.session_state.get("kirodocs_es_demo", False)
        if latencia_metrica is not None:
            if es_demo_metrica:
                # Modo Resiliencia: no hubo llamada real a Bedrock, por lo
                # tanto los tokens son estimados/simulados y el costo no es
                # calculable de forma honesta (se muestra N/A en vez de $0).
                fila_tokens = f"<strong>Tokens (est.):</strong> {tokens_metrica}"
                fila_costo = "<strong>Costo est.:</strong> N/A"
                fila_modelo = "<strong>Modelo:</strong> Modo Resiliencia"
            else:
                fila_tokens = f"<strong>Tokens:</strong> {tokens_metrica}"
                fila_costo = f"<strong>Costo est.:</strong> ${costo_metrica:.4f} USD"
                fila_modelo = f"<strong>Modelo:</strong> {nombre_modelo_metrica}"

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
                    <strong>Tiempo:</strong> {latencia_metrica:.2f}s
                    &nbsp;|&nbsp;
                    {fila_modelo}
                    &nbsp;|&nbsp;
                    {fila_tokens}
                    &nbsp;|&nbsp;
                    {fila_costo}
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
                st.write("### Servicios AWS utilizados en esta arquitectura")
                for servicio in resultado["servicios_aws"]:
                    st.markdown(
                        f"- **{servicio.get('nombre', '')}** — "
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
            terraform_generado = resultado.get("terraform_code", "")
            st.code(terraform_generado, language="terraform")
            st.download_button(
                "⬇️ Descargar main.tf",
                data=terraform_generado,
                file_name="main.tf",
                mime="text/plain",
            )

            analisis_tf = analizar_terraform(terraform_generado)
            with st.expander("Análisis de Seguridad & Cumplimiento (Checkov & Sintaxis HCL)"):
                if analisis_tf["sintaxis_valida"]:
                    st.markdown(f"**Sintaxis HCL:** Correcta — {analisis_tf['sintaxis_detalle']}")
                else:
                    st.markdown(f"**Sintaxis HCL:** Con errores — {analisis_tf['sintaxis_detalle']}")

                chequeos_tf = analisis_tf["chequeos"]
                pasados = [c for c in chequeos_tf if c["pasado"]]
                fallidos = [c for c in chequeos_tf if not c["pasado"]]
                nombres_pasados = ", ".join(c["nombre_corto"] for c in pasados)

                if not fallidos:
                    st.markdown(
                        f"**Auditoría de Seguridad Checkov / Well-Architected:** "
                        f"0 Vulnerabilidades Críticas "
                        f"({len(pasados)} Chequeos Pasados: {nombres_pasados})."
                    )
                else:
                    st.markdown(
                        f"**Auditoría de Seguridad Checkov / Well-Architected:** "
                        f"{len(fallidos)} Vulnerabilidad(es) Crítica(s) detectada(s) "
                        f"({len(pasados)} Chequeos Pasados: {nombres_pasados})."
                    )

                for chequeo in chequeos_tf:
                    icono = "✅" if chequeo["pasado"] else "❌"
                    st.markdown(f"- {icono} **{chequeo['nombre']}:** {chequeo['detalle']}")

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
            """
**Esperando tu requerimiento de infraestructura**

Describe la infraestructura que necesitas en el panel de la izquierda o selecciona una plantilla para comenzar.

Aquí se mostrarán la propuesta de arquitectura, el diagrama Mermaid, el código Terraform y el análisis de seguridad generados por KiroDocs.
"""
        )

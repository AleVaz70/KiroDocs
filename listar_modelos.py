"""
listar_modelos.py - Script de diagnóstico para KiroDocs

Lista los foundation models de Amazon Bedrock que están:
  - Activos (ACTIVE) según su ciclo de vida.
  - Habilitados para invocación mediante ON_DEMAND o INFERENCE_PROFILE
    (es decir, los que realmente se pueden llamar sin aprovisionamiento
    dedicado, que es como los usa KiroDocs a través de la Converse API).

Uso:
    python listar_modelos.py [region]

Si no se especifica región, usa AWS_DEFAULT_REGION o "us-east-1".

Requiere credenciales de AWS válidas con permiso `bedrock:ListFoundationModels`.
"""

import sys

import boto3
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError


def listar_modelos_invocables(region: str) -> None:
    cliente = boto3.client("bedrock", region_name=region)

    respuesta = cliente.list_foundation_models()
    modelos = respuesta.get("modelSummaries", [])

    if not modelos:
        print(f"No se encontraron modelos en la región '{region}'.")
        return

    # Filtra solo modelos activos que soporten invocación ON_DEMAND o
    # mediante Inference Profile (cross-region), que es lo que usa la app.
    modelos_utilizables = [
        m
        for m in modelos
        if m.get("modelLifecycle", {}).get("status") == "ACTIVE"
        and (
            "ON_DEMAND" in m.get("inferenceTypesSupported", [])
            or "INFERENCE_PROFILE" in m.get("inferenceTypesSupported", [])
        )
    ]

    modelos_utilizables.sort(key=lambda m: (m.get("providerName", ""), m.get("modelId", "")))

    print(f"Región: {region}")
    print(f"Modelos activos e invocables: {len(modelos_utilizables)} de {len(modelos)} totales\n")

    proveedor_actual = None
    for modelo in modelos_utilizables:
        proveedor = modelo.get("providerName", "Desconocido")
        if proveedor != proveedor_actual:
            print(f"\n== {proveedor} ==")
            proveedor_actual = proveedor

        tipos = ", ".join(modelo.get("inferenceTypesSupported", []))
        modalidades_salida = ", ".join(modelo.get("outputModalities", []))
        streaming = "sí" if modelo.get("responseStreamingSupported") else "no"

        print(f"  - {modelo.get('modelId')}")
        print(f"      Nombre: {modelo.get('modelName')}")
        print(f"      Tipos de inferencia soportados: {tipos}")
        print(f"      Salida: {modalidades_salida} | Streaming: {streaming}")


def main() -> int:
    region = sys.argv[1] if len(sys.argv) > 1 else None
    if not region:
        session = boto3.Session()
        region = session.region_name or "us-east-1"

    try:
        listar_modelos_invocables(region)
    except NoCredentialsError:
        print(
            "❌ No se encontraron credenciales de AWS. Configura `aws configure` "
            "o las variables de entorno AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY."
        )
        return 1
    except ClientError as error:
        codigo = error.response.get("Error", {}).get("Code", "Desconocido")
        mensaje = error.response.get("Error", {}).get("Message", str(error))
        print(f"❌ Error de AWS ({codigo}): {mensaje}")
        return 1
    except BotoCoreError as error:
        print(f"❌ Error de conexión con AWS: {error}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())

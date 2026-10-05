# Glosario de comandos del Makefile — Lab Sesión 06

Qué hace cada `make <comando>`, qué comando real ejecuta por debajo y qué significan los términos que aparecen. `make` solo es un atajo: antes de cada comando imprime el comando real, así que puedes copiarlo y ejecutarlo a mano. Para ver la lista viva usa `make help`.

> **Terraform no está en el Makefile.** `init`, `plan`, `apply`, `destroy` y `output` se ejecutan directamente con `terraform -chdir=infra ...` (ver [guia_deploy.md](../deploy/guia_deploy.md#4-deploy)). El Makefile solo cubre Docker, AWS CLI y los scripts del lab.

## 1. Comandos

La columna **Stack** indica si el comando necesita el stack ya desplegado (lee de Terraform el bucket, el repositorio ECR, el Crawler, etc.).

### Preparación

| Comando | Qué hace | Comando real | Stack |
|---|---|---|---|
| `make help` | Lista los comandos con su descripción | `awk` sobre el propio Makefile | No |
| `make preflight` | Comprueba que Docker, AWS CLI, Terraform y tus credenciales funcionan | `docker version`, `aws --version`, `terraform version`, `aws sts get-caller-identity` | No |

### Imagen del contenedor (Docker y ECR)

| Comando | Qué hace | Comando real | Stack |
|---|---|---|---|
| `make ecr-login` | Autentica Docker contra ECR (el token dura 12 horas) | `aws ecr get-login-password \| docker login --username AWS --password-stdin <registry>` | Sí (repositorio) |
| `make docker-build TAG=1.0.0` | Construye la imagen de la Lambda con el código de `src/lambdas/validator/app.py` | `docker build --platform linux/amd64 --provenance=false -f docker/validator/Dockerfile -t validator:<TAG> .` | No |
| `make docker-push TAG=1.0.0` | Etiqueta la imagen local con la URL del repositorio y la sube (hace `ecr-login` antes) | `docker tag …` y `docker push <repo>:<TAG>` | Sí (repositorio) |
| `make image-publish TAG=1.0.0` | Construye y sube **solo si el tag no está ya en ECR**; si existe, lo omite y avisa | `aws ecr describe-images` y, si falta, `docker-build` + `docker-push` | Sí (repositorio) |
| `make ecr-digest TAG=1.0.0` | Muestra el tag y el digest (`sha256:…`) de una imagen ya subida | `aws ecr describe-images --query …` | Sí (repositorio) |
| `make docker-run-local TAG=1.0.0` | Ejecuta la imagen en tu máquina con el emulador de Lambda, en `localhost:9000` | `docker run --rm -p 9000:8080 validator:<TAG>` | No |
| `make local-invoke PAYLOAD='{…}'` | Envía un evento JSON al emulador (en otra terminal, con `docker-run-local` activo) | `curl -XPOST http://localhost:9000/2015-03-31/functions/function/invocations -d '<PAYLOAD>'` | No |

### Datos y disparo del pipeline

| Comando | Qué hace | Comando real | Stack |
|---|---|---|---|
| `make gen-orders` | Genera CSV nuevos en `data/generated/`. El nombre lleva un sufijo aleatorio (`orders_2026_10_07_a1b2c3.csv`), así que cada ejecución es una clave distinta en S3 y no pisa muestras ni cargas anteriores; el primer `order_id` sale de la hora (milisegundos), así que tampoco se repiten entre ejecuciones | `uv run python scripts/generate_orders.py` | No |
| `make upload FILE=<ruta>` | Sube un archivo a `raw/` (o al prefijo de `PREFIX`). Subir a `raw/` un `.csv` **dispara el pipeline** | `aws s3 cp <FILE> s3://<bucket>/<PREFIX>` | Sí (bucket) |
| `make upload-generated` | Sube todos los CSV de `data/generated/` a `raw/` | `aws s3 cp data/generated s3://<bucket>/raw/ --recursive --exclude "*" --include "*.csv"` | Sí (bucket) |
| `make smoke` | Prueba rápida: sube un CSV válido y uno inválido de `data/samples/` | Dos veces `make upload` | Sí (bucket) |

### Observación y verificación del resultado

| Comando | Qué hace | Comando real | Stack |
|---|---|---|---|
| `make executions` | Últimas 10 ejecuciones de Step Functions con su estado (`SUCCEEDED`, `FAILED`…) | `aws stepfunctions list-executions` | Sí (state machine) |
| `make crawler-status` | Estado del Crawler de Glue (`RUNNING`, `STOPPING`, `READY`) | `aws glue get-crawler --query Crawler.State` | Sí (Crawler) |
| `make crawler-start` | Lanza el Crawler a mano. Normalmente no hace falta: Step Functions lo inicia tras cada archivo válido | `aws glue start-crawler` | Sí (Crawler) |
| `make athena-query` | Ejecuta una consulta SQL en Athena y espera e imprime el resultado. Por defecto, filas y total por `status` | `aws athena start-query-execution`, `get-query-execution` (en bucle) y `get-query-results` | Sí (workgroup, base) |
| `make e2e` | Verificación completa con el SDK de Python: sube archivos de prueba, espera a Step Functions y comprueba S3, Crawler, catálogo y Athena. Tarda unos minutos | `uv run python scripts/check_deployed_pipeline.py` | Sí |

### Calidad del código

| Comando | Qué hace | Comando real | Stack |
|---|---|---|---|
| `make test` | Ejecuta los tests locales (excluye los marcados `cloud`, que necesitan AWS) | `uv run python scripts/testing/run_pytest.py` | No |
| `make lint` | Revisa el estilo y errores del código Python | `uv run python scripts/testing/run_ruff_check.py` | No |

### Guardas internas (no se usan solas)

`require-tag`, `require-repo`, `require-crawler`, `require-athena` y `require-lambda-src` no hacen trabajo: comprueban que exista un valor o un archivo antes de que otro comando continúe, y si falta algo imprimen qué hacer. Por eso verás mensajes como `BUCKET is empty` cuando el stack aún no está desplegado.

## 2. Variables

Se pasan al final del comando: `make upload FILE=data/samples/orders_2026_10_05.csv`.

| Variable | Por defecto | Para qué sirve |
|---|---|---|
| `TAG` | (sin valor) | Versión de la imagen. Obligatoria en los comandos de imagen. Nunca `latest` (ver *tag inmutable*) |
| `FILE` | (sin valor) | Archivo a subir con `make upload` |
| `PREFIX` | `raw/` | Carpeta de destino en el bucket. Fuera de `raw/` el pipeline no se dispara |
| `PAYLOAD` | `{}` | Evento JSON que envía `make local-invoke` |
| `ATHENA_SQL` | Filas y total por `status` | Consulta que ejecuta `make athena-query` |
| `REGION` | `AWS_DEFAULT_REGION` o `us-east-1` | Región de AWS |
| `PYTHON_VERSION` | `3.13` | Versión de Python de la imagen base |
| `PLATFORM` | `linux/amd64` | Arquitectura de la imagen; debe coincidir con la de la Lambda (`x86_64`) |
| `IMAGE_NAME` | `validator` | Nombre de la imagen en tu máquina |
| `LOCAL_PORT` | `9000` | Puerto del emulador local |
| `BUCKET`, `REPO_URI`, `CRAWLER`, `GLUE_DB`, `ATHENA_WORKGROUP`, `STATE_MACHINE_ARN` | Salen de los *outputs* de Terraform | Datos del stack desplegado. Puedes forzarlos a mano, p. ej. `make upload BUCKET=mi-bucket FILE=…` |

## 3. Términos

**Athena.** Servicio que ejecuta SQL directamente sobre archivos en S3. Usa un *workgroup* propio del lab (`s6-lab-dev-wg`) y guarda sus resultados en otro bucket.

**ARN.** Identificador único de un recurso de AWS (por ejemplo, el de la máquina de estados que usa `make executions`).

**Bucket.** Contenedor de S3. El del lab tiene dos carpetas lógicas: `raw/` (entrada) y `processed/orders/` (salida validada).

**Crawler (Glue).** Recorre `processed/orders/`, deduce las columnas y crea la tabla `orders` en el Data Catalog. Sin esa tabla Athena no sabe leer los CSV.

**Data Catalog.** Registro de bases y tablas de Glue. La base del lab es `s6_lab_db`.

**Digest.** Huella `sha256:…` del contenido exacto de una imagen. El tag es un nombre legible que se puede mover; el digest no cambia. Lo muestra `make ecr-digest`.

**Ejecución (Step Functions).** Cada archivo subido a `raw/` inicia una ejecución de la máquina de estados. `make executions` las lista.

**ECR.** Registro de imágenes de contenedor de AWS. La Lambda se crea a partir de una imagen que debe existir ahí **antes** de desplegarla.

**Emulador de Lambda.** Incluido en la imagen base de AWS; permite probar la función en tu máquina con `make docker-run-local` y `make local-invoke`, sin tocar AWS.

**Idempotente.** Que repetirlo no cambia el resultado. Ejemplos: `make image-publish` (omite el push si el tag existe) y el pipeline (la salida lleva el mismo nombre que la entrada, así que reprocesar un archivo no duplica filas).

**Imagen (Docker).** Paquete con el código y sus dependencias que usa la Lambda. Se construye con `make docker-build`.

**`linux/amd64` y `--provenance=false`.** Opciones del `docker build`: la primera fija la arquitectura de la Lambda (`x86_64`) y la segunda evita metadatos extra que Lambda rechaza (`InvalidImage`).

**Lambda validadora.** La función del pipeline: lee cada CSV de `raw/`, lo valida (columnas, extensión, `amount` numérico…) y, si es válido, escribe una copia limpia en `processed/orders/`. Qué reglas aplica y qué devuelve: [README](../../README.md#qué-hace-la-lambda-validadora).

**Marcador `cloud`.** Etiqueta de pytest para los tests que necesitan AWS. `make test` los excluye.

**Output (Terraform).** Valor que Terraform publica tras desplegar (bucket, repositorio, Crawler…). El Makefile los lee, sin modificarlos, para no pedirte esos nombres.

**Prefijo.** Parte inicial de la clave de un objeto de S3 (`raw/`). La regla de EventBridge solo reacciona a claves `raw/*.csv`.

**QueryExecutionId.** Identificador de una consulta de Athena. `make athena-query` lo imprime y lo usa para esperar y leer el resultado.

**ruff.** Herramienta que revisa el estilo y errores del código (`make lint`).

**Stack.** El conjunto de recursos de AWS que crea Terraform en `infra/`.

**Tag inmutable.** El repositorio ECR no permite sobrescribir un tag. Para publicar código nuevo hay que usar un tag **nuevo** (`make image-publish TAG=1.0.1`) y luego apuntar la Lambda a él con Terraform. Repetir el mismo tag no actualiza la Lambda.

**`uv`.** Gestor de Python del proyecto. `uv run …` ejecuta el comando en el entorno del repo con sus dependencias.

## 4. Flujo típico

```bash
make preflight                          # 1. ¿está todo listo?
make image-publish TAG=1.0.0            # 2. imagen en ECR (entre los dos apply de Terraform)
make gen-orders                         # 3. datos nuevos
make upload-generated                   # 4. dispara el pipeline
make executions                         # 5. ¿terminó en SUCCEEDED?
make crawler-status                     # 6. espera a READY
make athena-query                       # 7. consulta el resultado
```

Más detalle en [demo_consola_aws.md](demo_consola_aws.md), [guia_deploy.md](../deploy/guia_deploy.md) y [guia_docker.md](../deploy/guia_docker.md).

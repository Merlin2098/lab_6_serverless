# Guía de deploy — Lab Sesión 06 (Serverless, orquestación y contenedores)

Cómo desplegar, probar y destruir el stack del laboratorio en una cuenta de AWS. Para lo específico de Docker y ECR (build, push, renovar sesión) ver [guia_docker.md](guia_docker.md). Para el recorrido del alumno por la consola ver [lab/demo_consola_aws.md](../lab/demo_consola_aws.md), y para qué hace cada `make`, el [glosario de comandos](../lab/glosario_comandos.md). El mapa del pipeline está en [architecture.png](../architecture/architecture.png).

## 1. Qué se despliega

```text
S3 raw/*.csv -> EventBridge -> Step Functions -> Lambda (imagen en ECR) -> S3 processed/orders/
                                  y luego: StartCrawler -> Glue Crawler -> Data Catalog -> Athena
```

Un solo `terraform apply` completo (precedido de la imagen en ECR, ver sección 4) crea, en `us-east-1`:

| Módulo (`infra/modules/`) | Recursos principales |
|---|---|
| `storage` | Bucket de datos (cifrado, privado) con notificaciones a EventBridge |
| `registry` | Repositorio ECR (tags inmutables) |
| `compute` | Lambda validadora (imagen), su rol IAM y su log group |
| `orchestration` | State machine Standard (Retry + Catch), su rol y su log group |
| `events` | Regla de EventBridge `raw/*.csv` y su rol |
| `catalog` | Base `s6_lab_db`, Crawler, workgroup de Athena y su bucket de resultados |

Todos los recursos llevan tags del lab (`Project`, `Course`, `Session`, `Lab`, `Environment`, `Owner`, `ManagedBy`, `CostCenter`, `Component`) y todo lo que puede bloquear un `destroy` tiene `force_destroy` / `force_delete`.

## 2. Requisitos

| Requisito | Detalle |
|---|---|
| Terminal | **Git Bash** (el Makefile usa `bash`) |
| Herramientas | GNU Make, Docker Desktop (con el daemon activo), AWS CLI v2, Terraform ≥ 1.6, `uv` (para `make test` y `make lint`) |
| Cuenta AWS | Credenciales con permisos para crear IAM, Lambda, ECR, S3, Step Functions, EventBridge, Glue, Athena y CloudWatch Logs |
| Región | `us-east-1`. Mantén alineados `AWS_DEFAULT_REGION` (lo usa el Makefile) y `aws_region` de Terraform |
| Cuotas | Las cuentas nuevas tienen cuotas bajas de Lambda: revísalas en Service Quotas antes de la sesión |
| Costo | Mínimo (Lambda, ECR, Glue Crawler, Athena). Destruye el stack al terminar |

## 3. Preparación (una vez)

1. **Credenciales de AWS.** El Makefile no las lee de ningún archivo: usan las del entorno o de `aws configure`. Si las guardas en `.env.credentials` (formato `KEY=VALUE`, ver `.env.example`), cárgalas en tu terminal:

   ```bash
   set -a; source .env.credentials; set +a
   ```

   Si son temporales (con `AWS_SESSION_TOKEN`), caducan: ver "Renovar la sesión" en [guia_docker.md](guia_docker.md#5-renovar-la-sesión).

2. **Comprobar el entorno:**

   ```bash
   make preflight        # docker, aws, terraform y aws sts get-caller-identity
   ```

   Debe terminar sin errores y mostrar tu cuenta. Si falla `docker version`, abre Docker Desktop.

3. **Si Terraform falla al hablar con el provider** con `x509: certificate signed by unknown authority` (visto en algunos Windows), ejecuta en esa terminal:

   ```bash
   export TF_DISABLE_PLUGIN_TLS=1
   ```

   Solo desactiva TLS en el enlace local entre `terraform` y su propio proceso de provider.

4. **Opcional: variables.** Copia `infra/terraform.tfvars.example` a `infra/terraform.tfvars` si quieres cambiar el prefijo, el owner o el centro de costos. Los valores por defecto sirven para el lab. El backend de estado es **local** (`infra/terraform.tfstate`): no lo borres ni lo edites a mano.

5. **Opcional: descargar la imagen base antes** para no esperar en clase:

   ```bash
   docker pull public.ecr.aws/lambda/python:3.13
   ```

## 4. Deploy

Terraform se ejecuta directamente, sin `make` por en medio (el Makefile solo envuelve Docker y AWS CLI). Desde la raíz del repo; Terraform pide escribir `yes` en cada `apply`:

```bash
terraform -chdir=infra init
terraform -chdir=infra plan                              # opcional: revisa qué se va a crear
terraform -chdir=infra apply -target=module.registry     # 1. solo el repositorio ECR
make image-publish TAG=1.0.0                             # 2. build + push de la imagen
terraform -chdir=infra apply                             # 3. el resto, incluida la Lambda
```

| Paso | Comando | Por qué |
|---|---|---|
| 1 | `terraform -chdir=infra apply -target=module.registry` | Crea solo el repositorio ECR |
| 2 | `make image-publish TAG=1.0.0` | Construye la imagen y la sube a ECR (la omite si el tag ya existe) |
| 3 | `terraform -chdir=infra apply` | Crea el resto, incluida la Lambda desde la imagen |

El orden importa: la Lambda se crea desde una imagen y esta **debe estar en ECR antes** del `apply` completo. Si lo ejecutas antes, falla con `Source image ... does not exist`. Repetir los tres pasos tras un fallo es seguro (el paso 2 omite el push si el tag ya existe).

El tag por defecto es `1.0.0` (variable `image_tag` de Terraform). Para otro, usa el mismo valor en el paso 2 y en el 3: `make image-publish TAG=1.0.1` y `terraform -chdir=infra apply -var image_tag=1.0.1` (o fíjalo en `infra/terraform.tfvars`).

## 5. Verificar el deploy

```bash
terraform -chdir=infra output   # outputs: bucket, ECR, state machine, crawler, workgroup...
make smoke            # sube orders_2026_10_04.csv (válido) y orders_invalid.csv
make executions       # últimas ejecuciones y su estado
```

Espera 1–2 minutos tras el deploy: las notificaciones de S3 a EventBridge tardan en activarse. Resultado esperado:

| Archivo | Ejecución |
|---|---|
| `orders_2026_10_04.csv` | `SUCCEEDED`, y aparece `processed/orders/orders_2026_10_04.csv` |
| `orders_invalid.csv` | `FAILED` con `InvalidFile`, sin archivo de salida |

Prueba de extremo a extremo con el SDK de Python (boto3):

```bash
make e2e              # equivale a: uv run python scripts/check_deployed_pipeline.py
```

El script `scripts/check_deployed_pipeline.py` sube los archivos de prueba, espera a Step Functions y comprueba cada servicio: los 3 archivos válidos terminan en `SUCCEEDED`, se escriben en `processed/orders/` y pasan por el estado `StartCrawler`; los inválidos fallan con `InvalidFile` sin salida; `prueba.json`, `otra/prueba.csv` y un `.CSV` en mayúsculas **no** disparan nada; una clave con espacios y un archivo con BOM se procesan bien; reprocesar un archivo no duplica datos; y el Crawler, el Data Catalog y Athena devuelven el resultado esperado. Imprime `PASS`/`FAIL` por comprobación, termina con código distinto de 0 si algo falla y borra los archivos temporales que subió (`--keep` los conserva, `--skip-catalog` omite el Crawler y Athena). Tarda varios minutos. Resultado esperado: `18 passed, 0 failed`. Espera exactamente los 3 archivos de muestra en `processed/orders/`: si subiste datos tuyos, la comprobación de Athena fallará hasta que los borres de `raw/` y `processed/orders/`.

Pruebas automáticas:

```bash
make test                                                   # unitarias y de infra (sin AWS)
uv run python scripts/testing/run_cloud_tests.py            # contra el stack desplegado
```

Los tests `cloud` suben archivos reales, esperan a Step Functions, ejecutan el Crawler y consultan Athena; pueden tardar varios minutos. Se saltan solos si no hay credenciales o stack.

## 6. Operación

| Quiero... | Comando |
|---|---|
| Subir un archivo de prueba | `make upload FILE=data/samples/orders_2026_10_05.csv` |
| Generar CSV propios y dispararlos | `make gen-orders` y luego `make upload-generated`. Cada archivo lleva un sufijo aleatorio (`orders_2026_10_05_3a62ab.csv`) y el primer `order_id` sale de la hora en milisegundos, así que ni pisa muestras o cargas anteriores ni repite ids. Otro tamaño o un archivo inválido: `python scripts/generate_orders.py --help` |
| Subirlo fuera de `raw/` | `make upload FILE=data/samples/prueba.csv PREFIX=otra/` |
| Cambiar el código de la Lambda | Tag **nuevo**: `make image-publish TAG=1.0.1` y luego `terraform -chdir=infra apply -var image_tag=1.0.1`. Repetir el paso 2 con el mismo tag **no** publica el cambio (ver [guia_docker.md](guia_docker.md#4-tags-digest-e-inmutabilidad)) |
| Provocar / corregir el fallo de Troubleshoot | `terraform -chdir=infra apply -var inject_fault=true` / `-var inject_fault=false` (esperar 20–30 s por IAM; añade `-var image_tag=...` si usas un tag distinto de `1.0.0`) |
| Catalogar y consultar el resultado | El Crawler lo inicia Step Functions tras cada archivo válido: `make crawler-status` (hasta `READY`) y `make athena-query`. A mano: `make crawler-start` |
| Ver el digest de una imagen | `make ecr-digest TAG=1.0.0` |
| Ver todos los comandos | `make help` |

El resultado esperado de `make athena-query` tras subir solo los tres archivos válidos de muestra es COMPLETED 6 / 1290.75 y CANCELLED 1 / 99.90. Cada archivo generado y subido suma sus filas a esos totales.

## 7. Destruir el stack

```bash
terraform -chdir=infra destroy   # pide confirmación (yes)
```

Elimina todo sin pasos manuales: los buckets de S3, el workgroup de Athena y el repositorio ECR se vacían solos (`force_destroy` / `force_delete`). Comprueba después:

```bash
terraform -chdir=infra output   # no debe mostrar outputs
```

Excepción conocida: los logs del Crawler van al log group compartido `/aws-glue/crawlers`, que no gestiona este stack y por tanto no se borra (ver [ADR 0001](../internal/adr/0001-pipeline-serverless-orientado-a-eventos.md)). Las imágenes locales de Docker tampoco se borran: ver [guia_docker.md](guia_docker.md#8-limpieza).

## 8. Problemas frecuentes

| Síntoma | Causa | Qué hacer |
|---|---|---|
| `InvalidParameterValueException: Source image ... does not exist` | Se aplicó la Lambda sin la imagen en ECR | Publicar la imagen (`make image-publish TAG=1.0.0`) y repetir el `apply` completo |
| `REPO_URI is empty` / `ECR repository does not exist` | El repositorio aún no existe | Paso 1 de la sección 4 (`apply -target=module.registry`) |
| `The security token included in the request is invalid` (`InvalidClientTokenId`) / `ExpiredToken` | Credenciales de AWS caducadas o incorrectas | Renovarlas: [guia_docker.md](guia_docker.md#5-renovar-la-sesión) |
| `x509: certificate signed by unknown authority` en Terraform | Handshake TLS local con el provider | `export TF_DISABLE_PLUGIN_TLS=1` |
| `failed to connect to the docker API` | Docker Desktop apagado | Abrirlo y esperar a que arranque |
| `role defined for the function cannot be assumed by Lambda` al crear la Lambda | Propagación de IAM | Esperar 30 s y repetir `terraform -chdir=infra apply` |
| `make smoke` no genera ejecuciones | EventBridge aún no activo, o la clave no es `raw/*.csv` | Esperar 1–2 min; revisar `make executions` |
| `CRAWLER is empty` / `BUCKET is empty` | El stack no está desplegado (los valores salen de los outputs de Terraform) | Desplegar (sección 4), o pasar el valor: `make upload BUCKET=...` |
| El Crawler no termina | Tarda | `make crawler-status` hasta `READY` (anota el tiempo real) |
| La ejecución falla en `StartCrawler` con `AccessDeniedException` | Permiso `glue:StartCrawler` del rol de Step Functions aún no propagado | Esperar 30 s y volver a subir el archivo |

## 9. Estructura del repositorio

```text
Makefile                 # atajos de Docker/ECR, AWS CLI y scripts (make help); Terraform va directo
docker/validator/        # Dockerfile de la Lambda (ver guia_docker.md)
src/lambdas/validator/   # código de la Lambda
src/contracts/           # contrato del dataset orders
infra/                   # Terraform: main.tf + modules/{storage,registry,compute,orchestration,events,catalog}
data/samples/            # archivos de prueba (F1, F2, F3, inválidos)
data/generated/          # CSV de make gen-orders (ignorado por git)
scripts/                 # generate_orders.py, check_deployed_pipeline.py (e2e), testing/, python/
tests/                   # lambdas/ y infra/ (locales), aws/ (contra el stack)
docs/specs, docs/plans   # especificación y plan de implementación
docs/internal/adr/       # decisiones de arquitectura
docs/lab/                # recorrido por la consola y glosario de comandos
docs/deploy/             # esta guía y la de Docker
docs/architecture/       # architecture.dot (+ .png/.svg renderizados)
```

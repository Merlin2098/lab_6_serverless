# SPEC — Fase 2: Stack Terraform y servicios del Laboratorio Sesión 06
## Pipeline serverless "listo para deploy"

**Estado:** revisión 2 (ajustes de log groups y duración); pendiente de aprobación final
**Fecha:** 4 de octubre de 2026
**Revisión 2:** (a) nombres propios para los log groups, sin declarar el compartido del Crawler (sección 5.7 y R4); (b) duración objetivo del lab **≤ 45 min** (sección 7).
**Revisión 3 (posterior):** el Makefile ya no envuelve Terraform. Los targets `deploy`, `fault-on`, `fault-off`, `tf-*` y la variable `DEPLOY_TAG` se retiraron; Terraform se ejecuta directo (`terraform -chdir=infra ...`) y el Makefile solo cubre Docker/ECR y AWS CLI. Donde esta spec mencione esos targets (secciones 1, 6 y 7), vale la secuencia de comandos de [guia_deploy.md](../deploy/guia_deploy.md#4-deploy). Además, Step Functions inicia el Crawler (estado `StartCrawler`, ver 3.3 y 3.5) y se añadió `scripts/generate_orders.py` (`make gen-orders`, `make upload-generated`): CSV nuevos con nombre de sufijo único y `order_id` por timestamp. Verificado de extremo a extremo con `make e2e` (18 comprobaciones).
**Spec base:** [SPEC_Laboratorio_Sesion_06_Serverless_Orquestacion_Contenedores.md](SPEC_Laboratorio_Sesion_06_Serverless_Orquestacion_Contenedores.md) (v3 · MVP)
**Fase 1 (hecha):** `docker/validator/` y `Makefile`.
**Alcance de este documento:** Lambda validadora, datos de prueba, Terraform (módulos), IAM, ajustes al Makefile, pruebas, ADR y guía de exploración.

---

## 1. Qué cambia respecto al spec v3

El spec v3 plantea un stack preparado en estado **inicial imperfecto** (patrón `raw/` amplio, sin `Catch`, Lambda .zip) que el alumno modifica durante la sesión. Esta fase adopta otro enfoque, decidido en el brainstorming:

> **El lab viene listo para deploy.** El alumno lo despliega y después analiza por su cuenta cómo se construyó. Lo importante es que vea la **interacción de los servicios en AWS**.

| Decisión | Resultado |
|---|---|
| Estado tras el deploy | **Estado final completo:** filtro `raw/*.csv`, state machine con `Retry` + `Catch`, Lambda desde imagen en ECR, Crawler y Catalog |
| Bloques Modify (M1, M2) y Container | Pasan de **ediciones** a **análisis guiado** y pruebas de comportamiento. El alumno no edita HCL salvo en Troubleshoot |
| Troubleshoot | Se mantiene: fallo de permisos activable con `inject_fault` (`make fault-on` / `make fault-off`) |
| Imagen en ECR | `make deploy` en 3 pasos visibles: apply del repo ECR → build + push → apply completo |
| Athena | El stack crea su propio workgroup y bucket de resultados (el lab no depende de S4) |
| Estructura Terraform | **Módulos por servicio** (ver sección 5) |
| Lambda .zip | **Desaparece.** El estado final solo usa imagen. `package-zip` se retira del Makefile |

Los pendientes 1, 2, 3 y 5 de la sección 15 del spec v3 quedan cerrados por este documento; el 4 (cambio de `package_type`) deja de aplicar al no existir el cambio zip → imagen.

---

## 2. Arquitectura

```text
S3  raw/*.csv
 |  Object Created
 v
EventBridge (regla: wildcard raw/*.csv)  --rol states:StartExecution-->  Step Functions (Standard)
                                                                          |
                                                                          v
                                                            Validate (Task, Retry + Catch)
                                                            Lambda validadora (imagen ECR, x86_64)
                                                            valida y, si es válido, copia a
                                                            processed/orders/<mismo nombre>
                                                                          |
                                                                       IsValid (Choice)
                                                                  /                \
                                                        StartCrawler           InvalidFile (Fail)
                                                  (SDK glue:startCrawler)
                                                            |
                                                     PipelineSucceeded
                                              error inesperado (Catch) -> HandleError (Pass) -> PipelineFailed (Fail)

                       ── catálogo y consulta ──
          S3 processed/orders/ -> Glue Crawler (iniciado por StartCrawler) -> Data Catalog (s6_lab_db.orders) -> Athena (workgroup propio)
```

Región `us-east-1`, backend local, una sola región para ECR, Lambda y regla de EventBridge.

---

## 3. Servicios: comportamiento

### 3.1 S3

- Un bucket de datos con notificaciones a EventBridge **activadas** (`eventbridge = true` en `aws_s3_bucket_notification`).
- Cifrado SSE-S3, bloqueo de acceso público completo, sin versionado (AGENTS.md).
- Prefijos: `raw/` (entrada) y `processed/orders/` (salida).
- `force_destroy = true` (lab; documentado).

### 3.2 EventBridge

Regla en el bus por defecto con este patrón (el nombre del bucket viene del módulo `storage`):

```json
{
  "source": ["aws.s3"],
  "detail-type": ["Object Created"],
  "detail": {
    "bucket": { "name": ["<bucket>"] },
    "object": { "key": [ { "wildcard": "raw/*.csv" } ] }
  }
}
```

- El **evento completo** se pasa a Step Functions (sin input transformer), de modo que el alumno ve `detail.bucket.name` y `detail.object.key` tal como llegan.
- El patrón no cubre `processed/`, por lo que la escritura de la Lambda **no re-dispara** el pipeline (invocación recursiva evitada por diseño).
- `raw/*.csv` también coincide con subcarpetas (`raw/a/b.csv`); la Lambda usa solo el nombre base para la clave de salida.

### 3.3 Step Functions (Standard)

ASL final: el de la sección 6 del spec v3 **con M2 incluido**.

- `Validate`: `arn:aws:states:::lambda:invoke`, `Payload.$ = "$"`, `ResultPath = "$.validation"`.
- `Retry` para `Lambda.ServiceException`, `Lambda.AWSLambdaException`, `Lambda.SdkClientException` y `Lambda.TooManyRequestsException` (2 s, 3 intentos, backoff 2.0).
- `Catch` para `States.ALL` con `ResultPath = "$.error"` hacia `HandleError` (Pass) → `PipelineFailed` (Fail, `Error = "PipelineError"`).
- `IsValid` (Choice) sobre `$.validation.Payload.valid`; el default va a `InvalidFile` (Fail, `Error = "InvalidFile"`).
- `StartCrawler` (rama válida de `IsValid`): `arn:aws:states:::aws-sdk:glue:startCrawler` (integración directa con el SDK, sin Lambda), `Parameters = {Name = <crawler>}`, `ResultPath = "$.crawler"`. No espera a que el Crawler termine. `Catch` de `Glue.CrawlerRunningException` hacia `PipelineSucceeded` (ya hay una ejecución en curso, no es un fallo) y de `States.ALL` hacia `HandleError`. El rol de la máquina de estados recibe `glue:StartCrawler` solo sobre el ARN de ese Crawler. Los archivos inválidos no llegan a este estado.
- `PipelineSucceeded` (Succeed).
- Logging de ejecución a un log group propio, con el prefijo recomendado por Step Functions: `/aws/vendedlogs/states/<prefijo>-pipeline` (`level = ALL`, `include_execution_data = true`).
- La definición vive en un archivo `.asl.json.tftpl` dentro del módulo, no embebida en HCL, para que sea legible por sí sola.

### 3.4 Lambda validadora

**Código:** `src/lambdas/validator/app.py` (un solo archivo; es el que copia el Dockerfile de la Fase 1).

**Contrato de entrada:** el evento de EventBridge tal como lo entrega Step Functions (`detail.bucket.name`, `detail.object.key`). No se pasa el contenido del archivo (límite de 256 KiB por estado).

**Contrato de salida:**

```json
{ "valid": true,  "records": 3, "output": "processed/orders/orders_2026_10_04.csv" }
{ "valid": false, "reason": "missing_columns: amount" }
```

**Reglas de validación** (en este orden, la primera que falla corta):

1. La clave termina en `.csv`.
2. El archivo no está vacío (tiene al menos el encabezado y una fila de datos).
3. Están presentes las columnas `order_id`, `customer_id`, `amount`, `status`.
4. Cada `amount` es numérico finito (`Decimal`).

**Escritura:** si es válido, copia el objeto a `processed/orders/<nombre base>` (la **misma clave** en cada reproceso → idempotencia; no duplica datos). Si es inválido **no** escribe nada.

**Errores:** los errores de validación **no son excepciones** (devuelven `valid: false` y el `Choice` decide). Los errores inesperados (p. ej. `AccessDenied` en `PutObject`) **se propagan como excepción**, para que el `Catch` los capture en `$.error` y aparezcan en CloudWatch.

**Estructura interna:** una función pura `validate_csv(key, text) -> ValidationResult` (sin I/O, probada con pytest) y un `handler` fino que lee de S3, llama a la función y escribe el resultado.

**Configuración (variables de entorno, no hardcodeada):** `PROCESSED_PREFIX` (`processed/orders/`) y `REQUIRED_COLUMNS` (`order_id,customer_id,amount,status`).

**Límite conocido:** lee el archivo completo en memoria. `# debt:` con techo en el orden de decenas de MB y disparador de mejora: archivos de varios GB (pregunta de reflexión 5 del spec v3).

**Recursos Lambda:** `package_type = "Image"`, `x86_64`, 256 MB, timeout 30 s, log group explícito `/aws/lambda/<nombre>` con `retention_in_days`.

### 3.5 Glue Crawler, Data Catalog y Athena

- **Base de Glue:** `s6_lab_db` (variable `glue_database_name`).
- **Crawler:** apunta a `s3://<bucket>/processed/orders/`, sin programación: lo inicia el estado `StartCrawler` de Step Functions tras cada archivo válido (también se puede lanzar a mano con `make crawler-start`). Usa un **classifier CSV personalizado** con `contains_header = "PRESENT"` (encabezado forzado), para no depender de la detección automática (pendiente 3 del spec v3). Tabla resultante: `orders`.
- **Athena:** workgroup propio (`<prefijo>-lab`) con `enforce_workgroup_configuration = true`, bucket de resultados propio (cifrado SSE-S3, sin acceso público) y `force_destroy = true`.
- Consulta de verificación: la de la sección 10 del spec v3. Resultado esperado: tabla de la sección 3 del spec v3 (COMPLETED 6 / 1290.75; CANCELLED 1 / 99.90; total 7 filas).

---

## 4. Datos de prueba

Carpeta `data/samples/`, con los archivos de la sección 3 del spec v3:

| Archivo | Contenido | Resultado esperado |
|---|---|---|
| `orders_2026_10_04.csv` (F1) | 1001–1003, COMPLETED | `Succeed` |
| `orders_2026_10_05.csv` (F2) | 1004 COMPLETED 210.00; 1005 CANCELLED 99.90 | `Succeed` |
| `orders_2026_10_06.csv` (F3) | 1006 COMPLETED 75.00; 1007 COMPLETED 410.25 | `Succeed` (con `inject_fault=true` falla) |
| `orders_invalid.csv` | `amount` no numérico | `Fail` (`InvalidFile`), sin salida |
| `prueba.json` | JSON vacío | **No dispara** (no cumple `raw/*.csv`) |
| `prueba.csv` | CSV vacío | Subido a `otra/`: **no dispara**; subido a `raw/`: `InvalidFile` |
| `prueba_invalida.csv` | Columna faltante | `InvalidFile` |

Los totales esperados de Athena se calculan solo con F1, F2 y F3; los archivos inválidos y de prueba no aportan filas.

---

## 5. Terraform

### 5.1 Estructura

```text
infra/
  main.tf             # composición de módulos + locals + common_tags
  budget.tf           # budget opcional (movido desde main.tf; sin cambios de comportamiento)
  variables.tf  outputs.tf  providers.tf  terraform.tfvars.example
  modules/
    storage/          # bucket de datos + notificaciones a EventBridge
    registry/         # ECR
    compute/          # Lambda + execution role + log group
    orchestration/    # state machine + rol + log group
    events/           # regla EventBridge + rol de invocación
    catalog/          # base Glue + crawler + rol + workgroup Athena + bucket de resultados
```

De la plantilla actual **se retira** lo que ya no aplica: bucket de artefactos, rol de Glue Job, variable `artifact_path` y sus recursos asociados. Se **conservan** `locals`, `common_tags`, el log group con retención y el budget opt-in (`enable_budget_guardrail`, default `false`).

Cada módulo expone `log_group_name`, `log_group_arn` y `resource_arn` cuando crea recursos que producen logs o ARN relevantes (regla de AGENTS.md).

### 5.2 Módulos

| Módulo | Recursos | Entradas clave | Salidas clave |
|---|---|---|---|
| `storage` | `aws_s3_bucket`, cifrado, public access block, `aws_s3_bucket_notification` (EventBridge) | `bucket_name`, `tags` | `bucket_name`, `bucket_arn` |
| `registry` | `aws_ecr_repository` (`IMMUTABLE`, `force_delete = true`), `aws_ecr_repository_policy` | `name`, `tags` | `repository_url`, `repository_arn` |
| `compute` | `aws_lambda_function` (Image), `aws_iam_role` + políticas, `aws_cloudwatch_log_group` | `image_uri`, `bucket_arn`, `processed_prefix`, `inject_fault`, `log_retention_days` | `function_arn`, `function_name`, `role_arn`, `log_group_*` |
| `orchestration` | `aws_sfn_state_machine`, rol, `aws_cloudwatch_log_group` | `lambda_arn`, `log_retention_days` | `state_machine_arn`, `log_group_*` |
| `events` | `aws_cloudwatch_event_rule`, `aws_cloudwatch_event_target`, rol | `bucket_name`, `state_machine_arn` | `rule_arn` |
| `catalog` | `aws_glue_catalog_database`, `aws_glue_classifier`, `aws_glue_crawler`, rol, bucket de resultados, `aws_athena_workgroup` | `bucket_name`, `bucket_arn`, `database_name`, `tags` | `crawler_name`, `database_name`, `workgroup_name`, `results_bucket_name` |

Dependencias: `storage` + `registry` → `compute` → `orchestration` → `events`; `catalog` depende de `storage`.

### 5.3 Variables raíz (config, no hardcodeo)

`project_name` (default `s6-lab`), `environment`, `owner`, `cost_center`, `aws_region`, `tags`, `log_retention_days`, `glue_database_name` (`s6_lab_db`), `image_tag` (`1.0.0`), `inject_fault` (`false`) y las del budget existentes. La versión de Python de la imagen **no** es una variable de Terraform: vive en el Makefile y el Dockerfile.

### 5.4 Outputs raíz (contrato con el Makefile)

`ecr_repository_url`, `bucket_name`, `crawler_name`, `glue_database_name`, `athena_workgroup`, `state_machine_arn`, `state_machine_log_group_name`, `lambda_function_name`, `event_rule_name`, `log_group_name`, `log_group_arn` (más `budget_name` y `budget_alert_sns_arn` de la plantilla).

> `log_group_name` y `log_group_arn` en la raíz exponen los de la Lambda; los de los demás módulos están disponibles como salidas del módulo.

### 5.5 IAM (mínimo privilegio, todo declarado en Terraform)

| Componente | Permisos | Dónde se declara |
|---|---|---|
| EventBridge → Step Functions | `states:StartExecution` sobre la state machine | `events` |
| Step Functions → Lambda | `lambda:InvokeFunction` sobre la validadora | `orchestration` |
| Step Functions → logs | Acciones de entrega de logs de Step Functions (**requieren `Resource: "*"` por la API del servicio**; justificado con comentario) | `orchestration` |
| Lambda (execution role) | Logs sobre su log group; `s3:GetObject` sobre `raw/*`; `s3:PutObject` sobre `processed/orders/*` (**la que quita `inject_fault`**) | `compute` |
| ECR → Lambda | Política de repositorio: `ecr:BatchGetImage`, `ecr:GetDownloadUrlForLayer` para `lambda.amazonaws.com` | `registry` |
| Crawler | `AWSGlueServiceRole` + lectura de `processed/orders/` | `catalog` |

Regla de colocación cross-module (AGENTS.md): cada política se declara en el módulo donde el ARN destino es conocido. Los ARN que cruzan módulos (bucket, state machine, función) llegan como variables; no hay dependencias circulares.

Ningún `Action: "*"`. Se **valida el IAM** de cada rol antes del `apply` (AGENTS.md).

### 5.6 Fallo inyectado

`var.inject_fault = true` hace que `compute` **omita** el statement `s3:PutObject` sobre `processed/orders/*` (con `dynamic "statement"`). El resto del stack no cambia.

Con la variable activa, subir F3 provoca: Lambda → excepción `AccessDenied` → `Catch` → `$.error` → `PipelineFailed`; el detalle está en CloudWatch. `fault-off` restaura la política.

La variable no persiste entre `apply`: un `apply` posterior sin ella vuelve a `false`. Es intencional (el estado seguro es el por defecto).

### 5.7 Guardarraíles transversales (AGENTS.md)

- Log group explícito, con nombre propio por stack y `retention_in_days`, para Lambda (`/aws/lambda/<prefijo>-validator`) y Step Functions (`/aws/vendedlogs/states/<prefijo>-pipeline`). Ninguno puede colisionar con recursos de otras sesiones porque llevan el prefijo del stack.
- **Log group del Crawler: excepción documentada.** Los Crawlers de Glue escriben en `/aws-glue/crawlers`, un log group compartido que gestiona AWS; la documentación consultada solo permite personalizar el nombre en los **Glue Jobs** (`--custom-logGroup-prefix`), no en los Crawlers. Por eso el stack **no declara** ese log group (declararlo choca con el de S4 o lo borra al hacer destroy). Es una excepción a la regla de AGENTS.md, registrada en el ADR y en R4.
- Tags descriptivos del lab en todos los recursos que admiten tags: `Project` (`s6-lab`), `Course` (`aws-data-engineer`), `Session` (`06`), `Lab` (`serverless-orchestration-containers`), `Environment`, `Owner` (`datahackers-bootcamp-da`), `ManagedBy` (`Terraform`) y `CostCenter` (`s6-lab-serverless`), más `Component` por módulo (`storage`, `registry`, `compute`, `orchestration`, `events`, `catalog`). Los valores por defecto genéricos de la plantilla (`engineering`, `data-engineering`) están prohibidos por test.
- `force_destroy = true` en los dos buckets S3 y en el workgroup de Athena, y `force_delete = true` en ECR, para que `terraform destroy` nunca falle por contenido; un test lo impone.
- Sin S3 versioning, sin budget por defecto, sin `terraform.tfstate` modificado manualmente.
- `terraform apply` y `destroy` los ejecuta el usuario (el agente no los corre).

---

## 6. Despliegue y Makefile

### 6.1 `make deploy` (3 pasos visibles)

```text
1. terraform -chdir=infra apply -target=module.registry
2. docker build + push (TAG, por defecto 1.0.0 solo en deploy)
3. terraform -chdir=infra apply -var image_tag=<TAG>
```

El paso 2 es `make image-publish`, **idempotente**: ECR es inmutable, así que si el tag ya existe se omite el build y el push (permite repetir `make deploy` tras un fallo posterior, p. ej. por la propagación de IAM). Los targets que aplican la Lambda (`tf-apply`, `fault-on`, `fault-off`) exigen la imagen en ECR y, si falta, se detienen con un mensaje que remite a `make deploy`, en lugar de dejar que AWS falle con `Source image ... does not exist`.

El `-target` es deliberado: la función necesita la imagen ya publicada. Se documenta en el Makefile y en la guía. `destroy` funciona porque ECR tiene `force_delete` y S3 y Athena tienen `force_destroy`.

### 6.2 Cambios sobre el Makefile de la Fase 1

| Cambio | Detalle |
|---|---|
| Retirar | `package-zip`, `ZIP_PATH` (ya no hay .zip) |
| Añadir | `deploy`, `fault-on`, `fault-off`, `smoke` (sube F1 y el inválido), `executions` (lista las últimas ejecuciones de la state machine con estado) |
| Variable nueva | `DEPLOY_TAG ?= 1.0.0` (usada por `deploy`, `fault-on` y `fault-off` para pasar `-var image_tag`) |

`fault-on` / `fault-off` ejecutan `terraform apply` con `-var inject_fault=...` y piden confirmación, como el resto.

---

## 7. Plan de tiempo propuesto (60 min)

Reemplaza la sección 4 del spec v3. **Duración objetivo: ≤ 45 min** (rev. 2). Los tiempos se irán ajustando; **a validar en ensayo** (build de imagen, crawler y propagación de EventBridge).

| Bloque | Min | Qué hace el alumno |
|---|---:|---|
| 1. Deploy | 10 | `make deploy` (mientras corre el build, el instructor explica la arquitectura); sube F1 y el inválido (`make smoke`); ve `Succeed` y `Fail` en Step Functions |
| 2. Explorar | 10 | Recorre en AWS el evento, el patrón, el ASL, la tabla de IAM y la imagen en ECR (tag y digest), con apoyo de Claude Code para **explicar** |
| 3. Probar | 5 | Sube `prueba.json`, `otra/prueba.csv` y `prueba_invalida.csv`; compara qué dispara y qué no |
| 4. Troubleshoot | 7 | `make fault-on`, sube F3, diagnostica; `make fault-off`, reprocesa F3 |
| 5. Verify | 8 | Crawler → Catalog → Athena; compara con el resultado esperado; idempotencia opcional |
| Cierre | 5 | 3 o 4 preguntas de reflexión |
| **Total** | **45** | |

Orden de recorte si aprieta: (1) bloque 3 pasa a demo; (2) parte de Explorar pasa a demo; (3) el instructor ejecuta el Crawler antes de la sesión y el alumno solo consulta. **No recortar Troubleshoot ni Verify.**

Mitigaciones para el límite de 45 min: la imagen base de Lambda se descarga una sola vez (`docker pull` antes de la clase, parte del pre-flight) y `make deploy` es el único paso largo; el resto son comandos de segundos.

---

## 8. Pruebas

| Tipo | Ubicación | Qué cubre |
|---|---|---|
| Unitarias (pytest, sin AWS) | `tests/lambdas/test_validator.py` | `validate_csv`: extensión, archivo vacío, columnas faltantes, `amount` no numérico, válido, clave de salida determinística |
| Estructura del stack | `tests/aws/` (marcador `cloud`) | Outputs existen; notificación EventBridge activa; patrón de la regla; ASL contiene `Retry` y `Catch`; Lambda con `PackageType = Image`; ningún `Action: "*"` en los roles; log groups con retención |
| End to end | `tests/aws/` (marcador `cloud`) | F1 → `SUCCEEDED`; inválido → `FAILED` (`InvalidFile`) sin salida; resultado de Athena = tabla esperada |
| Calidad | `make lint`, `make test`, `terraform validate`, `terraform fmt -check` | |

Los tests `cloud` se saltan sin credenciales (comportamiento actual del repo) y se reutiliza `tests/aws/aws_session.py`.

---

## 9. Documentación y gobierno

- **ADR** `docs/internal/adr/0001-pipeline-serverless-orientado-a-eventos.md` (título, estado, contexto, decisión, consecuencias): servicios nuevos, estado final desplegado y flujo `make deploy`. Se escribe **antes** de implementar (AGENTS.md).
- **Guía de exploración** `docs/lab/guia_alumno.md`: ruta corta por la consola y por CLI para observar cada interacción (EventBridge → ejecución → Lambda → S3 → Crawler → Athena) y las preguntas de reflexión. Sin ejercicios de edición salvo Troubleshoot.
- Actualizar `terraform.tfvars.example` y `.env.example` si cambian variables.

---

## 10. Riesgos y verificaciones en ensayo

| ID | Riesgo | Mitigación / verificación |
|---|---|---|
| R1 | Tiempo real del `docker build` y del `push` dentro de `make deploy` | Medir; la imagen base y una sola capa mínima lo mantienen corto |
| R2 | Propagación de notificaciones S3 → EventBridge tras el apply (minutos) | Esperar antes de `smoke`; documentar en la guía |
| R3 | El Crawler no infiere tipos o encabezados como se espera | Classifier con encabezado explícito; verificar tipo de `amount` y la suma en Athena (1290.75) |
| R4 | El nombre del log group del Crawler (`/aws-glue/crawlers`) no es configurable según la documentación consultada, y es compartido | **Decisión (rev. 2):** no declararlo; excepción documentada en ADR. Alternativa descartada por ahora: una *security configuration* de Glue con cifrado CloudWatch, que cambia el nombre del log group pero exige una clave KMS (costo y permisos extra). Revisar en el ensayo si se quiere retención propia para los logs del Crawler |
| R5 | `python_version` del Dockerfile no es un runtime vigente de Lambda | Confirmar contra la lista de runtimes antes de la clase (default actual 3.13) |
| R6 | Cuotas reducidas de Lambda en cuentas nuevas | Revisar Service Quotas antes de la sesión |
| R7 | Entrega at-least-once de EventBridge | La clave de salida determinística evita duplicados (cubre pregunta 10) |
| R8 | `terraform apply -target` genera advertencias y puede confundir | Documentado como paso explícito; solo se usa en `deploy` |

---

## 11. Criterios de aceptación

1. `make deploy` termina sin errores en una cuenta limpia y deja el stack completo.
2. F1 → `Succeed`; `orders_invalid.csv` → `Fail` (`InvalidFile`); `processed/orders/orders_2026_10_04.csv` existe y no hay salida del inválido.
3. `prueba.json` y `otra/prueba.csv` **no** disparan ejecuciones; `raw/prueba_invalida.csv` sí y falla.
4. `make fault-on` + F3 → ejecución `Fail` con `$.error` y `AccessDenied` en CloudWatch; `make fault-off` + F3 → `Succeed`.
5. Tras F1, F2 y F3 y el Crawler, la consulta de Athena devuelve COMPLETED 6 / 1290.75 y CANCELLED 1 / 99.90 (7 filas).
6. Reprocesar F1 no cambia los totales.
7. La Lambda corre desde **imagen** y el digest es visible con `make ecr-digest`.
8. `terraform validate`, `terraform fmt -check`, `make lint`, `make test` y los tests de estructura pasan.
9. `terraform destroy` (ejecutado por el usuario) elimina todo sin intervención manual.
10. Revisión de IAM: sin `Action: "*"`; el único `Resource: "*"` es el de entrega de logs de Step Functions, justificado.
11. El recorrido completo (secciones 1 a 5 del plan de tiempo) cabe en **45 min** en el ensayo.

---

## 12. Fuera de alcance

- Bloques de edición de HCL en clase (M1, M2, cambio zip → imagen), sustituidos por análisis guiado.
- Extensiones E1–E7 del spec v3 (SNS, SQS, DLQ, fan-out, Glue en el workflow, Parquet, arquitectura incorrecta). Siguen como home lab.
- Backend remoto de Terraform, CI/CD, múltiples ambientes.
- EC2, ECS, EKS y el resto de lo listado en la sección 17 del spec v3.

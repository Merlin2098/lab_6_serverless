# SPEC — Laboratorio Sesión 06 (v3 · MVP)
## Serverless, Orquestación y Contenedores

**Curso:** AWS Data Engineer
**Sesión:** 06
**Duración:** **60 minutos** (partición de la sesión: 120 min teoría + 60 min laboratorio)
**Formato:** Deploy → Understand → Modify → Container → Troubleshoot → Verify, sobre infraestructura **Terraform ya preparada** (no se construye desde cero en vivo)
**Alcance:** Serverless; no se contempla despliegue práctico con EC2, ECS ni EKS.
**Versión:** v3 (4 de octubre de 2026), versión **MVP**. Las v1 y v2 están en `_versiones_previas/`. Los IDs L01–L10 y C01–C05 remiten a `INFORME_GAPS_Sesion_06.md`.

---

## 0. Qué cambió respecto a la v2

| Cambio | Motivo |
|---|---|
| Glue Job y Athena **salen del workflow**. **Glue Crawler + Data Catalog + Athena se usan para verificar el resultado final** del pipeline (bloque Verify) | Decisión de alcance (MVP) |
| El workflow termina en `Succeed` / `Fail` (sin SNS). **SNS, SQS, DLQ, idempotencia y fan-out pasan a extensiones** | Tiempo; fricción de la suscripción por correo |
| La Lambda ahora **escribe su resultado** en `processed/orders/`, que es lo que el crawler cataloga | Para poder verificar con Athena |
| Se añade el bloque **Verify** (8 min) y se reduce Retry/Catch a un solo cambio (Catch) | Tiempo |
| Docker se da por **instalado antes de la clase** (solo se comprueba en el pre-flight) | Decisión de alcance |
| Troubleshoot: el fallo inyectado pasa a ser un permiso faltante en el **execution role de la Lambda** (S3 `PutObject`), diagnosticable en CloudWatch y en el `$.error` del Catch | El Glue Job ya no está en el workflow |
| Patrón de EventBridge inicial deliberadamente amplio (`raw/`), que el alumno ajusta a `raw/*.csv` en M1 | Hace visible el efecto del filtro |
| Archivos de prueba y resultados esperados de Athena definidos (sección 3) | Criterio de éxito verificable |

---

## 1. Objetivo

Que el alumno despliegue, comprenda, modifique y diagnostique un **pipeline orientado a eventos y orquestado**, y verifique su resultado con las herramientas de las Sesiones 4–5 (Glue Crawler, Data Catalog, Athena):

```text
S3 raw/*.csv
   |  Object Created
   v
EventBridge  --regla (wildcard)-->  Step Functions (Standard)
                                       |
                                       v
                          Validator Lambda  (zip → container image desde ECR)
                          valida y, si es válido, escribe en processed/orders/
                                       |
                                     Choice
                                 /            \
                            válido           inválido / error (Catch)
                               |                  |
                           Succeed             Fail

                          ── verificación (fuera del workflow) ──
              S3 processed/orders/ → Glue Crawler → Data Catalog → Athena
```

| Servicio | Rol |
|---|---|
| S3 | Almacenamiento: origen del evento (`raw/`) y destino del resultado (`processed/`) |
| EventBridge | Detección y routing de eventos con filtro de contenido |
| Step Functions | Orquestación (Choice, Retry, Catch) |
| Lambda | Validación y escritura del resultado (serverless compute) |
| Docker + ECR | Empaquetado y registry de la imagen de la Lambda |
| IAM | Permisos mínimos por componente |
| CloudWatch | Logs y troubleshooting |
| Glue Crawler + Data Catalog + Athena | **Verificación** del resultado (herramientas de S4–S5) |

> Cada servicio debe tener una razón de existir. Al final, el alumno explica **por qué cada servicio ocupa ese lugar**.

---

## 2. Prerrequisitos y pre-flight (antes de la sesión)

| Prerrequisito | Detalle |
|---|---|
| Athena de S4–S5 | Workgroup de Athena y bucket de resultados ya configurados. **Definir los nombres exactos antes de la clase** (variables del stack). |
| Glue Data Catalog | Base de datos para el lab (por defecto una nueva, `s6_lab_db`, para no mezclarla con S4; parametrizable). El **crawler lo crea Terraform** apuntando a `s3://<bucket>/processed/orders/`. |
| Docker | **Instalado antes de la clase.** Pre-flight: `docker version` responde y el daemon está activo. |
| AWS CLI v2 y Terraform | Con credenciales del alumno; backend local; ECR y Lambda en la misma región. |
| Cuotas de Lambda | Las **cuentas nuevas tienen cuotas reducidas de concurrencia y memoria**. Revisar Service Quotas antes de la sesión. |
| EventBridge en S3 | Notificaciones a EventBridge **activadas** en el bucket (vienen desactivadas; tardan unos minutos en aplicar y la regla debe estar en la misma región). Lo deja listo Terraform en la preparación, no durante la clase. |
| Costos | Lambda, ECR, Glue Crawler y Athena generan costo mínimo; recordar `terraform destroy` al final. |

---

## 3. Caso de uso y archivos de prueba

Se reciben archivos CSV de operaciones logísticas en S3. Formato:

```csv
order_id,customer_id,amount,status
1001,C001,150.50,COMPLETED
1002,C002,320.00,COMPLETED
1003,C003,125.00,COMPLETED
```

El pipeline: (1) detecta el archivo (solo `raw/*.csv`), (2) inicia el workflow, (3) valida, (4) si es válido lo escribe en `processed/orders/` con **la misma clave** (por eso reprocesar un archivo no duplica datos), (5) termina en `Succeed` o `Fail`. Después, el alumno verifica el resultado con Crawler + Athena.

La Validator Lambda comprueba: extensión `.csv`, columnas requeridas (`order_id`, `customer_id`, `amount`, `status`), archivo no vacío y valores válidos en `amount`. Devuelve un resultado pequeño (se pasan `bucket` y `key`, no el contenido; límite de 256 KiB por estado):

```json
{ "valid": true, "records": 3, "output": "processed/orders/orders_2026_10_04.csv" }
```

Archivos de prueba (el instructor los entrega):

| Archivo | Contenido | Se usa en | Resultado |
|---|---|---|---|
| `orders_2026_10_04.csv` (F1) | 1001–1003, todos COMPLETED (150.50 + 320.00 + 125.00) | Deploy | Válido → `Succeed` |
| `orders_invalid.csv` | `amount` no numérico o columna faltante | Deploy | Inválido → `Fail` (`InvalidFile`), sin salida |
| `orders_2026_10_05.csv` (F2) | 1004 COMPLETED 210.00; 1005 CANCELLED 99.90 | Container | Válido → `Succeed` |
| `orders_2026_10_06.csv` (F3) | 1006 COMPLETED 75.00; 1007 COMPLETED 410.25 | Troubleshoot | Falla con el fallo inyectado; válido al corregir |
| `prueba.json`, `prueba.csv`, `prueba_invalida.csv` | Vacíos o inválidos | Modify (M1) | Ver sección 7 |

**Resultado esperado en Athena (criterio de éxito de Verify):**

| status | filas | suma de amount |
|---|---:|---:|
| COMPLETED | 6 | 1290.75 |
| CANCELLED | 1 | 99.90 |

Total: 7 filas. Las filas de `orders_invalid.csv` y de los archivos de prueba **no aparecen**.

---

## 4. Plan de tiempo (60 min)

| Bloque | Min | Qué hace el alumno |
|---|---:|---|
| 1. Deploy | 10 | `terraform apply`; sube F1 y el archivo inválido; ve `Succeed` y `Fail` en Step Functions |
| 2. Understand | 7 | Lee patrón de EventBridge, ASL y tabla de IAM |
| 3. Modify | 10 | (M1) Ajusta el filtro a `raw/*.csv`; (M2) añade Catch |
| 4. Container | 13 | Build + push a ECR; cambia la Lambda de .zip a imagen; procesa F2 |
| 5. Troubleshoot | 7 | Diagnostica y corrige un permiso faltante en el rol de la Lambda; reprocesa F3 |
| 6. Verify | 8 | Crawler → Data Catalog → Athena; compara con el resultado esperado |
| Cierre | 5 | Preguntas de reflexión |
| **Total** | **60** | |

Si el tiempo aprieta, el orden de recorte es: **(1)** M2 (Catch) pasa a demo del instructor; **(2)** Container pasa a demo del instructor. **No recortar Troubleshoot ni Verify**: son la parte que demuestra el resultado y el razonamiento. Medir en el ensayo el tiempo real del `docker build` y del crawler.

---

## 5. Bloque 1 — Deploy (10 min)

Terraform ya preparado despliega: bucket S3 (con EventBridge activado), regla de EventBridge con patrón **amplio** (`prefix: raw/`), state machine, Validator Lambda (.zip), repositorio ECR, Glue Crawler y base de datos del Catalog, y los roles IAM.

1. `terraform init` / `plan` / `apply` (backend local).
2. Subir un archivo válido y uno inválido:
   ```text
   aws s3 cp orders_2026_10_04.csv s3://<bucket>/raw/
   aws s3 cp orders_invalid.csv    s3://<bucket>/raw/
   ```
3. En la consola de Step Functions, abrir ambas ejecuciones: la primera termina en `Succeed`; la segunda en `Fail` (`InvalidFile`).
4. Comprobar que existe `processed/orders/orders_2026_10_04.csv` y que no existe salida del inválido.

---

## 6. Bloque 2 — Understand (7 min)

El alumno recorre, con apoyo de **Claude Code** (explicar, no generar):

1. **El evento:** qué recibe Step Functions desde EventBridge (`detail.bucket.name`, `detail.object.key`).
2. **El patrón de EventBridge:** por qué `raw/` y no todo el bucket. La Lambda escribe en `processed/`; con un patrón sobre todo el bucket, el pipeline **se dispararía a sí mismo** (invocación recursiva).
3. **La state machine (ASL):** `Task`, `Choice`, `Succeed`, `Fail` y el `Retry` para errores del servicio Lambda (ejemplo ilustrativo; validar en la consola):

```json
{
  "StartAt": "Validate",
  "States": {
    "Validate": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": { "FunctionName": "<validator-arn>", "Payload.$": "$" },
      "ResultPath": "$.validation",
      "Retry": [
        { "ErrorEquals": ["Lambda.ServiceException", "Lambda.AWSLambdaException",
                          "Lambda.SdkClientException", "Lambda.TooManyRequestsException"],
          "IntervalSeconds": 2, "MaxAttempts": 3, "BackoffRate": 2.0 }
      ],
      "Catch": [
        { "ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "HandleError" }
      ],
      "Next": "IsValid"
    },
    "IsValid": {
      "Type": "Choice",
      "Choices": [
        { "Variable": "$.validation.Payload.valid", "BooleanEquals": true, "Next": "PipelineSucceeded" }
      ],
      "Default": "InvalidFile"
    },
    "PipelineSucceeded": { "Type": "Succeed" },
    "InvalidFile": { "Type": "Fail", "Error": "InvalidFile", "Cause": "El archivo no cumple las reglas de validación" },
    "HandleError": { "Type": "Pass", "Next": "PipelineFailed" },
    "PipelineFailed": { "Type": "Fail", "Error": "PipelineError", "Cause": "Fallo inesperado; ver $.error" }
  }
}
```

La state machine entregada en Deploy **no incluye** `Catch`, `HandleError` ni `PipelineFailed`: los añade el alumno en M2.

4. **La tabla de roles IAM** (sección 13).
5. **Preguntas guía:** ¿qué hace EventBridge que no hace Lambda? ¿Qué decide el `Choice` y qué decide la Lambda? ¿Qué componente administra AWS y cuál el alumno?

---

## 7. Bloque 3 — Modify (10 min)

### M1 — Filtro de eventos (6 min)

Cambiar el patrón de la regla para procesar solo objetos dentro de `raw/` con extensión `.csv`.

> **Trampa conocida (L01):** `prefix` + `suffix` es la sintaxis de las notificaciones nativas de S3 (se combinan como AND). En un patrón de EventBridge, los valores de un arreglo son **OR**; `[{"prefix":"raw/"},{"suffix":".csv"}]` dejaría pasar `raw/prueba.json` y `otra/prueba.csv`. Usar `wildcard`:

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

Prueba (subir los tres archivos antes y después del cambio):

| Archivo subido | Con `raw/` (Deploy) | Con `raw/*.csv` (después de M1) |
|---|---|---|
| `raw/prueba.json` | Dispara; falla la validación (`InvalidFile`) | **No dispara** |
| `otra/prueba.csv` | No dispara | No dispara |
| `raw/prueba_invalida.csv` | Dispara; falla la validación | Dispara; falla la validación |

### M2 — Catch (4 min)

Añadir al `Task` `Validate` el bloque `Catch` y los estados `HandleError` (Pass) y `PipelineFailed` (Fail) del ASL de la sección 6.

- **Retry** = volver a intentar errores recuperables (ya está para los errores del servicio Lambda).
- **Catch** = cuando se agotan los reintentos o el error no es recuperable, capturarlo, **guardar el error en `$.error`** (`ResultPath`) y dirigir el workflow a otra ruta.

`HandleError` es un `Pass` a propósito: en una extensión (E1) se reemplaza por una publicación en SNS.

---

## 8. Bloque 4 — Container (13 min)

Convertir la Validator Lambda de **.zip a container image**, publicarla en ECR y comprobar que sigue funcionando. Mensaje pedagógico:

> **ECR almacena y distribuye la imagen; Lambda proporciona el compute serverless que la ejecuta.**

```text
Dockerfile --docker build--> Docker Image --docker push--> ECR --> Lambda (container image)
```

Dockerfile de ejemplo (usar la versión de Python vigente en la lista de runtimes de Lambda):

```text
FROM public.ecr.aws/lambda/python:<versión>
COPY requirements.txt ${LAMBDA_TASK_ROOT}
RUN pip install -r requirements.txt
COPY app.py ${LAMBDA_TASK_ROOT}
CMD ["app.handler"]
```

El instructor entrega un script `build_push` (bash o PowerShell) que ejecuta, en orden:

```text
aws ecr get-login-password --region <region> | docker login --username AWS --password-stdin <cuenta>.dkr.ecr.<region>.amazonaws.com
docker build --platform linux/amd64 --provenance=false -t validator:1.0.0 .
docker tag validator:1.0.0 <repo-uri>:1.0.0
docker push <repo-uri>:1.0.0
```

Después, aplicar el cambio en Terraform (`package_type = "Image"` con `image_uri`) y subir **F2** (`orders_2026_10_05.csv`) para comprobar que la ejecución termina en `Succeed` con la Lambda desde imagen.

Trabajar: repository, authentication (token válido **12 horas**), image, **tag y digest** (el digest aparece al hacer push), push/pull.

Puntos que rompen en clase (L05):

| Punto | Detalle |
|---|---|
| Imagen base | Usar una imagen base de Lambda (incluye el Runtime Interface Client); `CMD` debe apuntar al handler |
| `--provenance=false` | Las imágenes con atestaciones de `buildx` pueden ser rechazadas por Lambda (`InvalidImage`) |
| Arquitectura | Una sola; debe coincidir con la de la función (x86_64 aquí). No se admiten imágenes multi-arquitectura |
| Región | ECR y Lambda en la misma región; solo imágenes Linux; hasta 10 GB |
| Permisos | Política del repositorio con `ecr:BatchGetImage` y `ecr:GetDownloadUrlForLayer` para `lambda.amazonaws.com` |
| Inmutabilidad | Repositorio con tag immutability: cada cambio de imagen exige un tag nuevo |

Notas de Terraform (práctica; no proviene de la documentación de AWS): la función con `package_type = "Image"` necesita que la imagen **ya exista** en ECR; por eso el Deploy usa .zip y el cambio se hace después del push. **Verificar en el ensayo** cómo se comporta el provider al cambiar el tipo de paquete de una función existente (puede reemplazarla); si hay problemas, definir una segunda función `validator-image` y cambiar el ARN que usa la state machine por variable.

---

## 9. Bloque 5 — Troubleshoot (7 min)

**Escenario único (obligatorio):** el instructor aplica una variante del stack (por ejemplo, una variable de Terraform `inject_fault`; diseño a definir) que **quita `s3:PutObject` sobre `processed/orders/*` del execution role** de la Validator Lambda. Al subir **F3** (`orders_2026_10_06.csv`), la ejecución falla.

El alumno debe:

1. Responder: **¿en qué componente falló el pipeline?** Ruta de diagnóstico (L10): EventBridge ✓ (la ejecución existe) → Step Functions ✓ (arrancó y entró a `Validate`) → Lambda ✗. Leer el error en el `$.error` que llegó a `PipelineFailed` y en los logs de CloudWatch de la Lambda (`AccessDenied` en `PutObject`).
2. Identificar el recurso y la acción que faltan, y corregir la política del rol (en Terraform).
3. Volver a subir F3 y confirmar `Succeed`.

**Claude Code:** interpretar el mensaje de error y explicar qué permiso falta; **no** reescribir la política completa (y cuestionar cualquier sugerencia de `Action: "*"`).

Escenarios alternativos para home lab: imagen con arquitectura incorrecta o `CMD` mal definido (la Lambda falla al invocar).

---

## 10. Bloque 6 — Verify (8 min)

El pipeline "funcionó" cuando el resultado se puede consultar. Se usan las herramientas de S4–S5:

1. **Glue Crawler:** ejecutarlo (consola o CLI):
   ```text
   aws glue start-crawler --name <crawler>
   ```
   Esperar a que vuelva a estado `READY`.
2. **Data Catalog:** abrir la base `s6_lab_db` y revisar la tabla creada (nombre derivado de la carpeta, `orders`), la ubicación en `processed/orders/` y las columnas `order_id`, `customer_id`, `amount`, `status`.
3. **Athena** (workgroup de S4):
   ```text
   SELECT status, COUNT(*) AS filas, SUM(amount) AS total
   FROM s6_lab_db.orders
   GROUP BY status;
   ```
4. **Comparar** con el resultado esperado de la sección 3 (COMPLETED 6 / 1290.75; CANCELLED 1 / 99.90) y comprobar que el archivo inválido no aparece.
5. **Comprobación de idempotencia (1 min, opcional):** volver a subir `orders_2026_10_04.csv`. El pipeline lo reprocesa sobre la **misma clave**; repetir la consulta: los totales **no cambian**.

Verificar en el ensayo: que el crawler detecte los nombres de columna del CSV (si no, usar un classifier CSV con encabezado) y el tiempo que tarda. Si el crawler tarda, el instructor muestra el resultado de uno ya ejecutado en su cuenta mientras el de los alumnos termina.

---

## 11. Cierre (5 min)

Criterio de éxito: ejecución exitosa end-to-end con la Lambda **desde imagen**; el resultado de Athena coincide con la tabla esperada; el alumno explica por qué falló el escenario de troubleshooting y por qué `raw/*.csv` es un filtro correcto.

### Preguntas de reflexión (elegir 5)

**Arquitectura**
1. ¿Por qué utilizar EventBridge y no las notificaciones nativas de S3?
2. ¿Qué problema resuelve Step Functions aquí? ¿Qué decide el `Choice`?
3. ¿Por qué el Crawler + Data Catalog + Athena (y no el código de la Lambda) para verificar el resultado?

**Serverless**
4. ¿Qué parte de la infraestructura administra AWS?
5. ¿Qué limitaciones tendría Lambda si los archivos fueran de varios GB?

**Containers**
6. ¿Qué almacena ECR? ¿Quién ejecuta la imagen?
7. ¿Qué diferencia hay entre tag y digest?
8. ¿Por qué no necesitamos ECS/EKS para este laboratorio?

**Resiliencia**
9. ¿Qué error debería resolverse mediante Retry y cuál mediante Catch?
10. ¿Qué ocurre si el mismo evento llega dos veces? (EventBridge entrega at-least-once; la clave de salida determinística evita duplicados)

---

## 12. Extensiones y home lab (fuera de los 60 min)

### E1 — SNS: notificaciones de éxito y error

Reemplazar `HandleError` (Pass) y `PipelineSucceeded` por publicaciones en un topic SNS (`sns:Publish`). Una suscripción por correo requiere confirmar la suscripción desde el mensaje recibido (práctica común; no verificada en esta revisión).

### E2 — SQS: procesamiento asíncrono y desacoplamiento

```text
Step Functions --> SQS --> Lambda Worker --> S3 processed/
```

Diseño corregido (L03): con `sqs:sendMessage` simple el workflow **no espera al Worker**. Opciones:

1. **Recomendada:** `sqs:sendMessage.waitForTaskToken`. El mensaje lleva `$$.Task.Token`; el Worker llama a `SendTaskSuccess` o `SendTaskFailure` al terminar; definir `HeartbeatSeconds`/`TimeoutSeconds`. Requiere Standard. El Worker necesita `states:SendTaskSuccess` y `states:SendTaskFailure`.
2. Fire-and-forget: el Worker publica en SNS y el workflow no notifica éxito.

### E3 — Dead-Letter Queue (L04)

- La DLQ se define en la **cola origen** (redrive policy con `maxReceiveCount`, recomendado ≥ 5). La DLQ configurada en la función Lambda es para invocaciones asíncronas.
- Visibility timeout de la cola ≥ **6×** el timeout de la función.
- Si la función lanza una excepción, **todo el lote** vuelve a la cola; usar `ReportBatchItemFailures` o `batch size = 1`.
- Rol del Worker: `AWSLambdaSQSQueueExecutionRole` (+ `kms:Decrypt` si la cola está cifrada).

### E4 — SNS + SQS (fan-out)

Cada cola necesita una access policy que permita `sqs:SendMessage` al servicio `sns.amazonaws.com` con `aws:SourceArn` del topic. Probar una **filter policy** de suscripción.

### E5 — Glue en el workflow

Añadir al state machine el Glue Job de S4 con `.sync` (o un estado que invoque el crawler mediante la integración con el SDK de AWS, que no tiene `.sync` y requiere esperar su finalización), de modo que la verificación deje de ser manual.

### E6 — Parquet con dependencias en la imagen

Escribir la salida en Parquet (la imagen incluye la dependencia necesaria) y comparar el escaneo en Athena frente a CSV (lección de S4).

### E7 — Arquitectura incorrecta

Construir la imagen para otra arquitectura que la de la función y diagnosticar el fallo de invocación.

---

## 13. IAM por componente (L06)

Principio: cada componente tiene únicamente los permisos necesarios. Evitar permisos administrativos.

| Componente | Permisos |
|---|---|
| Regla de EventBridge → Step Functions | Rol con `states:StartExecution` |
| Step Functions → Lambda | `lambda:InvokeFunction` sobre la Validator |
| Validator Lambda (execution role) | Logs en CloudWatch; `s3:GetObject` sobre `raw/*`; **`s3:PutObject` sobre `processed/orders/*`** (el permiso que se quita en Troubleshoot) |
| Lambda ← ECR | Política del repositorio o rol: `ecr:BatchGetImage`, `ecr:GetDownloadUrlForLayer` |
| Glue Crawler (rol) | Política gestionada de servicio de Glue + lectura de `processed/orders/` en S3 |
| Alumno (Athena) | Los permisos de Athena y del bucket de resultados ya configurados en S4 |
| (E1) Step Functions → SNS | `sns:Publish` |
| (E2) Worker SQS → Lambda | `AWSLambdaSQSQueueExecutionRole`, S3 limitado a `raw/` y `processed/`, `states:SendTask*` si hay callback |
| (E4) SNS → SQS | Access policy de la cola |

Validar el stack completo antes de la clase: los permisos exactos del crawler y de Athena dependen de la configuración de S4.

---

## 14. Terraform, Claude Code y observabilidad

- **Terraform:** metodología IaC del curso con backend local. El stack de S6 incluye S3 (con EventBridge), regla de EventBridge, Step Functions, Lambda, ECR, base de datos y crawler de Glue, e IAM. La publicación de la imagen Docker es una etapa explícita del laboratorio.
- **Destroy:** el repositorio ECR con imágenes requiere borrado forzado (práctica; verificar el atributo del provider) para que `terraform destroy` no falle.
- **Claude Code** (explorar e interpretar, no generar la solución): en *Understand*, explicar el ASL y el patrón de EventBridge; en *Container*, interpretar errores de `docker build/push` o el estado `InvalidImage` de Lambda; en *Troubleshoot*, explicar el error de permisos sin reescribir la política.
- **Observabilidad:** CloudWatch ya se trabaja previamente, así que no hay bloque propio. Ruta de diagnóstico: ejecución en Step Functions → `$.error` → logs de la Lambda en CloudWatch (→ métricas de EventBridge `FailedInvocations` si la ejecución ni siquiera arranca).

---

## 15. Pendientes de definir antes de la clase

1. Nombres de workgroup de Athena, bucket de resultados y base de datos del Catalog (variables del stack).
2. Diseño del fallo inyectado (`inject_fault` u otra variante) y cómo se aplica en clase.
3. Que el crawler detecte los encabezados del CSV y su tiempo de ejecución real.
4. Comportamiento del provider de Terraform al cambiar `package_type` de una función existente.
5. Script `build_push` (bash y PowerShell) y tiempo real del `docker build`.
6. Contenido exacto de `orders_invalid.csv` y de los archivos de prueba.

---

## 16. Resultado esperado

Al finalizar, el alumno debería poder explicar una arquitectura como:

```text
EVENT --> ROUTING --> ORCHESTRATION --> COMPUTE (desde imagen en ECR) --> STORAGE --> CATALOG + QUERY
```

Y, sobre todo, responder:

> **¿Por qué cada servicio ocupa ese lugar dentro del pipeline?**

La solución demuestra que un pipeline de datos puede dispararse, coordinarse y producir un resultado consultable sin administrar servidores:

> **S3 recibe el archivo → EventBridge detecta el evento → Step Functions coordina → Lambda (desde imagen en ECR) valida y escribe el resultado → Crawler y Data Catalog lo catalogan → Athena lo consulta.**

---

## 17. Fuera de alcance

No se contempla laboratorio práctico de:

- EC2;
- ECS;
- EKS;
- Kubernetes;
- ALB;
- networking avanzado;
- service mesh;
- Helm;
- administración avanzada de containers;
- Glue Jobs dentro del workflow, Redshift;
- SNS, SQS, DLQ y fan-out como parte obligatoria (son extensiones E1–E4).

ECS/EKS pueden aparecer únicamente en la teoría para explicar el ecosistema de containers.
